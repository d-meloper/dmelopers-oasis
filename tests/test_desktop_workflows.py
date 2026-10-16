"""Desktop dispatch journal integration; no real chats or model turns."""
import copy
from contextlib import closing
import os
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from oasis_harness import desktop_sessions, notifications, sessions, workflows
from oasis_harness.common import HarnessError, read_json, write_json
from oasis_harness.desktop_tools import DesktopNotSent, DesktopUncertain
from tests.test_sessions import NativeFixture, SAVED


class DesktopFixture(NativeFixture):
    desktop_managed = True
    source_id = "caller"

    def __init__(self, root):
        super().__init__(root)
        self.create_calls, self.recover_calls = 0, 0
        self.failure, self.verify_failure = None, False

    def prepare_assignment(self, source, target):
        if source != "caller" or Path(target) != self.root:
            raise HarnessError("wrong source/root")
        return "fixture-project", sessions.inherited_settings(SAVED), self.threads[source]

    def create_assignment(self, source, target, title, prompt, settings, project, call_id, *, on_created=None):
        self.create_calls += 1
        if self.failure:
            raise self.failure
        identity = "desktop-child"
        row = self.add(identity, name=title)
        row["turns"] = [{"id": "desktop-first", "status": "inProgress", "items": [
            {"id": "actual-input", "type": "userMessage", "sourceThreadId": source,
             "content": [{"type": "text", "text": prompt}]}]}]
        row["status"] = {"type": "active"}
        on_created(identity)
        return self.recover_assignment(identity, source, target, prompt, settings, project)

    def recover_assignment(self, identity, source, target, prompt, settings, project):
        self.recover_calls += 1
        if self.verify_failure:
            raise HarnessError("readback unavailable")
        row = self.threads[identity]
        if row["turns"][0]["items"][0]["content"][0]["text"] != prompt:
            raise HarnessError("wrong accepted input")
        return {"thread_id": identity, "turn_id": row["turns"][0]["id"], "native_thread": copy.deepcopy(row)}


