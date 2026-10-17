"""Bootstrap metadata effects with separate stores and durable recovery."""
import copy
import json
import os
from contextlib import contextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from oasis_harness import project_bindings, sessions, workflows
from oasis_harness.common import HarnessError, read_json
from tests.test_sessions import NativeFixture, SAVED


class MetadataStore(NativeFixture):
    def __init__(self, root, project="app-project"):
        super().__init__(root)
        self.project = project
        self.threads["caller"]["projectId"] = project
        self.skip_effect = False
        self.after_update = None
        self.before_update = None
        self.failed_reads = 0
        self.projects = None

    def pages(self, method, params):
        if method == "project/list":
            self.calls.append((method, copy.deepcopy(params)))
            return self.projects if self.projects is not None else [{"id": self.project, "roots": [{"path": str(self.root)}]}]
        return super().pages(method, params)

    def call(self, method, params):
        if method == "thread/metadata/update" and self.before_update:
            self.before_update()
        if method == "thread/read" and self.failed_reads:
            self.failed_reads -= 1
            raise HarnessError("Readback unavailable")
        if method == "thread/metadata/update" and self.skip_effect:
            self.calls.append((method, copy.deepcopy(params)))
            raise HarnessError("Metadata response lost before an observed effect")
        result = super().call(method, params)
        if method == "thread/metadata/update" and self.after_update:
            self.after_update()
        return result


class ProjectBindingContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.native = MetadataStore(self.root)
        self.bindings = [{"role": "Pioneer", "thread_id": "caller", "parent_thread_id": None}]

    def plan(self):
        return workflows.plan(self.root, "pioneer", "caller", bindings=self.bindings, factory=self.native)

    def metadata_calls(self, server=None):
        return [params for method, params in (server or self.native).calls if method == "thread/metadata/update"]

    def test_active_unassigned_role_initializes_with_metadata_only(self):
        row = self.native.threads["caller"]
        row.update(projectId=None, status={"type": "active"})
        before = Path(row["path"]).read_bytes()
        plan = self.plan()
        self.assertEqual(self.metadata_calls(), [])
        result = workflows.start(plan, factory=self.native)
        self.assertEqual(result["phase"], "complete")
        self.assertEqual(self.metadata_calls(), [{"threadId": "caller", "projectId": "app-project"}])
        self.assertEqual(before, Path(row["path"]).read_bytes())
        self.assertFalse({"thread/start", "thread/resume", "turn/start", "thread/archive"} & set(self.native.methods()))
        receipt = read_json(result["receipt"])
        binding = read_json(receipt["binding_results"][0]["receipt"])
        self.assertEqual(binding["before_project_id"], None)
        self.assertEqual(binding["observed_project_id"], "app-project")
        self.assertEqual(binding["settings_before"], binding["settings_after"])

    def test_strict_verification_still_rejects_unassigned(self):
        row = self.native.threads["caller"]
        row["projectId"] = None
        with self.assertRaisesRegex(HarnessError, "unassigned"):
            sessions.check_thread_binding(row, "caller", {"target": str(self.root), "project_id": "app-project"})

    def test_effect_owner_observes_durable_intent_before_metadata_update(self):
        self.native.threads["caller"]["projectId"] = None
        plan = self.plan()
        observed = []
        def inspect_intent():
            receipts = list(workflows._receipt_path(plan).parent.glob("*-binding.json"))
            self.assertEqual(len(receipts), 1)
            journal = read_json(receipts[0])
            self.assertEqual(journal["state"], "issued")
            self.assertIsNone(journal["before_project_id"])
            self.assertEqual(journal["rpc"]["params"], {"threadId": "caller", "projectId": "app-project"})
            observed.append(journal["rpc"]["outcome"])
        self.native.before_update = inspect_intent
        self.assertEqual(workflows.start(plan, factory=self.native)["phase"], "complete")
        self.assertEqual(observed, ["issued"])

    def test_foreign_assignment_and_wrong_root_never_schedule_repairs(self):
        row = self.native.threads["caller"]
        for field, value in (("projectId", "foreign-project"), ("cwd", str(self.root / "other"))):
            original = row[field]
            row[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(HarnessError, "another project/root"):
                self.plan()
            row[field] = original
        self.assertEqual(self.metadata_calls(), [])

    def test_absent_membership_field_is_unknown_not_unassigned(self):
        self.native.threads["caller"].pop("projectId")
        with self.assertRaisesRegex(HarnessError, "membership is unavailable"):
            self.plan()
        self.assertEqual(self.metadata_calls(), [])

    def test_missing_or_ambiguous_project_prevents_any_effect(self):
        for rows in ([], [{"id": value, "roots": [{"path": str(self.root)}]} for value in ("a", "b")]):
            self.native.projects = rows
            with self.subTest(rows=rows), self.assertRaisesRegex(HarnessError, "exactly one"):
                self.plan()
        self.assertEqual(self.metadata_calls(), [])

    def test_stale_bound_plan_cannot_restore_a_removed_membership(self):
        plan = self.plan()
        self.native.threads["caller"]["projectId"] = None
        with self.assertRaisesRegex(HarnessError, "removed after planning"):
            workflows.start(plan, factory=self.native)
        self.assertEqual(self.metadata_calls(), [])

    def test_conflict_after_plan_blocks_before_metadata(self):
        self.native.threads["caller"]["projectId"] = None
        plan = self.plan()
        self.native.threads["caller"]["projectId"] = "new-owner-project"
        with self.assertRaisesRegex(HarnessError, "another project"):
            workflows.start(plan, factory=self.native)
        self.assertEqual(self.metadata_calls(), [])

    def test_lost_mutation_reply_reconciles_applied_value_without_replay(self):
        self.native.threads["caller"]["projectId"] = None
        self.native.lose["thread/metadata/update"] = 1
        plan = self.plan()
        result = workflows.start(plan, factory=self.native)
        self.assertEqual(result["phase"], "complete")
        self.assertEqual(workflows.start(plan, factory=self.native)["phase"], "complete")
        self.assertEqual(len(self.metadata_calls()), 1)

    def test_unobserved_effect_is_retained_and_never_automatically_reissued(self):
        self.native.threads["caller"]["projectId"] = None
        self.native.skip_effect = True
        result = workflows.start(self.plan(), factory=self.native)
        self.assertEqual(result["phase"], "binding_not_applied")
        again = workflows.resume(result["receipt"], factory=self.native)
        self.assertEqual(again["phase"], "binding_not_applied")
        self.assertEqual(len(self.metadata_calls()), 1)
        self.native.threads["caller"]["projectId"] = "app-project"
        self.assertEqual(workflows.resume(result["receipt"], factory=self.native)["phase"], "complete")
        self.assertEqual(len(self.metadata_calls()), 1)

    def test_unavailable_readback_preserves_uncertainty_until_resume(self):
        self.native.threads["caller"]["projectId"] = None
        self.native.after_update = lambda: setattr(self.native, "failed_reads", 1)
        result = workflows.start(self.plan(), factory=self.native)
        self.assertEqual(result["phase"], "binding_uncertain")
        self.assertEqual(workflows.resume(result["receipt"], factory=self.native)["phase"], "complete")
        self.assertEqual(len(self.metadata_calls()), 1)

    def test_unsupported_method_returns_manual_existing_host_recovery(self):
        self.native.threads["caller"]["projectId"] = None
        self.native.reject["thread/metadata/update"] = {"code": -32601, "message": "Method unavailable"}
        result = workflows.start(self.plan(), factory=self.native)
        self.assertEqual(result["phase"], "binding_unsupported")
        self.assertIn("existing host", result["next_actions"][0])
        self.assertEqual(workflows.resume(result["receipt"], factory=self.native)["phase"], "binding_unsupported")
        self.assertEqual(len(self.metadata_calls()), 1)
        self.assertEqual(self.native.started, 0)

    def test_changed_settings_are_preserved_and_stop_initialization(self):
        row = self.native.threads["caller"]
        row["projectId"] = None
        def change_selection():
            Path(row["path"]).write_text(json.dumps({"type": "turn_context", "payload": {**SAVED, "model": "new-user-choice"}}) + "\n", encoding="utf-8")
        self.native.after_update = change_selection
        with self.assertRaisesRegex(HarnessError, "changed model/permission"):
            workflows.start(self.plan(), factory=self.native)
        self.assertEqual(sessions.latest_settings(row["path"])["model"], "new-user-choice")
        self.assertEqual(self.native.started, 0)

    def test_reinitialization_reuses_role_without_duplicate_chat_or_mutation(self):
        self.native.threads["caller"]["projectId"] = None
        workflows.start(self.plan(), factory=self.native)
        result = workflows.start(self.plan(), factory=self.native)
        self.assertEqual(result["phase"], "complete")
        self.assertEqual(workflows.status(self.root)["roles"], self.bindings)
        self.assertEqual(len(self.metadata_calls()), 1)
        self.assertEqual(self.native.started, 0)

    def test_desktop_and_app_server_use_independent_ids_and_effects(self):
        for native_missing, desktop_missing in ((True, True), (True, False), (False, True)):
            with self.subTest(native_missing=native_missing, desktop_missing=desktop_missing):
                # Independent roots prevent completed workflow state from hiding a new case.
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory).resolve()
                    native = MetadataStore(root)
                    desktop = MetadataStore(root, "desktop-project")
                    native.threads["caller"]["projectId"] = None if native_missing else native.project
                    desktop.threads["caller"]["projectId"] = None if desktop_missing else desktop.project
                    plan = workflows.plan(root, "pioneer", "caller", bindings=self.bindings, factory=native)
                    plan["project_bindings"].append(project_bindings.inspect(desktop, root, "caller", "desktop"))
                    @contextmanager
                    def desktop_connection(_):
                        yield desktop
                    with patch.object(workflows, "_desktop_binding_server", desktop_connection):
                        result = workflows.start(plan, factory=native)
                    self.assertEqual(result["phase"], "complete")
                    self.assertEqual(self.metadata_calls(native), [{"threadId": "caller", "projectId": "app-project"}] if native_missing else [])
                    self.assertEqual(self.metadata_calls(desktop), [{"threadId": "caller", "projectId": "desktop-project"}] if desktop_missing else [])
                    self.assertFalse({"thread/resume", "turn/start"} & set(native.methods() + desktop.methods()))

    def test_desktop_bootstrap_preflight_is_automatically_included_when_available(self):
        desktop = MetadataStore(self.root, "desktop-project")
        self.native.threads["caller"]["projectId"] = None
        desktop.threads["caller"]["projectId"] = None
        @contextmanager
        def desktop_connection(_):
            yield desktop
        with (patch.object(sessions, "command_server", self.native),
              patch.object(workflows, "_desktop_binding_server", desktop_connection),
              patch.dict(os.environ, {"CODEX_APP_TOOLS_PIPE_PATH": "fixture-existing-pipe"})):
            plan = self.plan()
            self.assertEqual([(row["backend"], row["project_id"]) for row in plan["project_bindings"]],
                             [("app-server", "app-project"), ("desktop", "desktop-project")])
            self.assertEqual(self.metadata_calls() + self.metadata_calls(desktop), [])
            self.assertEqual(workflows.start(plan, factory=self.native)["phase"], "complete")

    def test_both_catalogs_are_checked_before_any_metadata_effect(self):
        desktop = MetadataStore(self.root, "desktop-project")
        self.native.threads["caller"]["projectId"] = None
        desktop.threads["caller"]["projectId"] = None
        plan = self.plan()
        plan["project_bindings"].append(project_bindings.inspect(desktop, self.root, "caller", "desktop"))
        desktop.threads["caller"]["projectId"] = "foreign-desktop-project"
        @contextmanager
        def desktop_connection(_):
            yield desktop
        with patch.object(workflows, "_desktop_binding_server", desktop_connection):
            with self.assertRaisesRegex(HarnessError, "another project"):
                workflows.start(plan, factory=self.native)
        self.assertEqual(self.metadata_calls() + self.metadata_calls(desktop), [])

    def test_backend_id_cannot_be_reused_for_the_other_store(self):
        desktop = MetadataStore(self.root, "desktop-project")
        self.native.threads["caller"]["projectId"] = None
        plan = self.plan()
        check = project_bindings.inspect(desktop, self.root, "caller", "desktop")
        check["project_id"] = check["previous_project_id"] = "app-project"
        plan["project_bindings"].append(check)
        @contextmanager
        def desktop_connection(_):
            yield desktop
        with patch.object(workflows, "_desktop_binding_server", desktop_connection):
            with self.assertRaisesRegex(HarnessError, "catalog changed"):
                workflows.start(plan, factory=self.native)
        self.assertEqual(self.metadata_calls() + self.metadata_calls(desktop), [])
