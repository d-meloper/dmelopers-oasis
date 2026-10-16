"""Latest installed payload over real IPC/native sockets; never invokes a model."""
from __future__ import annotations

import base64
from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from oasis_harness import installation, sessions
from oasis_harness.common import HarnessError, clean_environment, digest, read_json
from tests.test_session_transport import LoopbackServer, exact, server_frame
from tests.test_sessions import NativeFixture

PACKAGE = Path(__file__).resolve().parents[1]


class WorkflowWire(LoopbackServer):
    """Native store behind independent RFC 6455 connections, with wire counts."""
    def __init__(self, root):
        self.native = NativeFixture(root)
        self.native.watch_supported = True
        self.native.on_turn = self._turn
        self.records, self.peers = [], []
        self.native_lock = threading.RLock()
        self.response_bytes = self.event_bytes = 0
        super().__init__()

    @staticmethod
    def _turn(row, turn):
        if row["id"] != "caller":
            row["status"] = {"type": "active"}
            turn["status"] = "inProgress"
            turn["items"] = [item for item in turn["items"] if item["type"] != "agentMessage"]

    def _send(self, peer, value, *, response=False):
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        with peer["writer"]:
            peer["connection"].sendall(server_frame(payload))
        with self.native_lock:
            if response:
                self.response_bytes += len(payload)
            else:
                self.event_bytes += len(payload)

    def _connection(self, connection):
        peer = {"connection": connection, "writer": threading.Lock(),
                "originator": None, "threads": set(), "watches": {}}
        try:
            request = bytearray()
            while not request.endswith(b"\r\n\r\n"):
                request.extend(exact(connection, 1))
            fields = dict(line.split(": ", 1) for line in request.decode("ascii").split("\r\n")[1:] if line)
            key = fields["Sec-WebSocket-Key"]
            accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()).decode("ascii")
            connection.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                                "Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept + "\r\n\r\n").encode("ascii"))
            connection.settimeout(None)
            with self.native_lock:
                self.peers.append(peer)
            while not self.stop.is_set():
                first, second = exact(connection, 2)
                if not first & 0x80 or not second & 0x80:
                    raise AssertionError("Fixture expects a complete masked client frame")
                opcode, length = first & 15, second & 127
                if length == 126:
                    length = struct.unpack("!H", exact(connection, 2))[0]
                elif length == 127:
                    length = struct.unpack("!Q", exact(connection, 8))[0]
                mask = exact(connection, 4)
                encoded = exact(connection, length)
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(encoded))
                if opcode == 8:
                    with peer["writer"]:
                        connection.sendall(server_frame(payload, 8))
                    return
                if opcode == 10:
                    continue
                value = json.loads(payload)
                if "id" not in value:
                    continue
                method, params = value["method"], value.get("params", {})
                with self.native_lock:
                    if method == "initialize":
                        peer["originator"] = params["clientInfo"]["name"]
                    self.records.append({"method": method, "originator": peer["originator"],
                                         "thread_id": params.get("threadId"), "time": time.monotonic()})
                    try:
                        if method == "initialize":
                            result = {}
                        elif method in ("project/list", "permissionProfile/list", "thread/list"):
                            result = {"data": list(self.native.pages(method, params)), "nextCursor": None}
                        elif method == "fs/watch":
                            peer["watches"][params["watchId"]] = params["path"]
                            result = {"path": params["path"]}
                        elif method == "fs/unwatch":
                            peer["watches"].pop(params["watchId"], None)
                            result = {}
                        else:
                            self.native.originator = peer["originator"]
                            result = self.native.call(method, params)
                            if method in ("thread/start", "thread/resume"):
                                peer["threads"].add(result["thread"]["id"])
                        reply = {"id": value["id"], "result": result}
                    except sessions.NativeError as exc:
                        reply = {"id": value["id"], "error": {"code": exc.code, "message": str(exc)}}
                self._send(peer, reply, response=True)
        except (EOFError, ConnectionResetError, BrokenPipeError, OSError):
            pass
        except Exception as exc:
            if not self.stop.is_set():
                self.errors.append(exc)
        finally:
            with self.native_lock:
                if peer in self.peers:
                    self.peers.remove(peer)
            connection.close()

    def emit(self, thread_id, method, params):
        with self.native_lock:
            peers = [peer for peer in self.peers if thread_id in peer["threads"]]
        for peer in peers:
            self._send(peer, {"method": method, "params": {"threadId": thread_id, **params}})

    def journal_changed(self, path):
        path = Path(path).resolve()
        with self.native_lock:
            peers = [(peer, list(peer["watches"].items())) for peer in self.peers]
        for peer, watches in peers:
            for watch_id, watched in watches:
                if path == Path(watched) or path.is_relative_to(Path(watched)):
                    self._send(peer, {"method": "fs/changed", "params": {
                        "watchId": watch_id, "changedPaths": [str(path)]}})

    def finish(self, thread_id):
        with self.native_lock:
            row = self.native.threads[thread_id]
            turn = row["turns"][-1]
            turn["status"], row["status"] = "completed", {"type": "idle"}
            turn["items"].append({"id": "actual-final", "type": "agentMessage",
                                  "phase": "final_answer", "text": "Verified fixed fixture output"})
            identity = turn["id"]
        self.emit(thread_id, "turn/completed", {"turn": {"id": identity, "status": "completed"}})
        self.emit(thread_id, "thread/status/changed", {"status": {"type": "idle"}})

    def snapshot(self):
        with self.native_lock:
            return copy.deepcopy(self.records)

    def __exit__(self, *error):
        super().__exit__(*error)
        # On an assertion failure the fake endpoint's EOF ends only this root's
        # owned observer. Wait before TemporaryDirectory removes Windows locks.
        from oasis_harness import notifications
        for path in (self.native.root / ".oasis/local/notifications").glob("*/state.json"):
            process = read_json(path).get("process", {})
            until = time.monotonic() + 5
            while process and notifications._identity(process.get("pid")) == process and time.monotonic() < until:
                time.sleep(0.02)


