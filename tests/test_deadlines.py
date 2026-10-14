"""Absolute native operation budgets; no real chats or host configuration."""
import io
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from oasis_harness import sessions, workflows
from oasis_harness.common import HarnessError
from tests.test_session_transport import InjectedTransport
from tests.test_sessions import NativeFixture


class DeadlineContracts(unittest.TestCase):
    def connect(self, wire):
        for patcher in (patch.dict(os.environ, {}, clear=True),
                        patch("oasis_harness.sessions.shutil.which", return_value="fixture-codex"),
                        patch("oasis_harness.sessions._ProxyTransport", return_value=wire)):
            patcher.start()
            self.addCleanup(patcher.stop)
        return sessions.AppServer("deadline-fixture")

    def test_scope_uses_one_absolute_clock_and_nested_scope_cannot_extend_it(self):
        clock = [100]
        with patch("oasis_harness.sessions.time.monotonic", side_effect=lambda: clock[0]):
            with sessions.deadline_scope(timeout=5) as deadline:
                self.assertEqual(deadline, 105)
                clock[0] = 102
                self.assertEqual(sessions.remaining_timeout(30), 3)
                with sessions.deadline_scope(timeout=100) as nested:
                    self.assertEqual(nested, 105)
                with sessions.deadline_scope(timeout=1) as nested:
                    self.assertEqual(nested, 103)
                self.assertEqual(sessions.remaining_timeout(30), 3)
                clock[0] = 105
                with self.assertRaises(sessions.DeadlineExceeded):
                    sessions.remaining_timeout(30)
            self.assertEqual(sessions.remaining_timeout(30), 30)

    def test_scope_is_thread_local_and_validates_only_actual_budgets(self):
        result = []
        with sessions.deadline_scope(timeout=1):
            thread = threading.Thread(target=lambda: result.append(sessions.remaining_timeout(30)))
            thread.start()
            thread.join(timeout=1)
            self.assertEqual(sessions.remaining_timeout(0), 0)
        self.assertEqual(result, [30])
        for value in (True, -1, float("nan"), float("inf"), "30"):
            with self.subTest(value=value), self.assertRaises(HarnessError):
                with sessions.deadline_scope(timeout=value):
                    pass

    def test_expired_scope_stops_before_connection_or_native_write(self):
        wire = InjectedTransport()
        with patch("oasis_harness.sessions._ProxyTransport", return_value=wire) as connect:
            with self.assertRaises(sessions.DeadlineExceeded):
                with sessions.deadline_scope(timeout=0):
                    sessions.AppServer("expired")
        connect.assert_not_called()
        client = self.connect(wire)
        self.addCleanup(client.close)
        before = len(wire.sent)
        with self.assertRaises(sessions.DeadlineExceeded):
            with sessions.deadline_scope(deadline=time.monotonic() - 1):
                client.call("turn/start", {})
        self.assertEqual(len(wire.sent), before)

    def test_initialize_and_event_wait_share_the_connection_deadline(self):
        wire = InjectedTransport()
        wire.initialize_messages = []
        started = time.monotonic()
        with self.assertRaises(sessions.DeadlineExceeded):
            with sessions.deadline_scope(timeout=0.04):
                self.connect(wire)
        self.assertLess(time.monotonic() - started, 0.3)
        self.assertTrue(wire.closed)
        self.assertEqual([row["method"] for row in wire.sent], ["initialize"])

        wire = InjectedTransport()
        with sessions.deadline_scope(timeout=0.04):
            client = self.connect(wire)
            started = time.monotonic()
            self.assertEqual(client.wait_events(30), [])
            self.assertLess(time.monotonic() - started, 0.2)
            with self.assertRaises(sessions.DeadlineExceeded):
                client.call("turn/start", {})
            client.close()

    def test_pages_do_not_renew_the_query_or_outer_budget(self):
        clock = [100]
        client = object.__new__(sessions.AppServer)
        requests = []

        def call(method, params, timeout=30):
            requests.append((method, params, timeout))
            clock[0] += 2
            return {"data": [{"id": str(len(requests))}], "nextCursor": str(len(requests))}

        client.call = call
        with patch("oasis_harness.sessions.time.monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(sessions.DeadlineExceeded):
                with sessions.deadline_scope(timeout=4):
                    list(client.pages("thread/turns/list", {}, timeout=3))
        self.assertEqual(len(requests), 2)
        self.assertEqual([row[2] for row in requests], [3, 1])
        self.assertEqual(requests[1][1], {"cursor": "1"})

    def test_handshake_drip_cannot_renew_its_deadline(self):
        clock = [0]
        wire = Mock()

        def receive(_size):
            clock[0] += 0.4
            return b"x"

        wire.recv.side_effect = receive
        with patch("oasis_harness.sessions.socket.create_connection", return_value=wire), \
                patch("oasis_harness.sessions.time.monotonic", side_effect=lambda: clock[0]):
            with self.assertRaises(sessions.DeadlineExceeded):
                sessions._LoopbackWebSocket("ws://127.0.0.1:12345", deadline=1)
        self.assertEqual(wire.recv.call_count, 3)
        wire.close.assert_called_once_with()
        self.assertLess(wire.settimeout.call_args.args[0], 0.3)

    def test_proxy_creation_timeout_releases_a_late_owned_proxy(self):
        entered, release, terminated = threading.Event(), threading.Event(), threading.Event()
        process = Mock()
        process.stdin, process.stdout, process.stderr = io.BytesIO(), io.BytesIO(), io.BytesIO()
        process.terminate.side_effect = terminated.set

        def launch(*_args, **_kwargs):
            entered.set()
            release.wait(1)
            return process

        with patch("oasis_harness.sessions.subprocess.Popen", side_effect=launch):
            started = time.monotonic()
            try:
                with self.assertRaises(sessions.DeadlineExceeded):
                    sessions._ProxyTransport("fixture", deadline=time.monotonic() + 0.03)
                self.assertTrue(entered.is_set())
                self.assertLess(time.monotonic() - started, 0.2)
            finally:
                release.set()
            self.assertTrue(terminated.wait(0.3))
        process.terminate.assert_called_once_with()
        self.assertTrue(process.stdin.closed)

    def test_expired_cleanup_drops_socket_without_a_graceful_write(self):
        transport = object.__new__(sessions._LoopbackWebSocket)
        transport.socket = Mock()
        transport.closed = transport.sent_close = False
        transport._frame = Mock()
        transport.close(deadline=time.monotonic() - 1)
        transport._frame.assert_not_called()
        transport.socket.close.assert_called_once_with()
        self.assertTrue(transport.closed)

    def test_expired_cleanup_never_adds_proxy_wait_budgets(self):
        proxy = object.__new__(sessions._ProxyTransport)
        proxy.closed = False
        proxy.write_lock, proxy.close_lock = threading.Lock(), threading.Lock()
        proxy.stderr_reader = Mock()
        proxy.process = Mock()
        proxy.process.stdin, proxy.process.stdout, proxy.process.stderr = io.BytesIO(), io.BytesIO(), io.BytesIO()
        proxy.close(deadline=time.monotonic() - 1)
        self.assertEqual(proxy.process.wait.call_args.kwargs, {"timeout": 0})
        self.assertEqual(proxy.stderr_reader.join.call_args.kwargs, {"timeout": 0})

    def test_cleanup_failure_preserves_the_original_native_rejection(self):
        for during_initialize in (False, True):
            with self.subTest(during_initialize=during_initialize):
                wire = InjectedTransport()
                rejection = {"code": -32602, "message": "A definite rejection"}
                if during_initialize:
                    wire.initialize_messages = [{"id": 1, "error": rejection}]

                def close():
                    wire.closed = True
                    wire.feed(None)
                    raise OSError("Fixture cleanup failure")

                wire.close = close
                with self.assertRaises(sessions.NativeError) as failure:
                    client = self.connect(wire)
                    wire.on_send = lambda value: wire.feed({"id": value["id"], "error": rejection})
                    with client:
                        client.call("rejected", {})
                self.assertEqual(failure.exception.code, -32602)
                self.assertTrue(any("cleanup failed: OSError" in note for note in failure.exception.__notes__))

    def test_collect_overall_budget_covers_real_rpc_wait_and_connection_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            native = NativeFixture(root)
            for name in ("oasis-camel", "oasis-cameleer"):
                path = root / f".agents/skills/{name}/SKILL.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("Fixture role instructions.\n", encoding="utf-8")
            row = workflows.assign(root, "caller", "Scoped deadline check", factory=native)
            turn = native.threads[row["camel_thread_id"]]["turns"][-1]
            turn.update(status="inProgress", items=[item for item in turn["items"] if item["type"] != "agentMessage"])
            native.threads[row["camel_thread_id"]]["status"] = {"type": "active"}
            workflows.complete(root, row["id"], "Submitted before actual terminal", factory=native)
            native.watch_supported = True
            wire = InjectedTransport()

            def respond(value):
                if "id" not in value:
                    return
                result = native.call(value["method"], value["params"])
                wire.feed({"id": value["id"], "result": result})

            wire.on_send = respond
            # Use the real AppServer reader, request deadlines and close path;
            # only the native storage and wire are in-memory fixtures.
            with patch.dict(os.environ, {}, clear=True), \
                    patch("oasis_harness.sessions.shutil.which", return_value="fixture-codex"), \
                    patch("oasis_harness.sessions._ProxyTransport", return_value=wire):
                started = time.monotonic()
                direct = lambda originator: sessions.AppServer(originator, notification_profile="command")
                result = workflows.collect(root, row["id"], timeout=1.15, wait_timeout=30, factory=direct)
                self.assertLess(time.monotonic() - started, 1.45)
                self.assertEqual(result["phase"], "awaiting_terminal")
            self.assertTrue(wire.closed)
            methods = [value.get("method") for value in wire.sent]
            self.assertIn("fs/watch", methods)
            self.assertNotIn("thread/archive", methods)
            self.assertIn("fs/unwatch", methods)
            self.assertFalse(native.threads[row["camel_thread_id"]]["archived"])


if __name__ == "__main__":
    unittest.main()
