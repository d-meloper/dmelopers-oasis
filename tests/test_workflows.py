"""Mode and Camel lifecycle fixtures, with real local state and injected RPC."""
import copy
from pathlib import Path
import tempfile
import unittest

from oasis_harness import sessions, workflows
from oasis_harness.common import HarnessError, read_json, write_json
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
        self.assertEqual((self.root / ".oasis/state/tasks.md").read_bytes(), before)
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

    def test_explicit_terminal_result_collects_during_native_final_turn(self):
        row = self.assign()
        self.native.threads[row["camel_thread_id"]]["status"] = {"type": "active"}
        self.complete(row)
        actual = workflows.collect(self.root, row["id"], factory=self.native)
        self.assertEqual(actual["phase"], "archived")
        self.assertEqual(self.native.methods().count("thread/archive"), 1)
        self.assertEqual(self.native.sent, 2)

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
