"""Desktop tool/rollout fixtures and local Windows events; no native model turns."""
import copy
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest import mock

from oasis_harness import desktop_sessions as desktop, sessions
from oasis_harness.desktop_tools import DesktopNotSent
from oasis_harness.common import HarnessError
from tests import FIXTURE_ROOT


SOURCE = "00000000-0000-4000-8000-000000000001"
CHILD = "00000000-0000-4000-8000-000000000002"
SOURCE_TURN = "00000000-0000-4000-8000-000000000011"
CHILD_TURN = "00000000-0000-4000-8000-000000000012"
SAVED = {"active_permission_profile": {"id": ":danger-full-access"},
         "permission_profile": {"type": "disabled"}, "approval_policy": "never",
         "approvals_reviewer": "user", "model": "fixture-model", "reasoning_effort": "high"}
LOCAL = FIXTURE_ROOT / "desktop-sessions"


def delegation(source, text):
    escape = lambda value: value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return ("<codex_delegation>\n  <source_thread_id>" + escape(source) + "</source_thread_id>\n"
            "  <input>" + escape(text) + "</input>\n</codex_delegation>")


class Tools:
    def __init__(self, home, root):
        self.home, self.root = home, root
        self.calls, self.rows = [], {}
        self.child_settings = copy.deepcopy(SAVED)
        self.after_create = None
        self.host = "local"
        self.source_root = root
        self.add(SOURCE, SOURCE_TURN)

    def add(self, identity, turn_id, *, prompt=None, source=SOURCE, saved=None):
        path = self.home / "sessions/2026/10/16" / ("rollout-2026-10-16T00-00-00-" + identity + ".jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        records = [{"type": "session_meta", "payload": {"id": identity, "cwd": str(self.root)}},
                   {"type": "turn_context", "payload": {**(saved or SAVED), "turn_id": turn_id}}]
        path.write_text("".join(json.dumps(row) + "\n" for row in records), encoding="utf-8")
        items = [] if prompt is None else [{"type": "functionCallOutput", "id": "input-" + turn_id,
                                          "namespace": "codex_app", "output": delegation(source, prompt)}]
        self.rows[identity] = {"native": {"id": identity, "kind": "codex", "hostId": "local",
                             "cwd": str(self.root), "title": "fixture", "status": {"type": "idle"}},
                             "turns": [{"id": turn_id, "status": "completed", "items": items}], "path": path}
        return self.rows[identity]

    def call(self, name, args, **kwargs):
        self.calls.append((name, copy.deepcopy(args), kwargs))
        if name == "list_projects":
            return {"schemaVersion": 2, "projects": [{"projectId": "fixture-project", "projectKind": "local",
                    "path": str(self.root), "hostId": "local", "isGitRepository": False}]}
        if name == "read_thread":
            row = self.rows[args["threadId"]]
            native = copy.deepcopy(row["native"])
            if args["threadId"] == SOURCE:
                native["cwd"] = str(self.source_root)
            data = list(reversed(row["turns"]))
            if args.get("cursor"):
                index = next(index for index, turn in enumerate(data) if turn["id"] == args["cursor"])
                data = data[index + 1:]
            selected = data[:args["turnLimit"]]
            more = len(data) > len(selected)
            return {"schemaVersion": 1, "thread": native, "turns": copy.deepcopy(selected),
                    "page": {"order": "newest_first", "hasMore": more,
                             "nextCursor": selected[-1]["id"] if more else None}}
        if name == "create_thread":
            self.add(CHILD, CHILD_TURN, prompt=args["prompt"], saved=self.child_settings)
            if self.after_create:
                self.after_create()
            return {"threadId": CHILD, "hostId": self.host}
        if name == "send_message_to_thread":
            row = self.rows[args["threadId"]]
            identity = "00000000-0000-4000-8000-000000000099"
            row["turns"].append({"id": identity, "status": "inProgress", "items": [
                {"id": "input-" + identity, "type": "userMessage", "content": [
                    {"type": "text", "text": delegation(SOURCE, args["prompt"])}]}]})
            return {"threadId": args["threadId"]}
        if name in ("set_thread_archived", "set_thread_title"):
            return {"threadId": args["threadId"]}
        raise AssertionError(name)


class Watch:
    def __init__(self, directory, changed, failed):
        self.directory, self.changed, self.failed, self.closed = directory, changed, failed, False

    def close(self):
        self.closed = True