def _until(predicate, *, timeout=10, detail="fixture condition"):
    end = time.monotonic() + timeout
    last_sharing_error = None
    while time.monotonic() < end:
        try:
            value = predicate()
        except HarnessError as exc:
            # A separate test observer can race a Windows atomic replacement.
            # This bounded read retry is fixture-only; malformed JSON and all
            # other product errors remain failures instead of being reset.
            if os.name != "nt" or not isinstance(exc.__cause__, PermissionError):
                raise
            last_sharing_error, value = exc, None
        if value:
            return value
        time.sleep(0.02)  # Test observer only, never a native RPC or model request.
    raise AssertionError("Timed out awaiting " + detail) from last_sharing_error


def run_fixed_scenario(package=PACKAGE, *, lifetime=8, payload=None, shared_wait=False):
    """One latest-only model-free run; returns metrics without host identifiers."""
    payload = installation.package_files(package) if payload is None else payload
    with tempfile.TemporaryDirectory(prefix="oasis RPC 한글 😶 ") as tmp:
        root = Path(tmp).resolve()
        for name, data in payload.items():
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        with WorkflowWire(root) as wire:
            env = clean_environment({"OASIS_APP_SERVER_URL": wire.url})
            env.pop("CODEX_THREAD_ID", None)
            env.pop("CODEX_APP_TOOLS_PIPE_PATH", None)
            env.pop("OASIS_SESSION_BACKEND", None)
            env.pop("PYTHONPATH", None)
            worker = "import sys,json;sys.path.insert(0,sys.argv[1]);from oasis_harness import notifications;print(json.dumps(notifications.ensure_running(sys.argv[2],lifetime=float(sys.argv[3]))))"
            start = time.monotonic()
            result = subprocess.run([sys.executable, "-B", "-X", "utf8", "-c", worker,
                                     str(root / ".oasis/runtime"), str(root), str(lifetime)],
                                    env=env, cwd=root, capture_output=True, timeout=10)
            if result.returncode:
                raise AssertionError(result.stderr.decode("utf-8", "replace"))
            owner = json.loads(result.stdout)
            states = root / ".oasis/local/notifications"
            state_path = next(states.glob("*/state.json"))

            def command(*arguments):
                completed = subprocess.run([sys.executable, "-B", "-X", "utf8", str(root / "tools/oasis.py"),
                                            "workflow", *arguments, "--target", str(root)],
                                           env=env, cwd=root, capture_output=True, timeout=15)
                if completed.returncode:
                    raise AssertionError(completed.stderr.decode("utf-8", "replace"))
                return json.loads(completed.stdout)

            _until(lambda: read_json(state_path).get("status") == "running", detail="installed observer startup")
            assigned = command("assign", "--cameleer-id", "caller", "--goal", "Produce the fixed output", "--request-id", "fixed")
            child = assigned["camel_thread_id"]
            aliases = []
            if shared_wait:
                for index in range(2):
                    aliases.append(command("dependency-wait", "--producer-id", child, "--consumer-id", "caller",
                        "--condition", "whole assigned output", "--request-id", "whole-" + str(index)))
            submitted = command("complete", "--task-id", assigned["id"], "--result", "fixed-result", "--checks", "fixed-check")
            if submitted["phase"] != "awaiting_terminal" or wire.native.sent != 1:
                raise AssertionError("Early submission woke its manager")
            journal = root / ".oasis/local/tasks/state.json"
            wire.journal_changed(journal)
            # Let actual change/registration reconciliation finish before counting progress.
            settled, previous = time.monotonic(), len(wire.snapshot())
            settle_deadline = time.monotonic() + 3
            while time.monotonic() < settle_deadline:
                time.sleep(0.02)
                current = len(wire.snapshot())
                if current != previous:
                    settled, previous = time.monotonic(), current
                if time.monotonic() - settled >= 0.4:
                    break
            before = wire.snapshot()
            turn_id = wire.native.threads[child]["turns"][-1]["id"]
            for index in range(1000):
                wire.emit(child, "item/completed", {"turnId": turn_id, "item": {
                    "id": "progress-" + str(index), "type": "commandExecution", "status": "completed"}})
                time.sleep(0.001)
            time.sleep(0.35)
            after_progress = wire.snapshot()
            extra_reads = sum(record["method"] in ("thread/read", "thread/turns/list", "thread/items/list")
                              for record in after_progress[len(before):])
            quiet_before = len(after_progress)
            time.sleep(0.15)
            quiet_rpc = len(wire.snapshot()) - quiet_before
            finished_at = time.monotonic()
            wire.finish(child)

            def accepted():
                row = read_json(journal)["tasks"][0]
                return row if row.get("completion", {}).get("delivery", {}).get("state") == "accepted" else None

            ready = _until(accepted, timeout=5, detail="one terminal-ready manager notice")
            latency = time.monotonic() - finished_at
            boundary = wire.snapshot()
            wire.finish(child)  # Deliberate duplicate event; no new wake-up.
            time.sleep(0.4)
            after_duplicate = wire.snapshot()
            if wire.native.sent != 2:
                raise AssertionError("Terminal notification was missing or duplicated")
            if ready["native_turn"]["state"] != "ready":
                raise AssertionError("Notice lacked terminal readiness")
            duplicate_finish_rpc = 0
            if shared_wait:
                collected = command("collect", "--task-id", assigned["id"])
                if collected["phase"] != "archived":
                    raise AssertionError("Installed collection did not archive the assigned chat")
                before_finish = len(wire.snapshot())
                for alias in aliases:
                    resolved = command("dependency-finish", "--dependency-id", alias["id"])
                    if resolved.get("end_turn") or resolved.get("subscription") != "assignment":
                        raise AssertionError("Whole-assignment alias requires another closing operation")
                duplicate_finish_rpc = len(wire.snapshot()) - before_finish
                if wire.native.sent != 2:
                    raise AssertionError("Archived whole assignment woke its manager again")
            current = read_json(state_path)
            same_owner = current["process"] == owner["process"]
            _until(lambda: read_json(state_path).get("status") not in ("starting", "running"),
                   timeout=lifetime + 3, detail="own shortened fixture lease cleanup")
            final = read_json(state_path)
            process = owner["process"]
            # Reuse the real process-identity helper; no native query is involved.
            from oasis_harness import notifications
            _until(lambda: notifications._identity(process["pid"]) != process,
                   timeout=3, detail="actual owned child process exit")
            records = wire.snapshot()
            calls = Counter(record["method"] for record in records)
            initializations = Counter(record["originator"] for record in records if record["method"] == "initialize")
            result = {
                "payload_sha256": digest({name: digest(data) for name, data in payload.items()}),
                "runtime_sha256": {name: digest(payload[".oasis/runtime/oasis_harness/" + name])
                                   for name in ("sessions.py", "shared_runtime.py", "notifications.py", "workflows.py")},
                "fixture_sha256": digest(Path(__file__).read_bytes()),
                "native_rpc": len(records), "native_rpc_through_notice": len(boundary),
                "duplicate_event_native_rpc": len(after_duplicate) - len(boundary),
                "native_rpc_before_cleanup": len(after_duplicate),
                "cleanup_native_rpc": len(records) - len(after_duplicate), "native_rpc_by_method": dict(calls),
                "cleanup_native_rpc_by_method": dict(Counter(record["method"] for record in records[len(after_duplicate):])),
                "response_bytes": wire.response_bytes, "event_bytes": wire.event_bytes,
                "connection_count": len(wire.connections), "initializations_per_originator": list(initializations.values()),
                "creation_originator_initializations": [count for originator, count in initializations.items()
                                                          if originator.startswith("oasis_session_")],
                "progress_events": 1000, "progress_history_reads": extra_reads, "quiet_native_rpc": quiet_rpc,
                "model_calls": 0, "fixture_turn_starts": wire.native.sent,
                "notice_count": wire.native.sent - 1, "manager_early_notice": False,
                "terminal_notice_delay_seconds": round(latency, 6),
                "elapsed_seconds_including_cleanup": round(time.monotonic() - start, 6),
                "shortened_fixture_lease_seconds": lifetime, "owner_survived_creator_exit": same_owner,
                "owner_child_exited": True, "owner_status": final["status"],
                "owner_error": final.get("error"),
                "runtime_diagnostics": final.get("runtime", final.get("diagnostics", {})),
                "separate_experiment_native_rpc": 0,
                "duplicate_finish_native_rpc": duplicate_finish_rpc,
            }
            if wire.errors:
                raise AssertionError(wire.errors)
            return result


