"""Mode and Camel lifecycle fixtures, with real local state and injected RPC."""
import copy
from pathlib import Path
import tempfile
import threading
import time
import unittest

from oasis_harness import sessions, workflows
from oasis_harness.common import HarnessError, digest, read_json, write_json
from tests.test_sessions import NativeFixture


class WorkflowContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.native = NativeFixture(self.root)
        self.native.threads["caller"]["name"] = "A renamed manager"
        for name in ("oasis-camel", "oasis-cameleer", "oasis-maintenance", "oasis-pioneer"):
            path = self.root / f".agents/skills/{name}/SKILL.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"Fixture {name} instructions.\n", encoding="utf-8")

    def assign(self, **kwargs):
        return workflows.assign(self.root, "caller", "Implement the scoped parser", factory=self.native, **kwargs)

    def complete(self, row, **kwargs):
        return workflows.complete(self.root, row["id"], "Done. Parser and focused checks pass.",
                                  result="fixture-result", checks="parser checks pass", factory=self.native, **kwargs)

    def pending_native_turn(self, row):
        native = self.native.threads[row["camel_thread_id"]]
        native["status"] = {"type": "active"}
        turn = native["turns"][-1]
        turn["status"] = "inProgress"
        turn["items"] = [item for item in turn["items"] if item["type"] != "agentMessage"]
        turn["items"].append({"id": "commentary", "type": "agentMessage", "phase": "commentary", "text": "Result notice sent"})
        return native, turn

    def finish_native_turn(self, native, turn):
        turn["items"].append({"id": "actual-final", "type": "agentMessage", "phase": "final_answer", "text": "Actual final output"})
        turn["status"], native["status"] = "completed", {"type": "idle"}

    def test_reused_request_ids_reject_changed_inputs_without_native_calls(self):
        row = self.assign(request_id="fixed-id")
        self.complete(row)
        before = len(self.native.calls)
        with self.assertRaisesRegex(HarnessError, "different inputs"):
            workflows.assign(self.root, "caller", "Different goal", request_id="fixed-id", factory=self.native)
        self.assertEqual(len(self.native.calls), before)
        follow = workflows.resume_task(self.root, row["id"], "First follow-up", request_id="follow-1", factory=self.native)
        self.complete(follow)
        before = len(self.native.calls)
        with self.assertRaisesRegex(HarnessError, "different inputs"):
            workflows.resume_task(self.root, row["id"], "Different follow-up", request_id="follow-1", factory=self.native)
        self.assertEqual(len(self.native.calls), before)
        workflows.resume_task(self.root, row["id"], "Second follow-up", request_id="follow-2", factory=self.native)
        sent = self.native.sent
        old = workflows.resume_task(self.root, row["id"], "First follow-up", request_id="follow-1", factory=self.native)
        self.assertEqual(old["cycle"], follow["cycle"])
        self.assertEqual(self.native.sent, sent)

    def test_known_creation_rejection_recovers_only_the_existing_assignment(self):
        self.native.reject["thread/start"] = {"code": -32602, "message": "Rejected before create"}
        with self.assertRaises(HarnessError):
            self.assign(request_id="once")
        pending = workflows.task_status(self.root)["tasks"][0]
        actual = workflows.resume_task(self.root, pending["id"], factory=self.native)
        self.assertEqual(actual["id"], pending["id"])
        self.assertEqual(actual["phase"], "assigned")
        self.assertEqual(self.native.started, 1)

    def test_completion_and_restore_validate_actual_project_binding(self):
        row = self.assign()
        self.native.threads["caller"]["projectId"] = "OTHER"
        sent = self.native.sent
        with self.assertRaisesRegex(HarnessError, "another project"):
            self.complete(row)
        self.assertEqual(self.native.sent, sent)
        self.native.threads["caller"]["projectId"] = "fixture-project"
        self.complete(row)
        workflows.collect(self.root, row["id"], factory=self.native)
        self.native.threads[row["camel_thread_id"]]["projectId"] = "OTHER"
        with self.assertRaisesRegex(HarnessError, "another project"):
            workflows.resume_task(self.root, row["id"], "Follow-up", factory=self.native)
        self.assertNotIn("thread/unarchive", self.native.methods())

    def test_old_unstarted_mode_plan_cannot_replace_new_roles(self):
        old = workflows.plan(self.root, "oasis", "caller", factory=self.native)
        current = workflows.plan(self.root, "pioneer", "caller", factory=self.native)
        workflows.start(current, factory=self.native)
        before = len(self.native.calls)
        with self.assertRaisesRegex(HarnessError, "stale"):
            workflows.start(old, factory=self.native)
        self.assertEqual(len(self.native.calls), before)
        self.assertEqual(workflows.status(self.root)["initialized_mode"], "pioneer")

    def test_mode_switch_preserves_independent_role_and_unlinked_work(self):
        prepared = workflows.plan(self.root, "oasis", "caller", factory=self.native)
        workflows.start(prepared, factory=self.native)
        state_path = self.root / ".oasis/local/workflows/state.json"
        state = read_json(state_path)
        self.native.add("independent", status="active")
        state["roles"].append({"role": "Camel", "thread_id": "independent"})
        write_json(state_path, state)
        write_json(self.root / ".oasis/local/tasks/state.json", {"schema_version": 1, "dependencies": [], "tasks": [
            {"id": "independent-task", "camel_thread_id": "independent", "cameleer_thread_id": "another-manager",
             "goal": "Unlinked ongoing work", "phase": "assigned"}]})
        operation = workflows.plan(self.root, "pioneer", "caller", factory=self.native)
        self.assertNotIn("independent", [row["thread_id"] for row in operation["old_roles"]])
        self.assertEqual(workflows.start(operation, factory=self.native)["phase"], "complete")
        self.assertFalse(self.native.threads["independent"]["archived"])
        self.assertIn("independent", [row["thread_id"] for row in read_json(state_path)["unrelated"]])

    def test_summary_reports_pending_notice_current_goal_and_location_without_prompt(self):
        location = str(self.root / "source-module")
        row = self.assign(location=location)
        text = self.native.threads[row["camel_thread_id"]]["turns"][0]["items"][0]["content"][0]["text"]
        self.assertIn("Assigned work location: " + location, text)
        self.assertEqual(self.native.threads[row["camel_thread_id"]]["cwd"], str(self.root))
        self.native.lose["turn/start"] = 1
        with self.assertRaises(HarnessError):
            self.complete(row)
        actual = workflows.task_status(self.root, summary=True)["tasks"][0]
        self.assertEqual(actual["completion_notice"]["state"], "uncertain")
        self.assertEqual(actual["phase"], "completed")
        self.assertNotIn("prompt", actual)
        self.assertNotIn("history", actual)
        self.assertIn("completion notice uncertain", (self.root / ".oasis/state/tasks.md").read_text(encoding="utf-8"))
        self.complete(row)
        workflows.resume_task(self.root, row["id"], "Current follow-up\nFurther detail", factory=self.native)
        actual = workflows.task_status(self.root, row["id"], summary=True)["tasks"][0]
        self.assertEqual(actual["goal"], "Current follow-up")
        self.assertEqual(workflows.task_status(self.root, row["id"])["goal"], row["goal"])

    def test_table_refresh_failure_preserves_original_native_rejection(self):
        from unittest.mock import patch
        row = self.assign()
        self.native.reject["turn/start"] = {"code": -32000, "message": "Original native rejection"}
        with patch.object(workflows, "_render_tasks", side_effect=HarnessError("Table unavailable")):
            with self.assertRaises(sessions.NativeError) as error:
                self.complete(row)
        self.assertIn("Original native rejection", str(error.exception))
        self.assertEqual(workflows.task_status(self.root, row["id"])["phase"], "completed")
        self.assertIn("Table unavailable", error.exception.__notes__[0])

    def test_legacy_followup_matches_known_saved_message_without_rewriting(self):
        row = self.assign()
        self.complete(row)
        follow = workflows.resume_task(self.root, row["id"], "Old follow-up", request_id="legacy", factory=self.native)
        self.complete(follow)
        path = self.root / ".oasis/local/tasks/state.json"
        state = read_json(path)
        state["tasks"][0].pop("followup_input_sha256")
        write_json(path, state)
        before = path.read_bytes()
        with self.assertRaisesRegex(HarnessError, "different recorded message"):
            workflows.resume_task(self.root, row["id"], "Different follow-up", request_id="legacy", factory=self.native)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(workflows.resume_task(self.root, row["id"], "Old follow-up", request_id="legacy", factory=self.native)["phase"], "completed")

    def test_consumed_task_types_and_duplicate_primary_roles_fail_before_mutation(self):
        row = self.assign()
        path = self.root / ".oasis/local/tasks/state.json"
        state = read_json(path)
        state["tasks"][0]["cycle"] = True
        write_json(path, state)
        with self.assertRaisesRegex(HarnessError, "cycle"):
            workflows.task_status(self.root)
        self.native.add("second-manager")
        with self.assertRaisesRegex(HarnessError, "More than one Cameleer"):
            workflows.plan(self.root, "oasis", "caller", bindings=[
                {"role": "Cameleer", "thread_id": "caller"}, {"role": "Cameleer", "thread_id": "second-manager"}], factory=self.native)

    def test_new_role_task_and_followup_prompts_remind_once_without_changing_request_keys(self):
        reminder = workflows.COMPLETION_REMINDER
        for role in ("Pioneer", "Oasis", "Cameleer"):
            self.assertEqual(workflows._prompt(role, "Preserve context", "ko").count(reminder), 1)
        operation = workflows.plan(self.root, "pioneer", "caller", task="Read the requested module", factory=self.native)
        self.assertEqual(operation["follow_on_task"], "Read the requested module\n\n" + reminder)
        row = self.assign(context="Parser context")
        self.assertEqual(row["request_key"], digest(["caller", "Implement the scoped parser", "Parser context", None, False, None]))
        self.assertTrue(row["prompt"].startswith("Apply $oasis-camel to this assigned task. Implement the scoped parser\n\nParser context"))
        self.assertEqual(row["prompt"].count(reminder), 1)
        followup = "Check the remaining whitespace case"
        follow = workflows.resume_task(self.root, row["id"], followup, factory=self.native)
        self.assertEqual(follow["followup_key"], digest([followup, False, False]))
        self.assertEqual(follow["prompt"], followup + "\n\n" + reminder)
        before = self.native.sent
        repeated = workflows.resume_task(self.root, row["id"], followup, factory=self.native)
        self.assertEqual(repeated["cycle"], follow["cycle"])
        self.assertEqual(repeated["prompt"], follow["prompt"])
        self.assertEqual(self.native.sent, before)

    def test_legacy_saved_prompts_and_lost_followup_responses_are_not_rewritten_or_replayed(self):
        row = self.assign()
        state_path = self.root / ".oasis/local/tasks/state.json"
        state = read_json(state_path)
        saved = state["tasks"][0]
        legacy = "The original saved assignment input"
        saved["prompt"] = legacy
        delivery_path = workflows._delivery_path(self.root, saved, "assign")
        delivery = read_json(delivery_path)
        delivery["text"] = legacy
        write_json(delivery_path, delivery)
        write_json(state_path, state)
        before = self.native.sent
        repeated = self.assign()
        self.assertEqual(repeated["prompt"], legacy)
        self.assertEqual(self.native.sent, before)
        original = workflows.COMPLETION_REMINDER
        self.native.lose["turn/start"] = 1
        with self.assertRaises(HarnessError):
            workflows.resume_task(self.root, row["id"], "Follow this request", request_id="fixed-followup", factory=self.native)
        pending = workflows.task_status(self.root, row["id"])
        sent = self.native.sent
        workflows.COMPLETION_REMINDER = "A future version of the reminder"
        try:
            recovered = workflows.resume_task(self.root, row["id"], "Follow this request", request_id="fixed-followup", factory=self.native)
        finally:
            workflows.COMPLETION_REMINDER = original
        self.assertEqual(recovered["prompt"], pending["prompt"])
        self.assertEqual(recovered["cycle"], pending["cycle"])
        self.assertEqual(self.native.sent, sent)
        self.assertEqual(recovered["assignment_delivery"]["state"], "accepted")

    def test_assign_uses_real_ids_native_skill_input_and_no_calf(self):
        def implementation(row, turn):
            if row["id"] == "caller":
                return
            (self.root / "parser.py").write_text("def parse(text):\n    return text.strip()\n", encoding="utf-8")
            turn["items"].append({"type": "commandExecution", "command": "fixture parser check"})
        self.native.on_turn = implementation
        row = self.assign(title="My custom title")
        self.assertEqual(row["phase"], "assigned")
        self.assertEqual(row["cameleer_thread_id"], "caller")
        self.assertTrue((self.root / "parser.py").is_file())
        self.assertEqual(self.native.started, 1)
        params = next(params for method, params in self.native.calls if method == "turn/start")
        self.assertEqual(params["input"][1], {"type": "skill", "name": "oasis-camel",
                         "path": str(self.root / ".agents/skills/oasis-camel/SKILL.md")})
        text = (self.root / ".oasis/state/tasks.md").read_text(encoding="utf-8")
        self.assertIn(f"codex://threads/{row['camel_thread_id']}", text)
        self.assertNotIn("Calf", text)
        self.assertEqual(self.assign(title="My custom title")["id"], row["id"])
        self.assertEqual(self.native.sent, 1)

    def test_renamed_camel_completes_directly_and_collects_without_owner_relay(self):
        row = self.assign()
        self.native.threads[row["camel_thread_id"]]["name"] = "Changed by user"
        before = (self.root / ".oasis/state/tasks.md").read_bytes()
        completed = self.complete(row)
        self.assertEqual(completed["completion"]["delivery"]["thread_id"], "caller")
        completed_table = (self.root / ".oasis/state/tasks.md").read_bytes()
        self.assertNotEqual(completed_table, before)
        self.assertIn(b"completed", completed_table)
        self.assertIn(b"fixture-result", completed_table)
        merges = []
        result = workflows.collect(self.root, row["id"], merge=lambda value: merges.append(value["id"]) or "merged-reference", factory=self.native)
        self.assertEqual(result["phase"], "archived")
        self.assertEqual(result["result"], "merged-reference")
        self.assertTrue(self.native.threads[row["camel_thread_id"]]["archived"])
        workflows.collect(self.root, row["id"], merge=lambda value: merges.append("duplicate"), factory=self.native)
        self.complete(row)
        self.assertEqual(merges, [row["id"]])
        self.assertEqual(self.native.sent, 2)
        self.assertEqual(self.native.methods().count("thread/archive"), 1)

    def test_normal_merged_reference_is_retained(self):
        row = self.assign()
        self.complete(row)
        result = workflows.collect(self.root, row["id"], merged_reference="actual-merge-sha", factory=self.native)
        self.assertEqual(result["result"], "actual-merge-sha")
        self.assertIn("actual-merge-sha", (self.root / ".oasis/state/tasks.md").read_text(encoding="utf-8"))

    def test_same_camel_is_restored_for_followup_and_completed_retry_is_noop(self):
        row = self.assign()
        self.complete(row)
        workflows.collect(self.root, row["id"], factory=self.native)
        follow = workflows.resume_task(self.root, row["id"], "Fix the whitespace edge", request_id="followup-1", factory=self.native)
        self.assertEqual(follow["camel_thread_id"], row["camel_thread_id"])
        self.assertEqual(self.native.started, 1)
        self.assertEqual(self.native.methods().count("thread/unarchive"), 1)
        self.complete(follow)
        sent = self.native.sent
        repeated = workflows.resume_task(self.root, row["id"], "Fix the whitespace edge", request_id="followup-1", factory=self.native)
        self.assertEqual(repeated["cycle"], follow["cycle"])
        self.assertEqual(repeated["phase"], "completed")
        self.assertEqual(self.native.sent, sent)
        next_follow = workflows.resume_task(self.root, row["id"], "Fix the whitespace edge", request_id="followup-2", factory=self.native)
        self.assertEqual(next_follow["cycle"], follow["cycle"] + 1)
        self.assertEqual(self.native.started, 1)

    def test_lost_creation_recovers_only_the_existing_task(self):
        self.native.lose["thread/start"] = 1
        with self.assertRaises(HarnessError):
            self.assign()
        pending = workflows.task_status(self.root)["tasks"][0]
        actual = workflows.resume_task(self.root, pending["id"], factory=self.native)
        self.assertEqual(actual["phase"], "assigned")
        self.assertEqual(self.native.started, 1)
        self.assertEqual(self.native.sent, 1)

    def test_lost_completion_send_recovers_without_duplicate_notice_or_task_loss(self):
        row = self.assign()
        self.native.lose["turn/start"] = 1
        with self.assertRaises(HarnessError):
            self.complete(row)
        retained = workflows.task_status(self.root, row["id"])
        self.assertEqual(retained["phase"], "completed")
        actual = self.complete(row)
        self.assertEqual(actual["completion"]["delivery"]["state"], "accepted")
        self.assertEqual(self.native.sent, 2)

    def test_completion_is_direct_input_to_an_active_cameleer(self):
        row = self.assign()
        self.native.threads["caller"]["status"] = {"type": "active"}
        self.native.threads["caller"]["turns"] = [{"id": "cameleer-current-turn", "status": "inProgress", "items": []}]
        self.native.lose["turn/start"] = 1
        with self.assertRaises(HarnessError):
            self.complete(row)
        result = self.complete(row)
        self.assertEqual(result["completion"]["delivery"]["turn_id"], "cameleer-current-turn")
        self.assertEqual(self.native.sent, 2)
        self.assertEqual(len(self.native.threads["caller"]["turns"][0]["items"]), 1)

    def test_merge_response_uncertainty_does_not_repeat_merge(self):
        row = self.assign()
        self.complete(row)
        calls = []
        def lost_merge(value):
            calls.append(value["id"])
            raise HarnessError("Merge result response lost")
        with self.assertRaises(HarnessError):
            workflows.collect(self.root, row["id"], merge=lost_merge, factory=self.native)
        pending = workflows.collect(self.root, row["id"], merge=lost_merge, factory=self.native)
        self.assertEqual(pending["phase"], "merge_uncertain")
        self.assertEqual(calls, [row["id"]])
        result = workflows.collect(self.root, row["id"], merged_reference="reconciled-merge", factory=self.native)
        self.assertEqual(result["phase"], "archived")

    def test_lost_archive_and_restore_responses_reconcile_native_ids(self):
        row = self.assign()
        self.complete(row)
        self.native.lose["thread/archive"] = 1
        with self.assertRaises(HarnessError):
            workflows.collect(self.root, row["id"], factory=self.native)
        self.assertEqual(workflows.collect(self.root, row["id"], factory=self.native)["phase"], "archived")
        self.assertEqual(self.native.methods().count("thread/archive"), 1)
        self.native.lose["thread/unarchive"] = 1
        with self.assertRaises(HarnessError):
            workflows.resume_task(self.root, row["id"], "Follow-up", factory=self.native)
        actual = workflows.resume_task(self.root, row["id"], "Follow-up", factory=self.native)
        self.assertEqual(actual["phase"], "assigned")
        self.assertEqual(self.native.methods().count("thread/unarchive"), 1)

    def test_archive_response_without_native_effect_stays_uncertain(self):
        row = self.assign()
        self.complete(row)
        self.native.archive_effective = False
        first = workflows.collect(self.root, row["id"], factory=self.native)
        second = workflows.collect(self.root, row["id"], factory=self.native)
        self.assertEqual(first["phase"], "archive_uncertain")
        self.assertEqual(second["phase"], "archive_uncertain")
        self.assertEqual(self.native.methods().count("thread/archive"), 1)

    def test_followup_after_lost_archive_restores_actual_camel_directly(self):
        row = self.assign()
        self.complete(row)
        self.native.lose["thread/archive"] = 1
        with self.assertRaises(HarnessError):
            workflows.collect(self.root, row["id"], factory=self.native)
        followup = workflows.resume_task(self.root, row["id"], "Correct whitespace", factory=self.native)
        self.assertEqual(followup["phase"], "assigned")
        self.assertFalse(self.native.threads[row["camel_thread_id"]]["archived"])
        self.assertEqual(self.native.methods().count("thread/unarchive"), 1)
        self.assertEqual(self.native.started, 1)

    def test_collection_waits_for_actual_terminal_final_before_merge_and_archive(self):
        row = self.assign()
        native, turn = self.pending_native_turn(row)
        self.complete(row)
        self.native.watch_supported = True
        observed = []
        def watch(params):
            self.native.watch_events.put({"method": "fs/changed", "params": {"watchId": "unrelated", "changedPaths": []}})
            def finish():
                observed.append((self.native.methods().count("thread/archive"), bool(merges)))
                self.finish_native_turn(native, turn)
                self.native.watch_events.put({"method": "fs/changed", "params": {"watchId": params["watchId"], "changedPaths": [native["path"]]}})
            timer = threading.Timer(0.03, finish)
            self.addCleanup(timer.join, 1)
            timer.start()
        self.native.on_watch = watch
        merges = []
        def merge(value):
            self.assertEqual(turn["status"], "completed")
            self.assertEqual(turn["items"][-1]["phase"], "final_answer")
            merges.append(value["id"])
        reads = self.native.methods().count("thread/turns/list")
        actual = workflows.collect(self.root, row["id"], merge=merge, factory=self.native, wait_timeout=1)
        self.assertEqual(actual["phase"], "archived")
        self.assertEqual(observed, [(0, False)])
        self.assertEqual(merges, [row["id"]])
        self.assertEqual(self.native.methods().count("thread/turns/list") - reads, 4)
        self.assertEqual(self.native.methods().count("fs/unwatch"), 1)
        self.assertEqual(self.native.watches, {})
        self.assertNotIn("thread/resume", self.native.methods())
        self.assertEqual(self.native.methods().count("thread/archive"), 1)
        self.assertEqual(self.native.sent, 2)

    def test_pending_collection_preserves_manual_reference_until_actual_final(self):
        row = self.assign()
        native, turn = self.pending_native_turn(row)
        self.complete(row)
        actual = workflows.collect(self.root, row["id"], merged_reference="reviewed-result", factory=self.native)
        self.assertEqual(actual["phase"], "awaiting_terminal")
        self.assertNotIn("merge_state", actual)
        self.assertNotIn("collected_result_key", actual)
        self.assertNotIn("thread/archive", self.native.methods())
        summary = workflows.task_status(self.root, row["id"], summary=True)["tasks"][0]
        self.assertEqual(summary["collection"], "awaiting_terminal")
        self.assertFalse(summary["native_turn"]["final_available"])
        self.finish_native_turn(native, turn)
        actual = workflows.collect(self.root, row["id"], merged_reference="reviewed-result", factory=self.native)
        self.assertEqual(actual["phase"], "archived")
        self.assertEqual(actual["result"], "reviewed-result")

    def test_native_failed_or_interrupted_turn_cannot_be_collected_as_success(self):
        for status, phase in (("failed", "failed"), ("interrupted", "cancelled")):
            with self.subTest(status=status):
                row = self.assign(request_id=status)
                native, turn = self.pending_native_turn(row)
                turn["status"], native["status"] = status, {"type": "idle"}
                self.complete(row)
                merges = []
                actual = workflows.collect(self.root, row["id"], merge=lambda value: merges.append(value), factory=self.native)
                self.assertEqual(actual["phase"], phase)
                self.assertEqual(actual["completion"]["outcome"], "completed")
                self.assertNotIn("collected_result_key", actual)
                self.assertEqual(merges, [])
                self.assertFalse(native["archived"])
        self.assertNotIn("thread/archive", self.native.methods())
        self.assertNotIn("fs/watch", self.native.methods())

    def test_collection_closes_watch_registration_race_without_waiting(self):
        row = self.assign()
        native, turn = self.pending_native_turn(row)
        self.complete(row)
        self.native.watch_supported = True
        self.native.on_watch = lambda params: self.finish_native_turn(native, turn)
        actual = workflows.collect(self.root, row["id"], factory=self.native, wait_timeout=0.5)
        self.assertEqual(actual["phase"], "archived")
        self.assertEqual(self.native.watches, {})

    def test_collection_event_timeout_keeps_camel_and_unwatches(self):
        row = self.assign()
        native, _ = self.pending_native_turn(row)
        self.complete(row)
        self.native.watch_supported = True
        started = time.monotonic()
        actual = workflows.collect(self.root, row["id"], factory=self.native, wait_timeout=0.02)
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(actual["phase"], "awaiting_terminal")
        self.assertEqual(self.native.watches, {})
        self.assertFalse(native["archived"])

    def test_collection_does_not_accept_other_final_phase_or_hide_watch_errors(self):
        row = self.assign()
        native = self.native.threads[row["camel_thread_id"]]
        native["turns"][-1]["items"][-1]["phase"] = "final"
        self.complete(row)
        actual = workflows.collect(self.root, row["id"], factory=self.native, wait_timeout=0)
        self.assertEqual(actual["phase"], "awaiting_terminal")
        self.native.reject["fs/watch"] = {"code": -32000, "message": "Actual watch permission denial"}
        with self.assertRaisesRegex(sessions.NativeError, "permission denial"):
            workflows.collect(self.root, row["id"], factory=self.native)
        self.assertFalse(native["archived"])

    def test_collection_preserves_new_native_work_before_and_after_merge(self):
        row = self.assign()
        self.complete(row)
        native = self.native.threads[row["camel_thread_id"]]
        extra = {"id": "unrelated-followup", "status": "completed", "items": []}
        native["turns"].append(extra)
        merges = []
        actual = workflows.collect(self.root, row["id"], merge=lambda value: merges.append(value), factory=self.native)
        self.assertEqual(actual["phase"], "terminal_unverified")
        self.assertEqual(merges, [])
        native["turns"].pop()
        def merge(value):
            native["turns"].append(extra)
            merges.append(value["id"])
        actual = workflows.collect(self.root, row["id"], merge=merge, factory=self.native)
        self.assertEqual(actual["phase"], "terminal_unverified")
        self.assertEqual(merges, [row["id"]])
        self.assertFalse(native["archived"])

    def test_collection_final_metadata_read_preserves_newly_active_camel(self):
        row = self.assign()
        self.complete(row)
        native = self.native.threads[row["camel_thread_id"]]
        original = self.native.call
        merged, reads = [], []
        def call(method, params):
            if method == "thread/read" and params["threadId"] == native["id"] and merged:
                reads.append(method)
                if len(reads) == 2:
                    native["status"] = {"type": "active"}
            return original(method, params)
        self.native.call = call
        actual = workflows.collect(self.root, row["id"], merge=lambda value: merged.append(value["id"]), factory=self.native)
        self.assertEqual(actual["phase"], "awaiting_terminal")
        self.assertFalse(native["archived"])
        self.assertNotIn("thread/archive", self.native.methods())

    def test_collection_wait_releases_project_lock_and_rejects_changed_assignment(self):
        first = self.assign(request_id="waiting-first")
        native, turn = self.pending_native_turn(first)
        self.complete(first)
        second = self.assign(request_id="independent-second")
        self.native.watch_supported = True
        registered, watch = threading.Event(), {}
        def on_watch(params):
            watch.update(params)
            registered.set()
        self.native.on_watch = on_watch
        results, errors, merges = [], [], []
        def collect():
            try:
                results.append(workflows.collect(self.root, first["id"], result="old-result", checks="old-checks",
                    merged_reference="old-merge", merge=lambda value: merges.append(value), factory=self.native, wait_timeout=3))
            except Exception as exc:
                errors.append(exc)
        collector = threading.Thread(target=collect, daemon=True)
        collector.start()
        try:
            self.assertTrue(registered.wait(2), "Collector did not reach its native I/O wait")
            other = self.complete(second)
            self.assertEqual(other["completion"]["delivery"]["state"], "accepted")
            follow = workflows.resume_task(self.root, first["id"], "Current follow-up", request_id="new-cycle", factory=self.native)
            self.assertEqual(follow["cycle"], 1)
        finally:
            self.finish_native_turn(native, turn)
            if watch:
                self.native.watch_events.put({"method": "fs/changed", "params": {"watchId": watch["watchId"], "changedPaths": [native["path"]]}})
            collector.join(timeout=4)
        self.assertFalse(collector.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(results[0]["collection"], "collection_changed")
        self.assertEqual(results[0]["cycle"], 1)
        self.assertEqual(merges, [])
        current = workflows.task_status(self.root, first["id"])
        self.assertNotIn("merge_state", current)
        self.assertNotEqual(current.get("result"), "old-result")
        self.assertNotEqual(current.get("checks"), "old-checks")
        self.assertEqual(self.native.watches, {})
        self.assertNotIn("thread/archive", self.native.methods())

    def test_legacy_collection_requires_actual_assignment_evidence(self):
        row = self.assign()
        self.complete(row)
        path = self.root / ".oasis/local/tasks/state.json"
        state = read_json(path)
        state["tasks"][0]["assignment_delivery"].pop("turn_id")
        write_json(path, state)
        receipt = workflows._delivery_path(self.root, state["tasks"][0], "assign")
        saved = read_json(receipt)
        saved.pop("turn_id")
        write_json(receipt, saved)
        native = self.native.threads[row["camel_thread_id"]]
        user = native["turns"][-1]["items"][0]
        original = copy.deepcopy(user)
        user.update(clientId="different", content=[{"type": "text", "text": "Unrelated work"}])
        actual = workflows.collect(self.root, row["id"], factory=self.native)
        self.assertEqual(actual["phase"], "terminal_unverified")
        native["turns"][-1]["items"][0] = original
        self.native.history_paging = False
        actual = workflows.collect(self.root, row["id"], factory=self.native)
        self.assertEqual(actual["phase"], "archived")

    def test_archive_native_error_preserves_result_for_scoped_retry(self):
        row = self.assign()
        self.complete(row)
        self.native.reject["thread/archive"] = {"code": -32000, "message": "Native archive busy"}
        with self.assertRaises(sessions.NativeError):
            workflows.collect(self.root, row["id"], factory=self.native)
        retained = workflows.task_status(self.root, row["id"])
        self.assertEqual(retained["phase"], "completed")
        self.assertEqual(retained["result"], "fixture-result")
        self.assertEqual(workflows.collect(self.root, row["id"], factory=self.native)["phase"], "archived")

    def test_failed_and_cancelled_tasks_stay_available_for_same_camel(self):
        for outcome in ("failed", "cancelled"):
            row = self.assign(request_id=outcome)
            self.complete(row, outcome=outcome)
            actual = workflows.collect(self.root, row["id"], factory=self.native)
            self.assertEqual(actual["phase"], outcome)
            self.assertFalse(self.native.threads[row["camel_thread_id"]]["archived"])
            self.assertEqual(workflows.resume_task(self.root, row["id"], "Try corrected input", factory=self.native)["camel_thread_id"], row["camel_thread_id"])

    def test_manual_rows_and_context_are_preserved_and_url_id_is_authoritative(self):
        path = self.root / ".oasis/state/tasks.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        original = "# Owner notes\n\nKeep this context.\n\n| [Changed label](codex://threads/legacy-id) | Existing work | assigned | path | |\n"
        path.write_text(original, encoding="utf-8")
        self.assertEqual(workflows.unfinished_tasks(self.root)[0]["camel_thread_id"], "legacy-id")
        self.assign()
        self.assertIn(original.rstrip(), path.read_text(encoding="utf-8"))
        before = path.read_text(encoding="utf-8").count("<!-- oasis-tasks:start -->")
        self.assign()
        self.assertEqual(path.read_text(encoding="utf-8").count("<!-- oasis-tasks:start -->"), before)

    def test_current_terminal_record_overrides_legacy_ready_without_deleting_it(self):
        row = self.assign()
        self.complete(row)
        legacy = self.root / ".oasis/local/sessions/legacy/receipt.json"
        write_json(legacy, {"role": "Calf", "thread_id": row["camel_thread_id"], "phase": "ready", "handoff_delivered": True})
        before = legacy.read_bytes()
        self.assertEqual(workflows.unfinished_tasks(self.root), [])
        self.assertEqual(legacy.read_bytes(), before)

    def test_native_plan_assign_starts_without_waiting_for_another_signal(self):
        row = self.assign(planning=True)
        self.assertEqual(row["phase"], "assigned")
        self.assertEqual(self.native.sent, 1)
        self.assertEqual(row["assignment_delivery"]["plan_route"], "settings")

    def test_pioneer_and_oasis_mode_operations_preserve_other_project_settings(self):
        project = read_json(self.root / ".oasis/project.json")
        project["extensions"]["owner_setting"] = {"keep": "yes"}
        project["git"]["profile"] = "main-test"
        write_json(self.root / ".oasis/project.json", project)
        prepared = workflows.plan(self.root, "pioneer", "caller", context={"arbitrary context": "retained"}, factory=self.native)
        first = workflows.start(prepared, factory=self.native)
        self.assertEqual(first["phase"], "complete")
        self.assertEqual(workflows.bound_pioneer(self.root, first["primary_thread_id"], self.native), first["primary_thread_id"])
        self.assertEqual(workflows.start(prepared, factory=self.native)["primary_thread_id"], first["primary_thread_id"])
        second_plan = workflows.plan(self.root, "oasis", "caller", task="Proceed with the requested work", factory=self.native)
        second = workflows.start(second_plan, factory=self.native)
        self.assertEqual(second["phase"], "complete")
        self.assertEqual(workflows.status(self.root)["initialized_mode"], "oasis")
        actual = read_json(self.root / ".oasis/project.json")
        self.assertEqual(actual["git"], project["git"])
        self.assertEqual(actual["extensions"]["owner_setting"], {"keep": "yes"})

    def test_invalid_mode_and_real_project_mismatch_still_fail(self):
        for mode in ([], {}, True, "automatic"):
            with self.subTest(mode=mode), self.assertRaises(HarnessError):
                workflows.effective_mode({"extensions": {"workflow": {"mode": mode}}})
        self.native.threads["caller"]["projectId"] = "different-project"
        with self.assertRaises(HarnessError):
            self.assign()


if __name__ == "__main__":
    unittest.main()