class DesktopWorkflows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.native = DesktopFixture(self.root)
        for name, value in (("available", lambda: True), ("DesktopServer", self.native)):
            self.enterContext(patch.object(desktop_sessions, name, value))
        self.enterContext(patch.object(notifications, "ensure_running", return_value={"state": "fixture"}))
        self.enterContext(patch.object(notifications, "status", return_value={"state": "fixture"}))
        skill = self.root / ".agents/skills/oasis-camel/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("Fixture role", encoding="utf-8")

    def assign(self, **kwargs):
        return workflows.assign(self.root, "caller", "Implement parser", request_id="one", **kwargs)

    def test_one_create_already_contains_goal_context_and_actual_task_ids(self):
        row = self.assign(context="Scope: parser only")
        self.assertEqual(row["phase"], "assigned")
        self.assertEqual(row["native_backend"], "desktop")
        self.assertEqual(self.native.create_calls, 1)
        self.assertEqual(self.native.started, 0)
        self.assertEqual(self.native.sent, 0)
        self.assertFalse({"thread/start", "thread/resume", "turn/start", "thread/list"} & set(self.native.methods()))
        prompt = row["prompt"]
        for value in ("Implement parser", "Scope: parser only", row["id"], "caller", str(self.root)):
            self.assertIn(value, prompt)
        self.assertEqual(row["assignment_delivery"]["turn_id"], "desktop-first")
        self.assertEqual(read_json(row["session_receipt"])["thread_id"], row["camel_thread_id"])
        self.assertEqual(self.assign(context="Scope: parser only")["camel_thread_id"], row["camel_thread_id"])
        self.assertEqual(self.native.create_calls, 1)
        self.assertEqual(self.native.recover_calls, 1)

    def test_unknown_creation_is_never_replayed_by_assign_or_resume(self):
        self.native.failure = DesktopUncertain("response lost")
        with self.assertRaisesRegex(HarnessError, "retained"):
            self.assign()
        row = workflows.task_status(self.root)["tasks"][0]
        self.assertIsNone(row["camel_thread_id"])
        self.native.failure = None
        self.assertEqual(self.assign()["phase"], "creation_uncertain")
        self.assertEqual(workflows.resume_task(self.root, row["id"])["phase"], "creation_uncertain")
        self.assertEqual(self.native.create_calls, 1)

    def test_explicit_created_id_recovery_verifies_original_input_without_recreate(self):
        self.native.verify_failure = True
        with self.assertRaises(HarnessError):
            self.assign()
        state_path = self.root / ".oasis/local/tasks/state.json"
        state = read_json(state_path)
        row = state["tasks"][0]
        # The app applied the create but its reply/ID was lost to the caller.
        receipt = read_json(row["session_receipt"])
        receipt.pop("thread_id")
        receipt["phase"] = "creation_started"
        row["camel_thread_id"] = None
        write_json(row["session_receipt"], receipt)
        write_json(state_path, state)
        self.native.verify_failure = False
        result = workflows.resume_task(self.root, row["id"], camel_id="desktop-child")
        self.assertEqual(result["phase"], "assigned")
        self.assertEqual(self.native.create_calls, 1)
        self.assertEqual(self.native.sent, 0)
        with self.assertRaisesRegex(HarnessError, "unresolved"):
            workflows.resume_task(self.root, row["id"], camel_id="another-chat")

    def test_known_created_id_survives_readback_failure_and_recovers_without_send(self):
        self.native.verify_failure = True
        with self.assertRaises(HarnessError):
            self.assign()
        row = workflows.task_status(self.root)["tasks"][0]
        self.assertEqual(row["camel_thread_id"], "desktop-child")
        self.assertEqual(read_json(row["session_receipt"])["thread_id"], "desktop-child")
        self.native.verify_failure = False
        recovered = workflows.resume_task(self.root, row["id"])
        self.assertEqual(recovered["assignment_delivery"]["turn_id"], "desktop-first")
        self.assertEqual(self.native.create_calls, 1)
        self.assertEqual(self.native.sent, 0)

    def test_proven_not_sent_can_retry_same_task_only(self):
        self.native.failure = DesktopNotSent("pipe never opened")
        with self.assertRaises(HarnessError):
            self.assign()
        row = workflows.task_status(self.root)["tasks"][0]
        self.native.failure = None
        result = workflows.resume_task(self.root, row["id"])
        self.assertEqual(result["id"], row["id"])
        self.assertEqual(result["phase"], "assigned")
        self.assertEqual(self.native.create_calls, 2)
        self.assertEqual(len(self.native.threads), 2)

    def test_plan_initial_turn_only_holds_for_one_manual_native_mode_instruction(self):
        row = self.assign(planning=True)
        self.assertEqual(row["phase"], "manual_plan")
        self.assertIn("Do not begin planning or implementation", row["prelude_delivery"]["text"])
        self.assertNotIn("Do not begin planning", row["prompt"])
        self.assertNotIn("assignment_delivery", row)
        self.assertIn(row["camel_thread_id"], row["instruction"])
        self.assertEqual(self.assign(planning=True)["camel_thread_id"], row["camel_thread_id"])
        self.assertEqual(self.native.create_calls, 1)
        self.assertFalse(workflows._notification_pending(self.root, read_json(self.root / ".oasis/local/tasks/state.json")))

    def test_followup_preserves_chat_and_omits_unsupported_native_skill_attachment(self):
        row = self.assign()
        self.native.threads[row["camel_thread_id"]]["status"] = {"type": "idle"}
        followup = workflows.resume_task(self.root, row["id"], "Change parser scope")
        self.assertEqual(followup["camel_thread_id"], row["camel_thread_id"])
        self.assertEqual(self.native.create_calls, 1)
        sent = [params for method, params in self.native.calls if method == "turn/start"][-1]
        self.assertEqual([part["type"] for part in sent["input"]], ["text"])
        self.assertNotIn("thread/resume", self.native.methods())

    def test_different_request_inputs_do_not_touch_native_chat(self):
        self.assign()
        before = self.native.create_calls, self.native.recover_calls
        with self.assertRaisesRegex(HarnessError, "different inputs"):
            self.assign(context="Changed meaning")
        self.assertEqual((self.native.create_calls, self.native.recover_calls), before)