class FixedRpcContracts(unittest.TestCase):
    metrics = []

    def test_installed_full_assignment_aliases_do_not_add_a_third_turn(self):
        result = run_fixed_scenario(shared_wait=True, lifetime=12)
        self.assertEqual(result["fixture_turn_starts"], 2)
        self.assertEqual(result["notice_count"], 1)
        self.assertEqual(result["duplicate_finish_native_rpc"], 0)

    def test_installed_latest_fixed_assignment_three_runs(self):
        self.__class__.metrics = []
        payload = installation.package_files(PACKAGE)
        for run in range(3):
            with self.subTest(run=run + 1):
                metrics = run_fixed_scenario(payload=payload)
                self.__class__.metrics.append(metrics)
                self.assertLessEqual(metrics["native_rpc"], 35, metrics)
                self.assertEqual(metrics["progress_history_reads"], 0, metrics)
                self.assertEqual(metrics["quiet_native_rpc"], 0, metrics)
                self.assertEqual(metrics["creation_originator_initializations"], [1], metrics)
                self.assertEqual(metrics["connection_count"], 2, metrics)
                self.assertTrue(all(count == 1 for count in metrics["initializations_per_originator"]), metrics)
                self.assertEqual(metrics["notice_count"], 1, metrics)
                self.assertTrue(metrics["owner_survived_creator_exit"] and metrics["owner_child_exited"])
                self.assertEqual(metrics["owner_status"], "expired", metrics)
                self.assertGreater(metrics["runtime_diagnostics"]["ipc_requests"], 0, metrics)
        self.assertEqual(len({metric["payload_sha256"] for metric in self.metrics}), 1)
        # The committed full-suite log retains exact consumed code and counters;
        # no extra product command or evidence file is required.
        print("OASIS_FIXED_RPC=" + json.dumps({
            "payload_sha256": self.metrics[0]["payload_sha256"],
            "runtime_sha256": self.metrics[0]["runtime_sha256"],
            "fixture_sha256": self.metrics[0]["fixture_sha256"],
            "native_rpc": [metric["native_rpc"] for metric in self.metrics],
            "ipc_requests": [metric["runtime_diagnostics"]["ipc_requests"] for metric in self.metrics],
            "progress_history_reads": [metric["progress_history_reads"] for metric in self.metrics],
            "cleanup_native_rpc": [metric["cleanup_native_rpc"] for metric in self.metrics],
            "terminal_notice_delay_seconds": [metric["terminal_notice_delay_seconds"] for metric in self.metrics],
            "owner_status": [metric["owner_status"] for metric in self.metrics],
            "shortened_fixture_lease_seconds": self.metrics[0]["shortened_fixture_lease_seconds"],
            "model_free": True, "latest_only": True,
        }, sort_keys=True), flush=True)


if __name__ == "__main__":
    unittest.main()
