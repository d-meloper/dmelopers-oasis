"""Shared command transport fixtures, including real local Windows byte pipes."""
import copy
import os
from pathlib import Path
import queue
import tempfile
import threading
import time
import unittest
from unittest import mock

from oasis_harness import notifications, sessions, shared_runtime as shared
from oasis_harness.common import HarnessError


class NativeFixture:
    def __init__(self, originator):
        self.originator = originator
        self.calls = []
        self.events = queue.Queue()
        self.closed = False
        self.gate = None
        self.started = threading.Event()

    def call(self, method, params, timeout=30):
        self.calls.append((method, copy.deepcopy(params)))
        self.started.set()
        if self.gate is not None and method == "thread/read":
            self.gate.wait(2)
        if params.get("reject"):
            raise sessions.NativeError(method, {"code": -32602, "message": "Fixture rejected"})
        if params.get("delay"):
            time.sleep(params["delay"])
        if params.get("uncertain"):
            raise HarnessError("Fixture accepted mutation but lost response; outcome uncertain")
        if method in ("thread/start", "thread/resume"):
            return {"thread": {"id": params.get("threadId", "created-" + self.originator)}}
        return {"originator": self.originator, "value": params.get("value"), "thread": {"id": params.get("threadId")}}

    def wait_events(self, timeout=30):
        try:
            item = self.events.get(timeout=timeout)
        except queue.Empty:
            return []
        return [] if item is None else [item]

    def diagnostics(self):
        return {"state": "closed" if self.closed else "connected", "rpc_by_method": {"initialize": 1}}

    def close(self):
        self.closed = True
        self.events.put(None)


class IssuedFixture(NativeFixture):
    def __init__(self, originator):
        super().__init__(originator)
        self.next_turn = "issued-turn"
        self.history = [{"id": self.next_turn, "status": "completed"}]
        self.history_started = threading.Event()
        self.history_gate = None
        self.history_error = None
        self.on_start = None

    def call(self, method, params, timeout=30):
        if method == "turn/start":
            self.calls.append((method, copy.deepcopy(params)))
            if self.on_start:
                self.on_start()
            return {"turn": {"id": self.next_turn, "status": "inProgress"}}
        if method == "thread/turns/list":
            self.calls.append((method, copy.deepcopy(params)))
            self.history_started.set()
            if self.history_gate:
                self.history_gate.wait(2)
            if self.history_error:
                raise self.history_error
            return {"data": copy.deepcopy(self.history)}
        return super().call(method, params, timeout)


class SharedRuntimeContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="oasis 공유 😶 ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.servers = {}
        def factory(originator):
            server = NativeFixture(originator)
            self.servers[originator] = server
            return server
        self.pool = shared.Pool(factory)
        self.addCleanup(self.pool.close)

    def host(self):
        host = shared.Host(self.root, "fixture-token", 1, self.pool)
        host.__enter__()
        self.addCleanup(host.close)
        row = {"ipc": host.descriptor(), "token": "fixture-token", "generation": 1}
        return host, row

    def client(self, row, originator="created-channel"):
        client = shared.Client(row, originator)
        self.addCleanup(client.close)
        return client

    def until(self, condition):
        deadline = time.monotonic() + 2
        while not condition():
            if time.monotonic() >= deadline:
                self.fail("Fixture transition did not settle")
            time.sleep(0.005)

    def test_native_connection_reused_after_cli_lease_release(self):
        host, row = self.host()
        first = self.client(row)
        result = first.call("thread/start", {"value": "한글 😶"})
        first.close()
        second = self.client(row)
        self.assertEqual(second.call("thread/read", {"threadId": result["thread"]["id"], "value": "그대로"})["value"], "그대로")
        self.assertEqual(len(self.servers), 1)
        report = self.pool.diagnostics()
        self.assertEqual(report["native_rpc_by_method"], {"initialize": 1, "thread/start": 1, "thread/read": 1})
        self.assertEqual(report["ipc_requests"], 2)
        self.assertTrue(host.busy())
        second.close()
        self.until(lambda: not host.busy())
        self.assertFalse(self.servers["created-channel"].closed)

    def test_creation_originator_and_thread_routing_are_preserved(self):
        owner = self.pool.facade("creator")
        owner.call("thread/read", {"threadId": "external"})
        self.assertFalse(self.pool.event_covered("external"))
        identity = owner.call("thread/start", {})["thread"]["id"]
        self.assertTrue(self.pool.event_covered(identity))
        observer = self.pool.facade("oasis-notifications")
        answer = observer.call("thread/read", {"threadId": identity})
        self.assertEqual(answer["originator"], "creator")
        self.assertEqual(set(self.servers), {"creator"})

    def test_default_read_after_writer_boundary_does_not_join_observation(self):
        observed = self.pool.facade("shared").observation()
        observed.call("thread/start", {})
        native = self.servers["shared"]
        native.started.clear()
        native.gate = threading.Event()
        replies = []
        first = threading.Thread(target=lambda: replies.append(observed.call("thread/read", {"threadId": "same"})))
        second = threading.Thread(target=lambda: replies.append(self.pool.facade("shared").call("thread/read", {"threadId": "same"})))
        first.start()
        self.assertTrue(native.started.wait(1))
        second.start()
        self.until(lambda: len(native.calls) == 3)
        native.gate.set()
        first.join(2)
        second.join(2)
        self.assertEqual(len(replies), 2)
        self.assertEqual(self.pool.diagnostics()["coalesced_reads"], 0)

    def test_simultaneous_identical_reads_share_only_inflight_result(self):
        server = self.pool.facade("shared").observation()
        server.call("thread/start", {})
        native = self.servers["shared"]
        native.started.clear()
        native.gate = threading.Event()
        replies = []
        first = threading.Thread(target=lambda: replies.append(server.call("thread/read", {"threadId": "same"})))
        second = threading.Thread(target=lambda: replies.append(server.call("thread/read", {"threadId": "same"})))
        first.start()
        self.assertTrue(native.started.wait(1))
        second.start()
        self.until(lambda: self.pool.diagnostics()["coalesced_reads"] == 1)
        native.gate.set()
        first.join(2)
        second.join(2)
        self.assertEqual(len(replies), 2)
        self.assertEqual([method for method, _ in native.calls].count("thread/read"), 1)
        server.call("thread/read", {"threadId": "same"})
        self.assertEqual([method for method, _ in native.calls].count("thread/read"), 2)

    def test_independent_clients_get_reverse_order_rpc_responses(self):
        _, row = self.host()
        first, second = self.client(row), self.client(row)
        first.call("thread/start", {})
        results = []
        slow = threading.Thread(target=lambda: results.append(first.call("turn/start", {"value": "slow", "delay": 0.15})))
        slow.start()
        time.sleep(0.02)
        results.append(second.call("turn/start", {"value": "fast"}))
        slow.join(2)
        self.assertEqual([result["value"] for result in results], ["fast", "slow"])

    def test_deadline_or_uncertain_mutation_never_replays_or_closes_peer(self):
        _, row = self.host()
        first, second = self.client(row), self.client(row)
        first.call("thread/start", {})
        with self.assertRaises(sessions.DeadlineExceeded):
            first.call("turn/start", {"value": "accepted-once", "delay": 0.15}, timeout=0.03)
        self.assertEqual(second.call("turn/start", {"value": "peer"})["value"], "peer")
        self.assertEqual(sum(params.get("value") == "accepted-once" for _, params in self.servers["created-channel"].calls), 1)
        with self.assertRaisesRegex(HarnessError, "outcome uncertain"):
            second.call("turn/start", {"uncertain": True})
        self.assertFalse(self.servers["created-channel"].closed)

    def test_native_rejection_retains_method_code_and_type(self):
        _, row = self.host()
        client = self.client(row)
        with self.assertRaises(sessions.NativeError) as caught:
            client.call("turn/start", {"reject": True})
        self.assertEqual(caught.exception.code, -32602)
        self.assertEqual(caught.exception.method, "turn/start")

    def test_pre_send_expiry_uses_complete_native_counters_instead_of_attempts(self):
        server = NativeFixture("counted")
        server.diagnostics = lambda: {"state": "connected", "rpc_by_method_complete": True,
                                      "rpc_by_method": {"initialize": 1}}
        server.call = mock.Mock(side_effect=sessions.DeadlineExceeded("Expired before native write"))
        pool = shared.Pool(lambda _: server)
        self.addCleanup(pool.close)
        with self.assertRaises(sessions.DeadlineExceeded):
            pool.facade("counted").call("turn/start", {})
        self.assertEqual(pool.counts["counted"]["turn/start"], 1)
        self.assertEqual(pool.diagnostics()["native_rpc_by_method"], {"initialize": 1})

    def test_existing_legacy_owner_uses_direct_without_replacing_it(self):
        legacy = {"status": "running", "token": "old-token", "generation": 1}
        direct = mock.Mock()
        with mock.patch.object(notifications, "ensure_running", return_value=legacy) as ensure:
            with mock.patch.object(sessions, "AppServer", return_value=direct) as constructor:
                self.assertIs(shared.connect(self.root, "same-originator"), direct)
        ensure.assert_called_once_with(self.root)
        constructor.assert_called_once_with("same-originator", notification_profile="command")

    def test_explicit_scope_only_changes_default_command_factory(self):
        with mock.patch.object(shared, "connect", return_value="shared") as connect:
            with mock.patch.object(sessions, "AppServer", return_value="direct"):
                self.assertEqual(sessions.command_server("bare"), "direct")
                with sessions.command_scope(self.root, channel="original"):
                    self.assertEqual(sessions.command_server("later-command"), "shared")
                self.assertEqual(sessions.command_server("bare"), "direct")
        connect.assert_called_once_with(str(self.root), "original")

    def test_wrong_generation_or_token_cannot_acquire_lease_or_forward(self):
        host, row = self.host()
        wrong = {**row, "token": "different-token"}
        with self.assertRaises((EOFError, OSError, HarnessError)):
            self.client(wrong)
        self.assertFalse(host.busy())
        self.assertEqual(self.pool.diagnostics()["native_rpc_by_method"], {})

    def test_same_user_verification_is_required_before_handshake(self):
        _, row = self.host()
        with mock.patch.object(shared, "_same_user", return_value=False):
            with self.assertRaises(HarnessError):
                self.client(row)
        self.assertEqual(self.pool.diagnostics()["native_rpc_by_method"], {})

    def test_read_only_diagnostics_do_not_renew_owner_or_native_reads(self):
        _, row = self.host()
        previous = self.pool.last_activity
        report = shared.read_diagnostics(self.root, row)
        self.assertEqual(report["ipc_requests"], 0)
        self.assertEqual(report["native_rpc_by_method"], {})
        self.assertEqual(self.pool.last_activity, previous)
        self.assertFalse(self.pool.busy())

    def test_shutdown_admission_barrier_cannot_kill_accepted_lease(self):
        host, row = self.host()
        client = self.client(row)
        self.assertFalse(host.begin_shutdown())
        client.call("thread/start", {})
        client.close()
        self.until(lambda: not host.busy())
        self.assertTrue(host.begin_shutdown())
        with self.assertRaises((EOFError, OSError, HarnessError)):
            self.client(row)
        self.assertEqual(self.pool.diagnostics()["native_rpc_by_method"]["thread/start"], 1)

    def test_aggregate_reader_retains_exact_terminal_event(self):
        server = self.pool.facade("creator")
        identity = server.call("thread/start", {})["thread"]["id"]
        self.pool.drain_events()
        event = {"method": "turn/completed", "params": {"threadId": identity, "turn": {"id": "own-turn"}}}
        self.servers["creator"].events.put(event)
        self.assertEqual(self.pool.wait_events(1), [event])

    def test_client_event_fanout_does_not_consume_observer_or_another_lease(self):
        _, row = self.host()
        first, second = self.client(row), self.client(row)
        identity = first.call("thread/start", {})["thread"]["id"]
        self.assertTrue(second.event_covered(identity))
        self.pool.drain_events()
        event = {"method": "turn/completed", "params": {"threadId": identity, "turn": {"id": "own-turn"}}}
        self.servers["created-channel"].events.put(event)
        self.assertEqual(first.wait_events(1), [event])
        self.assertEqual(second.wait_events(1), [event])
        self.assertEqual(self.pool.drain_events(), [event])
        self.assertEqual(first.drain_events(), [])
        self.assertEqual(first.diagnostics()["connections"], 1)

    def test_expired_owner_still_releases_handles_and_event_readers(self):
        self.pool.facade("creator").call("thread/start", {})
        reader = self.pool.channels["creator"]["reader"]
        with sessions.deadline_scope(timeout=0.01):
            time.sleep(0.015)
            self.pool.close()
        self.assertTrue(self.servers["creator"].closed)
        self.assertFalse(reader.is_alive())

    def test_initializing_caller_timeout_does_not_expire_shared_upstream(self):
        gate = threading.Event()
        def delayed(originator):
            gate.wait(1)
            server = NativeFixture(originator)
            self.servers[originator] = server
            return server
        pool = shared.Pool(delayed)
        self.addCleanup(pool.close)
        with self.assertRaises(sessions.DeadlineExceeded):
            pool.facade("creator").call("thread/start", {}, timeout=0.01)
        gate.set()
        self.assertEqual(pool.facade("creator").call("thread/start", {})["thread"]["id"], "created-creator")
        self.assertEqual(len(self.servers["creator"].calls), 1)

    def test_exact_active_turn_keeps_owner_until_matching_completion(self):
        server = self.pool.facade("creator")
        identity = server.call("thread/start", {})["thread"]["id"]
        native = self.servers["creator"]
        native.events.put({"method": "turn/started", "params": {"threadId": identity, "turn": {"id": "active"}}})
        self.until(lambda: self.pool.busy())
        native.events.put({"method": "turn/completed", "params": {"threadId": identity, "turn": {"id": "old"}}})
        self.until(lambda: len(self.pool.completed_turns) == 1)
        self.assertTrue(self.pool.busy())
        native.events.put({"method": "turn/completed", "params": {"threadId": identity, "turn": {"id": "active"}}})
        self.until(lambda: not self.pool.busy())

    def test_terminal_event_before_start_response_cannot_resurrect_lease(self):
        self.pool.facade("creator").call("thread/start", {})
        identity = "created-creator"
        with self.pool.lock:
            self.pool._turn_event({"method": "turn/completed", "params": {"threadId": identity, "turn": {"id": "already-done"}}})
            self.pool._turn_response("turn/start", {"threadId": identity}, {"turn": {"id": "already-done", "status": "inProgress"}})
        self.assertFalse(self.pool.busy())

    def test_terminal_history_releases_only_exact_active_turn_after_event_loss(self):
        self.pool.facade("creator").call("thread/start", {})
        identity = "created-creator"
        self.pool.active_turns.update({(identity, "finished"), (identity, "newer")})
        previous = self.pool.last_activity
        with self.pool.lock:
            self.pool._turn_response("thread/turns/list", {"threadId": identity}, {"data": [{"id": "finished", "status": "completed"}]})
        self.assertEqual(self.pool.active_turns, {(identity, "newer")})
        self.assertGreater(self.pool.last_activity, previous)

    def test_buffered_terminal_batch_precedes_connection_failure(self):
        self.pool.facade("creator").call("thread/start", {})
        listener = self.pool.listen("creator")
        self.pool.drain_events()
        event = {"method": "turn/completed", "params": {"threadId": "created-creator", "turn": {"id": "last"}}}
        self.servers["creator"].events.put(event)
        self.servers["creator"].close()
        self.until(lambda: self.pool.event_error is not None)
        self.assertEqual(self.pool.drain_events(), [event])
        with self.assertRaisesRegex(HarnessError, "connection ended"):
            self.pool.drain_events()
        self.assertEqual(listener.wait(0), [event])
        with self.assertRaisesRegex(HarnessError, "connection ended"):
            listener.wait(0)

    def issued(self):
        native = IssuedFixture("sender")
        pool = shared.Pool(lambda _: native)
        self.addCleanup(pool.close)
        return native, pool, pool.facade("sender")

    @staticmethod
    def status(native, state):
        native.events.put({"method": "thread/status/changed", "params": {
            "threadId": "external-parent", "status": {"type": state}}})

    def test_unsubscribed_issued_turn_idle_verifies_once_and_releases_owner(self):
        native, pool, server = self.issued()
        server.call("turn/start", {"threadId": "external-parent"})
        self.assertFalse(pool.event_covered("external-parent"))
        self.assertTrue(pool.busy())
        native.history_gate = threading.Event()
        self.status(native, "idle")
        self.assertTrue(native.history_started.wait(1))
        for _ in range(100):
            self.status(native, "idle")
        native.history_gate.set()
        self.until(lambda: not pool.busy())
        self.assertEqual([method for method, _ in native.calls].count("thread/turns/list"), 1)
        self.assertEqual(pool.diagnostics()["reconciliations"]["issued_turn_idle"], 1)
        self.assertEqual(pool.diagnostics()["lifetime_recovery_required"], 0)
        self.assertFalse(pool.event_covered("external-parent"))

    def test_final_lifetime_worker_release_wakes_owner_after_prior_activity_was_consumed(self):
        native, pool, server = self.issued()
        server.call("turn/start", {"threadId": "external-parent"})
        ready, release, waiting, finished = (threading.Event() for _ in range(4))
        actual_call, actual_wait = pool.call, pool.changed.wait_for
        result = []

        def paused_call(originator, method, params, timeout=30, **kwargs):
            value = actual_call(originator, method, params, timeout, **kwargs)
            if method == "thread/turns/list":
                ready.set()
                release.wait(2)
            return value

        def observed_wait(predicate, timeout=None):
            waiting.set()
            return actual_wait(predicate, timeout)

        def owner():
            result.extend(pool.wait_events(2))
            finished.set()

        pool.call = paused_call
        self.status(native, "idle")
        self.assertTrue(ready.wait(1))
        self.assertFalse(pool.active_turns)
        self.assertTrue(pool.busy())
        pool.drain_events()
        observer = threading.Thread(target=owner, daemon=True)
        try:
            with mock.patch.object(pool.changed, "wait_for", side_effect=observed_wait):
                observer.start()
                self.assertTrue(waiting.wait(1))
                with pool.lock:
                    worker = pool.lifetime_workers["external-parent"]
                release.set()
                worker.join(1)
                self.assertFalse(worker.is_alive())
                self.assertFalse(pool.busy())
                self.assertTrue(finished.wait(1))
                self.assertEqual(result, [{"method": "oasis/shared/activity", "params": {}}])
        finally:
            release.set()
            pool.close()
            observer.join(1)

    def test_stale_idle_cannot_release_a_newer_active_issued_turn(self):
        native, pool, server = self.issued()
        server.call("turn/start", {"threadId": "external-parent"})
        native.history_gate = threading.Event()
        self.status(native, "idle")
        self.assertTrue(native.history_started.wait(1))
        native.next_turn = "newer-turn"
        server.call("turn/start", {"threadId": "external-parent"})
        native.history = [{"id": "issued-turn", "status": "completed"}, {"id": "newer-turn", "status": "inProgress"}]
        native.history_gate.set()
        self.until(lambda: not pool.lifetime_workers)
        self.assertEqual(pool.active_turns, {("external-parent", "newer-turn")})
        self.assertTrue(pool.busy())
        self.assertEqual([method for method, _ in native.calls].count("thread/turns/list"), 1)
        native.history[1]["status"] = "completed"
        self.status(native, "active")
        self.status(native, "idle")
        self.until(lambda: not pool.busy())
        self.assertEqual([method for method, _ in native.calls].count("thread/turns/list"), 2)

    def test_idle_before_start_response_is_retained_for_exact_turn_verification(self):
        native, pool, server = self.issued()
        def early_idle():
            self.status(native, "idle")
            self.until(lambda: "idle" in pool.starting_turns.get(("sender", "external-parent"), {}).values())
        native.on_start = early_idle
        server.call("turn/start", {"threadId": "external-parent"})
        self.until(lambda: not pool.busy())
        self.assertEqual([method for method, _ in native.calls].count("thread/turns/list"), 1)

    def test_unsupported_issued_turn_verification_stays_finite_and_retains_work(self):
        native, pool, server = self.issued()
        native.history_error = sessions.NativeError("thread/turns/list", {"code": -32601, "message": "Fixture unsupported"})
        server.call("turn/start", {"threadId": "external-parent"})
        self.status(native, "idle")
        self.until(lambda: pool.diagnostics()["lifetime_recovery_required"] == 1)
        self.assertTrue(pool.busy())
        self.status(native, "idle")
        self.status(native, "idle")
        time.sleep(0.03)
        self.assertEqual([method for method, _ in native.calls].count("thread/turns/list"), 1)
        self.assertEqual(pool.active_turns, {("external-parent", "issued-turn")})

    def test_invalid_json_is_rejected_without_deserialization(self):
        for value in (b'{"x":1,"x":2}', b'{"x":NaN}', b'[]', b'\xff'):
            with self.assertRaises(HarnessError):
                shared._decode(value)
        with mock.patch.object(shared, "MAX_BYTES", 3):
            with self.assertRaisesRegex(HarnessError, "size"):
                shared._encode({"payload": "too big"})


if __name__ == "__main__":
    unittest.main()