class DesktopContracts(unittest.TestCase):
    def setUp(self):
        LOCAL.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=LOCAL)
        self.base = Path(self.temporary.name)
        self.root, self.home = self.base / "project", self.base / "codex"
        self.root.mkdir()
        self.tools = Tools(self.home, self.root)
        self.environment = mock.patch.dict(os.environ, {"CODEX_THREAD_ID": SOURCE,
            "CODEX_APP_TOOLS_PIPE_PATH": r"\\.\pipe\fixture", "CODEX_HOME": str(self.home)}, clear=False)
        self.environment.start()
        self.server = desktop.DesktopServer("fixture", tools=self.tools, watcher_factory=Watch)

    def tearDown(self):
        self.server.close()
        self.environment.stop()
        self.temporary.cleanup()

    def create(self, **kwargs):
        project, settings, _ = self.server.prepare_assignment(SOURCE, self.root)
        return self.server.create_assignment(SOURCE, self.root, "camel_A_fixture", "Do <work> & check", settings,
                                             project, "stable-call-id", **kwargs)

    def test_create_is_one_desktop_effect_with_exact_settings_and_input_readback(self):
        created = []
        result = self.create(on_created=created.append)
        self.assertEqual(created, [CHILD])
        self.assertEqual((result["thread_id"], result["turn_id"]), (CHILD, CHILD_TURN))
        calls = [call for call in self.tools.calls if call[0] == "create_thread"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1]["target"], {"type": "project", "projectId": "fixture-project", "environment": {"type": "local"}})
        self.assertEqual((calls[0][1]["model"], calls[0][1]["thinking"]), ("fixture-model", "high"))
        self.assertEqual(calls[0][2]["call_id"], "stable-call-id")
        self.assertTrue(result["creation_verified"])
        self.assertTrue(all(call[0] not in ("thread/start", "thread/resume") for call in self.tools.calls))

    def test_readback_failure_retains_acknowledged_id_and_recovery_never_replays(self):
        created = []
        self.tools.child_settings["reasoning_effort"] = "low"
        with self.assertRaisesRegex(HarnessError, "actual saved selections differ"):
            self.create(on_created=created.append)
        self.assertEqual(created, [CHILD])
        project, settings, _ = self.server.prepare_assignment(SOURCE, self.root)
        with self.assertRaises(HarnessError):
            self.server.recover_assignment(CHILD, SOURCE, self.root, "Do <work> & check", settings, project)
        self.assertEqual(len([call for call in self.tools.calls if call[0] == "create_thread"]), 1)

    def test_known_id_precedes_a_failed_native_readback(self):
        created = []
        self.tools.after_create = lambda: self.tools.rows.pop(CHILD)
        with self.assertRaises(KeyError):
            self.create(on_created=created.append)
        self.assertEqual(created, [CHILD])

    def test_create_rechecks_are_known_not_sent_and_long_escaped_prompt_never_mutates(self):
        project, settings, _ = self.server.prepare_assignment(SOURCE, self.root)
        self.tools.source_root = self.base / "different-root"
        with self.assertRaises(DesktopNotSent):
            self.server.create_assignment(SOURCE, self.root, "camel", "request", settings, project, "call")
        self.tools.source_root = self.root
        for prompt in ("&" * 5000, "🙂" * 10000, "invalid\x01input"):
            with self.assertRaises(DesktopNotSent):
                self.server.create_assignment(SOURCE, self.root, "camel", prompt, settings, project, "call")
        self.assertFalse(any(call[0] == "create_thread" for call in self.tools.calls))

    def test_archive_state_follows_exact_native_rollout_location_and_refreshes_duplicates(self):
        self.assertFalse(self.server.archive_state(SOURCE))
        path = self.tools.rows[SOURCE]["path"]
        archived = self.home / "archived_sessions" / path.name
        archived.parent.mkdir()
        path.rename(archived)
        self.assertTrue(self.server.archive_state(SOURCE))
        path.write_text(archived.read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaisesRegex(HarnessError, "exactly one"):
            self.server.archive_state(SOURCE)

    def state_database(self, name="state_5.sqlite"):
        path = self.home / name
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT NOT NULL)")
            connection.execute("CREATE TABLE thread_spawn_edges (parent_thread_id TEXT NOT NULL, child_thread_id TEXT PRIMARY KEY, status TEXT NOT NULL)")
            connection.execute("INSERT INTO threads VALUES (?,?)", (SOURCE, str(self.tools.rows[SOURCE]["path"])))
        return path

    def test_archive_descendants_are_complete_readonly_and_include_unknown_materialization(self):
        path = self.state_database()
        grandchild = "00000000-0000-4000-8000-000000000003"
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.executemany("INSERT INTO thread_spawn_edges VALUES (?,?,?)", [
                (SOURCE, CHILD, "open"), (CHILD, grandchild, "closed")])
        before = path.read_bytes()
        self.assertEqual(self.server.archive_descendants(SOURCE), {CHILD, grandchild})
        self.assertEqual(path.read_bytes(), before)

    def test_archive_inventory_rejects_missing_ambiguous_changed_owner_schema_and_cycles(self):
        with self.assertRaisesRegex(HarnessError, "inventory"):
            self.server.archive_descendants(SOURCE)
        path = self.state_database()
        self.assertEqual(self.server.archive_descendants(SOURCE), set())
        duplicate = self.state_database("state_6.sqlite")
        with self.assertRaisesRegex(HarnessError, "unambiguous"):
            self.server.archive_descendants(SOURCE)
        duplicate.unlink()
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("UPDATE threads SET rollout_path='other-rollout'")
        with self.assertRaisesRegex(HarnessError, "disagree"):
            self.server.archive_descendants(SOURCE)
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("UPDATE threads SET rollout_path=?", (str(self.tools.rows[SOURCE]["path"]),))
            connection.execute("INSERT INTO thread_spawn_edges VALUES (?,?,?)", (SOURCE, SOURCE, "open"))
        with self.assertRaisesRegex(HarnessError, "cycle"):
            self.server.archive_descendants(SOURCE)
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("DROP TABLE thread_spawn_edges")
        with self.assertRaisesRegex(HarnessError, "schema"):
            self.server.archive_descendants(SOURCE)

    def test_different_source_root_or_custom_permission_blocks_before_mutation(self):
        self.tools.source_root = self.base / "other"
        with self.assertRaisesRegex(HarnessError, "root disagree"):
            self.create()
        self.tools.source_root = self.root
        saved = {**SAVED, "active_permission_profile": {"id": "custom-profile"},
                 "permission_profile": None, "sandbox_policy": {"type": "read-only"}}
        self.tools.add(SOURCE, SOURCE_TURN, saved=saved)
        with self.assertRaisesRegex(HarnessError, "custom permission inheritance"):
            self.create()
        self.assertFalse(any(call[0] == "create_thread" for call in self.tools.calls))

    def test_wrong_caller_and_missing_actual_effort_block_before_create(self):
        with self.assertRaisesRegex(HarnessError, "actual inherited caller"):
            self.server.prepare_assignment(CHILD, self.root)
        saved = {**SAVED, "reasoning_effort": None}
        self.tools.add(SOURCE, SOURCE_TURN, saved=saved)
        with self.assertRaisesRegex(HarnessError, "reasoning effort"):
            self.create()
        self.assertFalse(any(call[0] == "create_thread" for call in self.tools.calls))

    def test_native_read_uses_actual_status_and_rollout_identity(self):
        self.tools.rows[SOURCE]["native"]["status"] = {"type": "active"}
        native = self.server.call("thread/read", {"threadId": SOURCE, "includeTurns": False})["thread"]
        self.assertEqual(native["status"], {"type": "active"})
        self.assertEqual(native["projectId"], "fixture-project")
        self.assertEqual(native["path"], str(self.tools.rows[SOURCE]["path"]))
        self.assertEqual(native["latestTurn"]["id"], SOURCE_TURN)
        self.assertEqual(native["turnsView"], "notLoaded")

    def test_exact_rollout_rejects_wrong_identity_ambiguity_and_symlink(self):
        path = self.tools.rows[SOURCE]["path"]
        bad = path.read_text(encoding="utf-8").replace(SOURCE, CHILD)
        path.write_text(bad, encoding="utf-8")
        with self.assertRaisesRegex(HarnessError, "metadata does not match"):
            self.server.rollouts.metadata(SOURCE)
        self.tools.add(SOURCE, SOURCE_TURN)
        duplicate = self.home / "archived_sessions" / path.name
        duplicate.parent.mkdir()
        duplicate.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaisesRegex(HarnessError, "exactly one"):
            desktop.Rollouts(self.home).metadata(SOURCE)
        duplicate.unlink()
        try:
            duplicate.symlink_to(path)
        except OSError:
            return
        with self.assertRaisesRegex(HarnessError, "linked or reparse"):
            desktop.Rollouts(self.home).metadata(SOURCE)

    def test_lookup_has_an_explicit_inventory_bound(self):
        reader = desktop.Rollouts(self.home)
        reader.MAX_ENTRIES = 1
        with self.assertRaisesRegex(HarnessError, "bounded lookup"):
            reader.find(SOURCE)

    def test_delegation_normalization_is_strict_and_keeps_actual_item_identity(self):
        item = {"type": "functionCallOutput", "namespace": "codex_app", "id": "native-item", "output": delegation(SOURCE, "<work> & check")}
        normalized = desktop.DesktopServer._item(item)
        self.assertEqual(normalized["id"], "native-item")
        self.assertEqual(normalized["nativeType"], "functionCallOutput")
        self.assertEqual(sessions._message_text(normalized), "<work> & check")
        windows = {**item, "output": delegation(SOURCE, "line1\r\nline2")}
        self.assertEqual(sessions._message_text(desktop.DesktopServer._item(windows)), "line1\r\nline2")
        for altered in ({**item, "namespace": "other"}, {**item, "name": "unknown"},
                        {**item, "output": item["output"] + "[truncated]"},
                        {**item, "output": item["output"].replace(SOURCE, "fake")},
                        {**item, "output": item["output"].replace("<input>", "<input extra='true'>")}):
            self.assertEqual(desktop.DesktopServer._item(altered)["type"], "functionCallOutput")

    def test_history_anchor_includes_new_items_in_its_existing_turn(self):
        self.create()
        value = {"thread_id": CHILD, "message_id": "client-message", "text": "Follow-up"}
        sessions._capture_anchor(self.server, value)
        self.tools.rows[CHILD]["turns"][0]["items"].append({"type": "userMessage", "id": "actual-new-input",
            "content": [{"type": "text", "text": delegation(SOURCE, "Follow-up")}]})
        self.assertTrue(sessions.reconcile_delivery(self.server, value))
        self.assertEqual(value["turn_id"], CHILD_TURN)

    def test_delivery_recovery_requires_retained_delegation_source(self):
        self.create()
        value = {"thread_id": CHILD, "message_id": "client-message", "text": "Follow-up", "desktop_source_id": SOURCE}
        sessions._capture_anchor(self.server, value)
        items = self.tools.rows[CHILD]["turns"][0]["items"]
        items.append({"type": "userMessage", "id": "other-source-input", "content": [
            {"type": "text", "text": delegation(CHILD, "Follow-up")} ]})
        self.assertFalse(sessions.reconcile_delivery(self.server, value))
        items.append({"type": "userMessage", "id": "actual-source-input", "content": [
            {"type": "text", "text": delegation(SOURCE, "Follow-up")} ]})
        self.assertTrue(sessions.reconcile_delivery(self.server, value))

    def test_paginated_history_orders_and_retains_actual_turns(self):
        turns = [{"id": f"00000000-0000-4000-8000-{index:012d}", "status": "completed", "items": []} for index in range(1, 26)]
        self.tools.rows[SOURCE]["turns"] = turns
        actual = sessions.read_turns(self.server, SOURCE)
        self.assertEqual([turn["id"] for turn in actual], [turn["id"] for turn in turns])
        first = self.server.call("thread/turns/list", {"threadId": SOURCE, "sortDirection": "desc", "limit": 1})
        self.assertEqual(first["data"][0]["id"], turns[-1]["id"])
        self.assertEqual(first["backwardsCursor"], "desktop-anchor:" + turns[-1]["id"])

    def test_paginated_item_history_uses_serializable_cursors_and_actual_ids(self):
        self.tools.rows[SOURCE]["turns"][0]["items"] = [
            {"type": "agentMessage", "id": f"actual-item-{index}", "phase": "commentary", "text": str(index)}
            for index in range(205)]
        items = [item for page in sessions._history_pages(self.server, "thread/items/list", {
            "threadId": SOURCE, "turnId": SOURCE_TURN, "sortDirection": "asc", "limit": 100})
                 for item in page["data"]]
        self.assertEqual([item["item"]["id"] for item in items], [f"actual-item-{index}" for index in range(205)])

    def test_send_verifies_exact_new_turn_and_preserves_existing_settings(self):
        self.create()
        value = self.server.call("turn/start", {"threadId": CHILD,
            "input": [{"type": "text", "text": "Follow-up"}], "clientUserMessageId": "stable-message"})
        self.assertEqual(value["turn"]["id"], "00000000-0000-4000-8000-000000000099")
        call = next(call for call in self.tools.calls if call[0] == "send_message_to_thread")
        self.assertNotIn("model", call[1])
        self.assertNotIn("thinking", call[1])
        self.assertEqual(call[2]["call_id"], "stable-message")

    def test_mode_changes_and_active_recipient_never_start_wrong_turn(self):
        self.create()
        for mode in ({"mode": "plan"}, {"mode": "default"}):
            with self.assertRaises(sessions.NativeError) as raised:
                self.server.call("turn/start", {"threadId": CHILD, "input": [{"type": "text", "text": "work"}], "collaborationMode": mode})
            self.assertEqual(raised.exception.code, -32601)
        self.tools.rows[CHILD]["native"]["status"] = {"type": "active"}
        with self.assertRaises(sessions.NativeError):
            self.server.call("turn/start", {"threadId": CHILD, "input": [{"type": "text", "text": "work"}]})
        self.assertFalse(any(call[0] == "send_message_to_thread" for call in self.tools.calls))
        for method in ("thread/resume", "thread/start", "collaborationMode/list", "thread/settings/update", "thread/list"):
            with self.assertRaises(sessions.NativeError) as raised:
                self.server.call(method, {})
            self.assertEqual(raised.exception.code, -32601)

    def test_watch_consolidates_directory_filters_files_and_never_queries_idle(self):
        directory = self.root / ".oasis/local/tasks"
        directory.mkdir(parents=True)
        path = directory / "state.json"
        self.server.call("fs/watch", {"watchId": "file", "path": str(path)})
        self.server.call("fs/watch", {"watchId": "directory", "path": str(directory)})
        self.assertEqual(len(self.server.directories), 1)
        watcher = next(iter(self.server.directories.values()))
        before = len(self.tools.calls)
        watcher.changed(["other.json"])
        events = self.server.wait_events(0)
        self.assertEqual([event["params"]["watchId"] for event in events], ["directory"])
        watcher.changed(["state.json"])
        self.assertEqual({event["params"]["watchId"] for event in self.server.wait_events(0)}, {"file", "directory"})
        self.assertEqual(self.server.wait_events(.005), [])
        self.assertEqual(len(self.tools.calls), before)
        self.server.call("fs/unwatch", {"watchId": "file"})
        self.assertFalse(watcher.closed)
        self.server.call("fs/unwatch", {"watchId": "directory"})
        self.assertTrue(watcher.closed)

    def test_watch_limits_paths_and_reports_error_before_preserved_events(self):
        with self.assertRaisesRegex(HarnessError, "verified rollout"):
            self.server.call("fs/watch", {"watchId": "outside", "path": str(self.base)})
        directory = self.root / ".oasis/local/tasks"
        directory.mkdir(parents=True)
        self.server.call("fs/watch", {"watchId": "owned", "path": str(directory)})
        watcher = next(iter(self.server.directories.values()))
        watcher.changed(["state.json"])
        watcher.failed(OSError("fixture"))
        with self.assertRaisesRegex(HarnessError, "observation failed"):
            self.server.wait_events(0)
        self.assertEqual(len(self.server.drain_events()), 1)

    def test_unrelated_directory_activity_does_not_end_a_scoped_wait_early(self):
        directory = self.root / ".oasis/local/tasks"
        directory.mkdir(parents=True)
        self.server.call("fs/watch", {"watchId": "file", "path": str(directory / "state.json")})
        watcher = next(iter(self.server.directories.values()))

        def transitions():
            time.sleep(.01)
            watcher.changed(["unrelated.json"])
            time.sleep(.02)
            watcher.changed(["state.json"])

        worker = threading.Thread(target=transitions)
        worker.start()
        events = self.server.wait_events(2)
        worker.join(timeout=2)
        self.assertEqual([event["params"]["watchId"] for event in events], ["file"])

    @unittest.skipUnless(os.name == "nt", "Windows filesystem notification integration")
    def test_real_windows_append_notification_owns_and_releases_handles(self):
        directory = self.root / ".oasis/local/events"
        directory.mkdir(parents=True)
        path = directory / "state.json"
        path.write_text("{}", encoding="utf-8")
        with desktop.DesktopServer("real-fs-fixture", tools=self.tools) as server:
            server.call("fs/watch", {"watchId": "real", "path": str(path)})
            watcher = next(iter(server.directories.values()))
            before = len(self.tools.calls)
            with path.open("a", encoding="utf-8") as stream:
                stream.write("\n")
            events, deadline = [], time.monotonic() + 5
            while not events and time.monotonic() < deadline:
                events = server.wait_events(max(0, deadline - time.monotonic()))
            self.assertTrue(any(event["params"]["watchId"] == "real" for event in events))
            self.assertEqual(len(self.tools.calls), before)
            server.call("fs/unwatch", {"watchId": "real"})
            self.assertFalse(watcher.thread.is_alive())
            self.assertIsNone(watcher.handle)
            self.assertIsNone(watcher.event)
            self.assertIsNone(watcher.stop)


if __name__ == "__main__":
    unittest.main()