class NativeDesktopWorkflow(unittest.TestCase):
    def setUp(self):
        from tests.test_desktop_sessions import SOURCE, Tools, Watch
        self.source = SOURCE
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root, self.home = self.base / "project", self.base / "codex"
        self.root.mkdir()
        write_json(self.root / ".oasis/project.json", {"extensions": {"workflow": {"mode": "oasis"}}})
        self.tools = Tools(self.home, self.root)
        self.database = self.home / "state_5.sqlite"
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT NOT NULL)")
            connection.execute("CREATE TABLE thread_spawn_edges (parent_thread_id TEXT NOT NULL, child_thread_id TEXT PRIMARY KEY, status TEXT NOT NULL)")
        def index_child():
            with closing(sqlite3.connect(self.database)) as connection, connection:
                connection.executemany("INSERT OR REPLACE INTO threads VALUES (?,?)", [
                    (identity, str(row["path"])) for identity, row in self.tools.rows.items()])
        self.tools.after_create = index_child
        original_call = self.tools.call
        def tool_call(name, args, **kwargs):
            result = original_call(name, args, **kwargs)
            if name == "set_thread_archived":
                row = self.tools.rows[args["threadId"]]
                directory = self.home / ("archived_sessions" if args["archived"] else "sessions")
                directory.mkdir(exist_ok=True)
                target = directory / row["path"].name
                row["path"].rename(target)
                row["path"] = target
                index_child()
            return result
        self.tools.call = tool_call
        native_class = desktop_sessions.DesktopServer
        self.enterContext(patch.dict(os.environ, {"CODEX_THREAD_ID": SOURCE, "CODEX_HOME": str(self.home),
                                                 "CODEX_APP_TOOLS_PIPE_PATH": r"\\.\pipe\fixture"}))
        self.enterContext(patch.object(desktop_sessions, "DesktopServer", lambda originator:
            native_class(originator, tools=self.tools, codex_home=self.home, watcher_factory=Watch)))
        self.enterContext(patch.object(sessions, "AppServer", side_effect=AssertionError("external writer started")))
        for name in ("ensure_running", "status"):
            self.enterContext(patch.object(notifications, name, return_value={"state": "fixture"}))

    def assign(self, **kwargs):
        return workflows.assign(self.root, self.source, "Review parser", request_id="native-once", **kwargs)

    def final(self, row):
        native = self.tools.rows[row["camel_thread_id"]]
        native["turns"][-1]["items"].append({"id": "native-final", "type": "agentMessage",
                                            "phase": "final_answer", "text": "Reviewed parser."})
        return native

    def test_dispatch_and_terminal_notice_use_native_tools_without_external_writer(self):
        row = self.assign()
        self.final(row)
        done = workflows.complete(self.root, row["id"], "Review done", checks="manual fixture")
        self.assertEqual(done["completion"]["delivery"]["state"], "accepted")
        calls = [name for name, _, _ in self.tools.calls]
        self.assertEqual(calls.count("create_thread"), 1)
        self.assertEqual(calls.count("send_message_to_thread"), 1)
        self.assertNotIn("set_thread_archived", calls)

    def test_owner_new_turn_preserves_chat_and_prevents_stale_collection(self):
        row = self.assign()
        native = self.final(row)
        native["turns"].append({"id": "owner-steered-turn", "status": "inProgress", "items": [
            {"id": "owner-input", "type": "userMessage", "content": [{"type": "text", "text": "Change direction"}]}]})
        native["native"]["status"] = {"type": "active"}
        done = workflows.complete(self.root, row["id"], "Earlier review done")
        self.assertEqual(done["phase"], "terminal_unverified")
        self.assertFalse(any(name == "set_thread_archived" for name, _, _ in self.tools.calls))

    def test_collection_archive_and_followup_restore_reuse_same_native_chat(self):
        row = self.assign()
        self.final(row)
        workflows.complete(self.root, row["id"], "Review done", checks="manual fixture")
        collected = workflows.collect(self.root, row["id"])
        self.assertEqual(collected["collection_receipt"]["status"], "collected")
        self.assertTrue(collected["archived"])
        followup = workflows.resume_task(self.root, row["id"], "Review additional parser case")
        self.assertEqual(followup["camel_thread_id"], row["camel_thread_id"])
        self.assertFalse(followup["archived"])
        self.assertEqual([name for name, _, _ in self.tools.calls].count("create_thread"), 1)

    def test_archive_preserves_descendants_outside_task_scope(self):
        row = self.assign()
        self.final(row)
        workflows.complete(self.root, row["id"], "Review done")
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("INSERT INTO thread_spawn_edges VALUES (?,?,?)", (
                row["camel_thread_id"], "00000000-0000-4000-8000-000000000088", "open"))
        with self.assertRaisesRegex(HarnessError, "unrelated descendant"):
            workflows.collect(self.root, row["id"])
        self.assertFalse(any(name == "set_thread_archived" for name, _, _ in self.tools.calls))

    def test_manual_plan_resume_binds_actual_planning_turn_instead_of_holding_turn(self):
        import json
        row = self.assign(planning=True)
        self.assertEqual(row["phase"], "manual_plan")
        holding = row["prelude_delivery"]["turn_id"]
        pending = workflows.resume_task(self.root, row["id"])
        self.assertEqual(pending["phase"], "manual_plan")
        self.assertFalse(any(name == "send_message_to_thread" for name, _, _ in self.tools.calls))
        path = self.tools.rows[row["camel_thread_id"]]["path"]
        saved = sessions.latest_settings(path)
        saved["collaboration_mode"] = {"mode": "plan"}
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"type": "turn_context", "payload": saved}) + "\n")
        planned = workflows.resume_task(self.root, row["id"])
        self.assertEqual(planned["phase"], "assigned")
        self.assertNotEqual(planned["assignment_delivery"]["turn_id"], holding)
        self.assertEqual(planned["assignment_delivery"]["text"], row["prompt"])
        self.assertEqual(planned["prelude_delivery"]["turn_id"], holding)

    def test_implementation_followup_waits_for_actual_default_mode_then_resumes_same_request(self):
        import json
        row = self.assign()
        path = self.tools.rows[row["camel_thread_id"]]["path"]
        saved = sessions.latest_settings(path)
        saved["collaboration_mode"] = {"mode": "plan"}
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"type": "turn_context", "payload": saved}) + "\n")
        pending = workflows.resume_task(self.root, row["id"], "Implement reviewed parser", implementation=True)
        self.assertEqual(pending["phase"], "manual_mode")
        self.assertFalse(any(name == "send_message_to_thread" for name, _, _ in self.tools.calls))
        saved["collaboration_mode"] = {"mode": "default"}
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"type": "turn_context", "payload": saved}) + "\n")
        actual = workflows.resume_task(self.root, row["id"])
        self.assertEqual(actual["phase"], "assigned")
        self.assertEqual(actual["assignment_delivery"]["text"], pending["prompt"])
        self.assertEqual(actual["cycle"], pending["cycle"])


if __name__ == "__main__":
    unittest.main()
