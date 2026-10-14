"""Transient notification ownership and I/O fixtures; no model/server launches."""
import copy
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

from oasis_harness import notifications, sessions
from oasis_harness.common import HarnessError, read_json, write_json


class Clock:
    def __init__(self):
        self.now = 0

    def monotonic(self):
        return self.now

    def sleep(self, duration):
        self.now += duration


class EventServer:
    def __init__(self, clock):
        self.clock = clock
        self.calls = []
        self.events = []
        self.watches = {}
        self.on_watch = None
        self.failed = None
        self.watch_supported = True
        self.cleanup_failed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def call(self, method, params):
        self.calls.append((method, copy.deepcopy(params)))
        if method == "fs/watch":
            if not self.watch_supported:
                raise sessions.NativeError(method, {"code": -32601, "message": "Method not found"})
            self.watches[params["watchId"]] = params["path"]
            if self.on_watch:
                self.on_watch(params)
            return {"path": params["path"]}
        if method == "fs/unwatch":
            if self.cleanup_failed:
                raise HarnessError("Fixture cleanup denied")
            self.watches.pop(params["watchId"], None)
            return {}
        raise AssertionError(method)

    def wait_events(self, timeout):
        if self.failed:
            raise self.failed
        if self.events and self.events[0][0] <= self.clock.now + timeout:
            when, event = self.events.pop(0)
            self.clock.now = max(self.clock.now, when)
            return [event]
        self.clock.now += timeout
        return []


class NotificationContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="oasis 알림 ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.journal = self.root / ".oasis/local/tasks/state.json"
        write_json(self.journal, {"tasks": [], "dependencies": []})
        self.clock = Clock()
        self.server = EventServer(self.clock)
        self.target = {"thread_id": "worker", "turn_id": "assigned-turn", "path": str(self.root / "worker.jsonl")}

    def own_state(self, **updates):
        value = {"schema_version": 1, "target": str(self.root), "backend": notifications._backend(),
                 "token": "owned-token", "generation": 1, "status": "starting",
                 "created_at": time.time(), "expires_at": time.time() + 60,
                 "process": notifications._identity(os.getpid())}
        value.update(updates)
        write_json(notifications._directory(self.root) / "state.json", value)
        return value

    def observe(self, step, deadline=10):
        with mock.patch.object(notifications, "time", self.clock):
            return notifications._observe(self.root, self.server, deadline, step)

    def test_same_target_burst_is_coalesced_without_periodic_queries(self):
        steps = []

        def registered(params):
            if params["path"] == self.target["path"]:
                self.server.events.extend((0.01 + index * 0.001, {"method": "fs/changed", "params": {
                    "watchId": params["watchId"], "changedPaths": [self.target["path"]]}}) for index in range(100))

        def step(root, server, *, changed_threads, cache):
            steps.append((self.clock.now, changed_threads))
            return {"pending": len(steps) < 3, "targets": [self.target]}

        self.server.on_watch = registered
        self.assertEqual(self.observe(step)[0], "stopped")
        self.assertEqual(len(steps), 3)  # Initial, registration race, one burst.
        self.assertEqual(steps[-1][1], {"worker"})
        self.assertGreaterEqual(steps[-1][0] - steps[-2][0], 1)
        self.assertFalse(self.server.watches)

    def test_unrelated_and_old_turn_events_do_not_query_status(self):
        steps = []
        self.server.events = [
            (0.1, {"method": "turn/completed", "params": {"threadId": "other", "turn": {"id": "assigned-turn"}}}),
            (0.2, {"method": "turn/completed", "params": {"threadId": "worker", "turn": {"id": "previous-turn"}}}),
            (0.3, {"method": "fs/changed", "params": {"watchId": "other-watch", "changedPaths": [self.target["path"]]}}),
        ]

        def step(*args, **kwargs):
            steps.append(kwargs["changed_threads"])
            return {"pending": True, "targets": [self.target]}

        self.assertEqual(self.observe(step)[0], "expired")
        self.assertEqual(steps, [None, {"worker"}])

    def test_sustained_change_storm_respects_reconciliation_rate(self):
        steps = []

        def registered(params):
            if params["path"] == self.target["path"]:
                self.server.events.extend((0.01 + index * 0.01, {"method": "fs/changed", "params": {
                    "watchId": params["watchId"], "changedPaths": [self.target["path"]]}}) for index in range(300))

        def step(*args, **kwargs):
            steps.append(self.clock.now)
            return {"pending": True, "targets": [self.target]}

        self.server.on_watch = registered
        self.assertEqual(self.observe(step, deadline=4)[0], "expired")
        self.assertLessEqual(len(steps), 5)
        self.assertTrue(all(later - earlier >= 1 for earlier, later in zip(steps[1:], steps[2:])))

    def test_exact_terminal_and_idle_status_are_observation_triggers(self):
        watches = {}
        targets = {"worker": self.target}
        changed, journal = notifications._relevant([
            {"method": "turn/completed", "params": {"threadId": "worker", "turn": {"id": "assigned-turn"}}},
            {"method": "thread/status/changed", "params": {"threadId": "worker", "status": {"type": "idle"}}},
        ], watches, targets, self.journal)
        self.assertEqual(changed, {"worker"})
        self.assertFalse(journal)

    def test_journal_directory_events_only_rescan_exact_state_file(self):
        watches = {"journal": {"thread_id": None, "path": str(self.journal.parent)}}
        unrelated = {"method": "fs/changed", "params": {"watchId": "journal", "changedPaths": [str(self.journal.parent / "notes.txt")]}}
        expected = {"method": "fs/changed", "params": {"watchId": "journal", "changedPaths": [str(self.journal)]}}
        self.assertEqual(notifications._relevant([unrelated], watches, {}, self.journal), (set(), False))
        self.assertEqual(notifications._relevant([expected], watches, {}, self.journal), (set(), True))

    def test_normal_writer_lock_defers_to_journal_event(self):
        steps = []

        def registered(params):
            if params["path"] == str(self.journal.parent):
                self.server.events.append((0.1, {"method": "fs/changed", "params": {
                    "watchId": params["watchId"], "changedPaths": [str(self.journal)]}}))

        def step(*args, **kwargs):
            steps.append(kwargs["changed_threads"])
            if len(steps) == 1:
                raise HarnessError("Operation is already locked: fixture; inspect its owner before recovery")
            return {"pending": False, "targets": []}

        self.server.on_watch = registered
        self.assertEqual(self.observe(step)[0], "stopped")
        self.assertEqual(steps, [None, set()])

    def test_journal_registration_race_rechecks_without_thread_targets(self):
        steps = []

        def step(*args, **kwargs):
            steps.append(kwargs["changed_threads"])
            return {"pending": len(steps) == 1, "targets": []}

        self.assertEqual(self.observe(step)[0], "stopped")
        self.assertEqual(steps, [None, set()])

    def test_busy_postregistration_read_resumes_from_writer_unlock(self):
        steps = []

        def registered(params):
            if params["path"] == str(self.journal.parent.parent):
                self.server.events.append((0.1, {"method": "fs/changed", "params": {
                    "watchId": params["watchId"], "changedPaths": [str(self.journal.parent.parent / "operations.lock")]}}))

        def step(*args, **kwargs):
            steps.append(kwargs["changed_threads"])
            if len(steps) < 3:
                raise HarnessError("Operation is already locked: fixture")
            return {"pending": False, "targets": []}

        self.server.on_watch = registered
        self.assertEqual(self.observe(step)[0], "stopped")
        self.assertEqual(steps, [None, set(), set()])
        self.assertGreaterEqual(self.clock.now, notifications.DEBOUNCE)

    def test_covered_output_storm_only_reconciles_exact_terminal(self):
        self.target["event_covered"] = True
        self.server.events = [(0.001 * index, {"method": "item/completed", "params": {
            "threadId": "worker", "turnId": "assigned-turn", "item": {"type": "commandExecution", "id": str(index)}}})
            for index in range(1000)]
        self.server.events.append((1.5, {"method": "turn/completed", "params": {
            "threadId": "worker", "turn": {"id": "assigned-turn", "status": "completed"}}}))
        steps = []

        def step(*args, **kwargs):
            steps.append((self.clock.now, kwargs["changed_threads"]))
            return {"pending": len(steps) < 3, "targets": [self.target]}

        self.assertEqual(self.observe(step)[0], "stopped")
        self.assertEqual(len(steps), 3)  # Initial, journal registration, exact terminal.
        self.assertEqual(steps[-1][1], {"worker"})
        self.assertLess(steps[-1][0], notifications.MIN_QUERY_INTERVAL)
        self.assertFalse(any(method == "fs/watch" and params["path"] == self.target["path"]
                             for method, params in self.server.calls))

    def test_idle_and_progress_only_wake_recipients_actually_awaited(self):
        active = {"method": "thread/status/changed", "params": {"threadId": "worker", "status": {"type": "active"}}}
        idle = {"method": "thread/status/changed", "params": {"threadId": "worker", "status": {"type": "idle"}}}
        targets = {"worker": self.target}
        self.assertEqual(notifications._relevant([active, idle], {}, targets, self.journal), (set(), False))
        self.target["idle_only"] = True
        self.assertEqual(notifications._relevant([active, idle], {}, targets, self.journal), ({"worker"}, False))

    def test_fallback_sustained_changes_issue_at_most_one_read_per_five_seconds(self):
        steps = []

        def registered(params):
            if params["path"] == self.target["path"]:
                self.server.events.extend((0.01 + index * 0.01, {"method": "fs/changed", "params": {
                    "watchId": params["watchId"], "changedPaths": [self.target["path"]]}}) for index in range(1200))

        def step(*args, **kwargs):
            steps.append((self.clock.now, kwargs["changed_threads"]))
            return {"pending": True, "targets": [self.target]}

        self.server.on_watch = registered
        self.assertEqual(self.observe(step, deadline=13)[0], "expired")
        self.assertEqual(len(steps), 4)  # Initial, registration race, 5s and 10s fallback.
        self.assertGreaterEqual(steps[2][0] - steps[1][0], 5)
        self.assertGreaterEqual(steps[3][0] - steps[2][0], 5)

    def test_native_terminal_never_flushes_other_threads_deferred_fallback(self):
        native = {"thread_id": "native", "turn_id": "native-turn", "event_covered": True,
                  "path": str(self.root / "native.jsonl")}
        steps = []

        def registered(params):
            if params["path"] == self.target["path"]:
                self.server.events.extend([
                    (1, {"method": "fs/changed", "params": {"watchId": params["watchId"], "changedPaths": [self.target["path"]]}}),
                    (1, {"method": "turn/completed", "params": {"threadId": "native", "turn": {"id": "native-turn"}}}),
                ])

        def step(*args, **kwargs):
            steps.append((self.clock.now, kwargs["changed_threads"]))
            return {"pending": len(steps) < 4, "targets": [self.target, native]}

        self.server.on_watch = registered
        self.assertEqual(self.observe(step)[0], "stopped")
        self.assertEqual(steps[2][1], {"native"})
        self.assertLess(steps[2][0], 2)
        self.assertEqual(steps[3][1], {"worker"})
        self.assertGreaterEqual(steps[3][0], 5)

    def test_shared_owner_stays_idle_for_sixty_seconds_without_native_queries(self):
        runtime = mock.Mock()
        runtime.busy.return_value = False
        runtime.last_activity = 0
        steps = []

        def step(*args, **kwargs):
            steps.append(None)
            return {"pending": False, "targets": []}

        with mock.patch.object(notifications, "time", self.clock):
            result = notifications._observe(self.root, self.server, 100, step, runtime=runtime)
        self.assertEqual(result[0], "stopped")
        self.assertEqual(self.clock.now, 60)
        self.assertEqual(len(steps), 2)  # The second step closes journal registration.
        self.assertTrue(all(method in ("fs/watch", "fs/unwatch") for method, _ in self.server.calls))

    def test_first_command_creates_only_missing_owned_watch_directory(self):
        self.journal.unlink()
        self.journal.parent.rmdir()
        runtime = mock.Mock()
        runtime.busy.return_value = False
        runtime.last_activity = 0

        def step(*args, **kwargs):
            self.assertTrue(self.journal.parent.is_dir())
            self.assertFalse(self.journal.exists(), "The I/O owner must not synthesize/reset a task journal")
            return {"pending": False, "targets": []}

        with mock.patch.object(notifications, "time", self.clock):
            self.assertEqual(notifications._observe(self.root, self.server, 100, step, runtime=runtime)[0], "stopped")
        self.assertFalse(self.journal.exists())

    def test_completed_work_loses_targets_during_shared_idle_grace(self):
        self.target["event_covered"] = True
        self.server.events = [(0.5, {"method": "turn/completed", "params": {
            "threadId": "worker", "turn": {"id": "assigned-turn"}}})]
        runtime = mock.Mock()
        runtime.busy.return_value = False
        runtime.last_activity = 0
        steps = []

        def step(*args, **kwargs):
            steps.append(kwargs["changed_threads"])
            return {"pending": False, "targets": [self.target]}

        with mock.patch.object(notifications, "time", self.clock):
            self.assertEqual(notifications._observe(self.root, self.server, 100, step, runtime=runtime)[0], "stopped")
        self.assertEqual(steps, [None, set()])
        self.assertFalse(any(params.get("path") == self.target["path"] for _, params in self.server.calls))

    def test_own_lock_events_never_create_idle_reconciliation_loop(self):
        steps = []

        def registered(params):
            if params["path"] == str(self.journal.parent.parent):
                self.server.events.extend((0.1 + index * 0.01, {"method": "fs/changed", "params": {
                    "watchId": params["watchId"], "changedPaths": [str(self.journal.parent.parent / "operations.lock")]}}) for index in range(100))

        def step(*args, **kwargs):
            steps.append(None)
            return {"pending": True, "targets": []}

        self.server.on_watch = registered
        self.assertEqual(self.observe(step)[0], "expired")
        self.assertEqual(len(steps), 2)

    def test_stop_reconciles_work_accepted_before_shutdown_barrier(self):
        state = self.own_state()
        steps = []

        def step(*args, **kwargs):
            steps.append(None)
            if len(steps) == 1:
                write_json(self.journal, {"tasks": [{"id": "newly-accepted"}], "dependencies": []})
            return {"pending": False, "targets": []}

        result = notifications.run(self.root, state["token"], factory=lambda name: self.server, step=step)
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(len(steps), 2)
        self.assertEqual(read_json(self.journal)["tasks"], [{"id": "newly-accepted"}])

    def test_new_owner_launch_waits_for_previous_owner_shutdown(self):
        state = self.own_state()
        observed, threads = [], []
        test = self

        class ClosingServer(EventServer):
            def __exit__(self, *_):
                thread = threading.Thread(target=lambda: observed.append(notifications.ensure_running(test.root)))
                threads.append(thread)
                thread.start()
                thread.join(0.05)
                test.assertTrue(thread.is_alive(), "Startup must wait while previous observer owns shutdown")

        server = ClosingServer(self.clock)
        fake_child = mock.Mock(pid=99999999)
        with mock.patch.object(notifications.subprocess, "Popen", return_value=fake_child) as launch:
            result = notifications.run(self.root, state["token"], factory=lambda name: server,
                                       step=lambda *a, **k: {"pending": False, "targets": []})
            threads[0].join(2)
            self.assertFalse(threads[0].is_alive())
            launch.assert_called_once()
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(observed[0]["generation"], state["generation"] + 1)
        self.assertNotEqual(observed[0]["token"], state["token"])

    def test_actual_process_identity_includes_birth_and_executable(self):
        identity = notifications._identity(os.getpid())
        self.assertEqual(identity["pid"], os.getpid())
        self.assertTrue(identity["birth"])
        self.assertTrue(Path(identity["executable"]).is_absolute())

    def test_hidden_python_child_expires_before_any_native_connection(self):
        # Actual Windows process/lifetime boundary in a Unicode temp project.
        # Its lease expires before spawn, so no native factory can be entered.
        launched = notifications.ensure_running(self.root, lifetime=0.000001)
        until = time.monotonic() + 5
        while time.monotonic() < until:
            current = notifications._read(self.root)
            if current["status"] not in ("starting", "running"):
                break
            time.sleep(0.02)
        self.assertEqual(current["status"], "expired", current)
        self.assertEqual(current["token"], launched["token"])
        self.assertTrue(current["process"]["birth"])
        self.assertEqual(current["process"]["pid"], launched["process"]["pid"])
        # Only the fixture's retained journal exists; no task mutation/server.
        self.assertEqual(read_json(self.journal), {"tasks": [], "dependencies": []})

    def test_equivalent_backend_addresses_have_one_owner_namespace(self):
        with mock.patch.dict(os.environ, {"OASIS_APP_SERVER_URL": "ws://localhost:80"}):
            local = notifications._backend()
        with mock.patch.dict(os.environ, {"OASIS_APP_SERVER_URL": "ws://127.0.0.1/"}):
            self.assertEqual(notifications._backend(), local)

    def test_verified_existing_owner_is_reused_without_launch(self):
        state = self.own_state(status="running")
        with notifications._lock(notifications._directory(self.root) / "owner.lock"):
            with mock.patch.object(notifications.subprocess, "Popen") as launch:
                result = notifications.ensure_running(self.root)
        self.assertEqual(result["token"], state["token"])
        self.assertTrue(result["owner_verified"])
        launch.assert_not_called()

    def test_launch_failure_preserves_pending_project_journal(self):
        before = self.journal.read_bytes()
        with mock.patch.object(notifications.subprocess, "Popen", side_effect=OSError("fixture")):
            result = notifications.ensure_running(self.root)
        self.assertEqual(result["status"], "recovery_required")
        self.assertEqual(self.journal.read_bytes(), before)
        self.assertIn("retry", result["next_action"])

    def test_pid_reuse_does_not_establish_ownership(self):
        state = self.own_state(status="running")
        state["process"]["birth"] += "-older"
        write_json(notifications._directory(self.root) / "state.json", state)
        self.assertEqual(notifications.status(self.root)["status"], "recovery_required")
        factory = mock.Mock()
        result = notifications.run(self.root, state["token"], factory=factory, step=lambda *a, **k: None)
        self.assertEqual(result["status"], "recovery_required")
        self.assertIn("identity", result["next_action"])
        factory.assert_not_called()

    def test_superseded_process_cannot_write_new_generation(self):
        state = self.own_state(token="new-token", generation=2)
        before = read_json(notifications._directory(self.root) / "state.json")
        self.assertEqual(notifications.run(self.root, "old-token", step=lambda *a, **k: None), {"status": "superseded"})
        self.assertEqual(read_json(notifications._directory(self.root) / "state.json"), before)
        with self.assertRaisesRegex(HarnessError, "generation changed"):
            notifications._save(self.root, "old-token", status="stopped")
        self.assertEqual(notifications.status(self.root)["token"], state["token"])

    def test_unsupported_event_backend_exits_with_retained_resume_path(self):
        state = self.own_state()
        self.server.watch_supported = False
        factory = mock.Mock(return_value=self.server)
        result = notifications.run(self.root, state["token"], factory=factory,
                                   step=lambda *a, **k: {"pending": True, "targets": []})
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(factory.call_count, 1)
        self.assertIn("do not poll", result["next_action"])
        self.assertTrue(self.journal.exists())

    def test_connection_loss_reconciles_once_then_stops(self):
        state = self.own_state()
        self.server.failed = HarnessError("Fixture EOF")
        factory = mock.Mock(return_value=self.server)
        result = notifications.run(self.root, state["token"], factory=factory,
                                   step=lambda *a, **k: {"pending": True, "targets": []})
        self.assertEqual(factory.call_count, 2)
        self.assertEqual(result["status"], "recovery_required")
        self.assertEqual(result["reconnects"], 1)

    def test_cleanup_failure_preserves_resume_without_reconnecting(self):
        state = self.own_state()
        self.server.cleanup_failed = True
        factory = mock.Mock(return_value=self.server)
        calls = []

        def step(*args, **kwargs):
            calls.append(None)
            return {"pending": len(calls) < 2, "targets": [self.target]}

        result = notifications.run(self.root, state["token"], factory=factory,
                                   step=step)
        self.assertEqual(result["status"], "recovery_required")
        self.assertIn("cleanup failed", result["error"])
        factory.assert_called_once()

    def test_disconnected_unwatch_does_not_hide_one_reconnect(self):
        state = self.own_state()
        self.server.failed = HarnessError("Fixture EOF")
        self.server.cleanup_failed = True
        recovered = EventServer(self.clock)
        factory = mock.Mock(side_effect=[self.server, recovered])
        result = notifications.run(self.root, state["token"], factory=factory,
                                   step=lambda root, server, **k: {"pending": server is self.server, "targets": []})
        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["reconnects"], 1)
        self.assertEqual(result["cleanup_errors"], ["Fixture cleanup denied"])

    def test_expired_lease_starts_no_new_connection(self):
        state = self.own_state(expires_at=time.time() - 1)
        factory = mock.Mock(return_value=self.server)
        result = notifications.run(self.root, state["token"], factory=factory,
                                   step=lambda *a, **k: self.fail("Expired observer must not read task state"))
        self.assertEqual(result["status"], "expired")
        factory.assert_not_called()

    def test_native_wait_deadline_at_owner_expiry_is_normal_expiration(self):
        state = self.own_state()
        clock = mock.Mock(wraps=time)

        def expire(root, server, deadline, *args, **kwargs):
            clock.monotonic.return_value = deadline + .01
            raise sessions.DeadlineExceeded("Fixture native wait reached owner lifetime")

        factory = mock.Mock(return_value=self.server)
        with mock.patch.object(notifications, "time", clock), mock.patch.object(notifications, "_observe", side_effect=expire):
            result = notifications.run(self.root, state["token"], factory=factory)
        self.assertEqual(result["status"], "expired")
        self.assertEqual(result["reconnects"], 0)
        self.assertIn("Fixture native wait", result["error"])
        factory.assert_called_once()


if __name__ == "__main__":
    unittest.main()
