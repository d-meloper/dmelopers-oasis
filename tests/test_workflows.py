import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from oasis_harness import sessions, workflows
from oasis_harness.common import HarnessError, digest, read_json, run, write_json
from oasis_harness.installation import apply as install_apply, plan as install_plan


ROOT = Path(__file__).resolve().parents[1]
SAVED = {"active_permission_profile": {"id": "custom-readonly"}, "sandbox_policy": {"type": "read-only"},
         "approval_policy": "on-request", "approvals_reviewer": "user", "model": "chosen-model", "reasoning_effort": "high"}


class NativeFixture:
    """Only injected metadata reads/creation; external messages are test inputs."""
    def __init__(self, root):
        self.root = root
        self.threads = {}
        self.logs = root / ".oasis/local/native-fixture"
        self.calls = []
        self.originator = None
        self.started = 0
        self.lost_creation = False
        self.add("caller", name="Owner", first="Owner request")

    def __call__(self, originator):
        self.originator = originator
        return self

    def __enter__(self): return self
    def __exit__(self, *_): pass

    def add(self, identity, *, name=None, first=None, parent=None, archived=False):
        path = self.logs / (identity + ".jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"type": "turn_context", "payload": SAVED}) + "\n", encoding="utf-8")
        row = {"id": identity, "name": name, "cwd": str(self.root), "projectId": "fixture-project",
               "originator": self.originator, "path": str(path), "status": {"type": "idle"},
               "turns": [], "archived": archived, "parent": parent}
        if first:
            row["turns"].append({"id": identity + "-initial", "status": "completed",
                                 "items": [{"type": "userMessage", "content": [{"type": "text", "text": first}]}]})
        self.threads[identity] = row
        return row

    def pages(self, method, params):
        self.calls.append(method)
        if method == "project/list":
            return [{"id": "fixture-project", "roots": [{"path": str(self.root)}]}]
        if method == "permissionProfile/list":
            return [{"id": "custom-readonly", "allowed": True}]
        if method != "thread/list":
            raise AssertionError(method)
        rows = [copy.deepcopy(row) for row in self.threads.values() if row["archived"] == params.get("archived", False)]
        if "ancestorThreadId" in params:
            ancestor = params["ancestorThreadId"]
            def child(row):
                parent = row.get("parent")
                while parent:
                    if parent == ancestor:
                        return True
                    parent = self.threads.get(parent, {}).get("parent")
                return False
            rows = [row for row in rows if child(row)]
        return rows

    def call(self, method, params):
        self.calls.append(method)
        if method == "thread/start":
            self.started += 1
            row = self.add("created-" + str(self.started))
            if self.lost_creation:
                self.lost_creation = False
                raise HarnessError("Lost native creation response")
        elif method == "thread/read":
            row = copy.deepcopy(self.threads[params["threadId"]])
            if not params.get("includeTurns"):
                row.pop("turns")
            return {"thread": row}
        elif method == "thread/resume":
            row = self.threads[params["threadId"]]
        elif method == "thread/name/set":
            self.threads[params["threadId"]]["name"] = params["name"]
            return {}
        else:
            raise AssertionError("No implicit native lifecycle writes: " + method)
        settings = sessions.inherited_settings(SAVED)
        return {"thread": copy.deepcopy(row), "cwd": str(self.root), "activePermissionProfile": {"id": settings["permissions"]},
                "approvalPolicy": settings["approvalPolicy"], "approvalsReviewer": settings["approvalsReviewer"],
                "sandbox": settings["effective_sandbox"], "model": settings["model"], "reasoningEffort": settings["reasoning"]}

    def deliver(self, action, *, status="completed", tools=False, ack=None):
        row = self.threads[action["thread_id"]]
        items = [{"type": "userMessage", "content": [{"type": "text", "text": action["prompt"]}]}]
        if tools:
            items.append({"type": "commandExecution", "command": "fixture"})
        if action["kind"] == "assign":
            items.append({"type": "agentMessage", "text": action["ack"] if ack is None else ack, "phase": "final_answer"})
        row["turns"].append({"id": row["id"] + "-" + str(len(row["turns"])), "status": status, "items": items})
        row["status"] = {"type": "idle" if status == "completed" else "active"}

    def archive(self, identity):
        self.threads[identity]["archived"] = True


class WorkflowContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = tempfile.TemporaryDirectory()
        install_apply(install_plan(Path(cls.baseline.name), package=ROOT))

    @classmethod
    def tearDownClass(cls):
        cls.baseline.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        shutil.copytree(self.baseline.name, self.root, dirs_exist_ok=True)
        self.project = read_json(self.root / ".oasis/project.json")
        self.native = NativeFixture(self.root)
        patcher = patch.dict(os.environ, {"CODEX_THREAD_ID": "caller"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.readiness = patch("oasis_harness.sessions.source_readiness", return_value={"profile": "unmanaged"})
        self.readiness.start()
        self.addCleanup(self.readiness.stop)

    def prepare(self, mode=None, **kwargs):
        return workflows.plan(self.root, mode, "caller", factory=self.native, **kwargs)

    def begin(self, value):
        return workflows.start(value, "owner request", self.native)

    def inspect(self, result):
        return workflows.inspect(result["receipt"], self.native)

    def initialized(self, mode="pioneer"):
        value = self.prepare(mode)
        result = self.begin(value)
        for action in result["next_actions"]:
            self.native.deliver(action)
        return self.inspect(result)

    def test_missing_legacy_defaults_and_invalid_mode_are_explicit(self):
        self.assertEqual(workflows.effective_mode({"extensions": {}}), "oasis")
        for mode in (None, [], {}, True, "automatic"):
            with self.assertRaises(HarnessError):
                workflows.effective_mode({"extensions": {"workflow": {"mode": mode}}})
        with self.assertRaises(HarnessError):
            workflows.effective_mode({"extensions": {"workflow": []}})

    def test_selected_mode_without_state_requires_real_initialization(self):
        self.assertTrue(workflows.status(self.root)["initialization_required"])
        value = self.prepare()
        self.assertFalse(value["same_mode"])
        self.assertEqual([row["role"] for row in value["new_roles"]], ["Pioneer"])
        result = self.begin(value)
        self.assertEqual(result["phase"], "standby")
        self.assertEqual(self.native.started, 1)
        self.assertIsNone(workflows.status(self.root)["initialized_mode"])
        self.assertNotIn("turn/start", self.native.calls)
        self.assertNotIn("thread/archive", self.native.calls)
        self.native.deliver(result["next_actions"][0])
        result = self.inspect(result)
        self.assertEqual(result["phase"], "complete")
        self.assertEqual(workflows.status(self.root)["initialized_mode"], "pioneer")

    def test_partial_install_missing_manifest_cannot_create_chats(self):
        (self.root / ".oasis/install-manifest.json").unlink()
        with self.assertRaisesRegex(HarnessError, "ownership is incomplete"):
            self.prepare()
        self.assertEqual(self.native.started, 0)

    def test_partial_install_missing_pioneer_cannot_create_chats(self):
        (self.root / ".agents/skills/oasis-pioneer/SKILL.md").unlink()
        with self.assertRaisesRegex(HarnessError, "owned installation file is missing"):
            self.prepare()
        self.assertEqual(self.native.started, 0)

    def test_unknown_attempt_is_never_offered_for_replay(self):
        result = self.begin(self.prepare())
        action = result["next_actions"][0]
        workflows.resume(result["receipt"], "same owner scope", self.native, begin_action=action["id"])
        pending = self.inspect(result)["next_actions"][0]
        self.assertEqual(pending["outcome"], "uncertain")
        self.assertFalse(pending["retry_allowed"])
        with self.assertRaises(HarnessError):
            workflows.resume(result["receipt"], "same owner scope", self.native, begin_action=action["id"])
        self.native.deliver(action)
        self.assertEqual(self.inspect(result)["phase"], "complete")

    def test_local_completed_claim_is_not_native_evidence(self):
        result = self.begin(self.prepare())
        receipt = read_json(result["receipt"])
        receipt["phase"] = "complete"
        for action in receipt["actions"]:
            action["observed"] = True
        write_json(result["receipt"], receipt)
        with self.assertRaisesRegex(HarnessError, "completed marker"):
            self.inspect(result)
        self.assertIsNone(workflows.status(self.root)["initialized_mode"])

    def test_terminal_standby_is_required_even_with_ack_text(self):
        result = self.begin(self.prepare())
        self.native.deliver(result["next_actions"][0], status="inProgress")
        self.assertEqual(self.inspect(result)["phase"], "standby")
        row = self.native.threads[result["next_actions"][0]["thread_id"]]
        row["turns"][0]["status"] = "completed"
        row["status"] = {"type": "idle"}
        self.assertEqual(self.inspect(result)["phase"], "complete")

    def test_tools_in_initial_standby_keep_predecessors(self):
        result = self.begin(self.prepare())
        self.native.deliver(result["next_actions"][0], tools=True)
        with self.assertRaises(HarnessError):
            self.inspect(result)
        self.assertIsNone(workflows.status(self.root)["initialized_mode"])
        self.assertNotIn("thread/archive", self.native.calls)

    def test_wrong_ack_keeps_predecessors(self):
        result = self.begin(self.prepare())
        self.native.deliver(result["next_actions"][0], ack="Implementation complete")
        with self.assertRaises(HarnessError):
            self.inspect(result)
        self.assertIsNone(workflows.status(self.root)["initialized_mode"])

    def test_first_turn_settings_drift_blocks_archive(self):
        result = self.begin(self.prepare())
        action = result["next_actions"][0]
        self.native.deliver(action)
        path = Path(self.native.threads[action["thread_id"]]["path"])
        changed = {**SAVED, "approval_policy": "never"}
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"type": "turn_context", "payload": changed}) + "\n")
        with self.assertRaisesRegex(HarnessError, "settings drifted"):
            self.inspect(result)
        self.assertIsNone(workflows.status(self.root)["initialized_mode"])

    def test_same_mode_is_idempotent_and_real_cycles_create_fresh_targets(self):
        original = self.initialized()
        noop = self.begin(self.prepare("pioneer"))
        self.assertEqual(noop["phase"], "complete")
        self.assertEqual(noop["primary_thread_id"], original["primary_thread_id"])
        self.assertEqual(self.native.started, 1)
        transition = self.begin(self.prepare("oasis", context={"status": "Saved checkpoint", "open_work": ["Unfinished goal"]}))
        self.assertEqual(self.native.started, 3)
        self.assertEqual(workflows.status(self.root)["selected_mode"], "pioneer")
        for action in transition["next_actions"]:
            self.native.deliver(action)
        transition = self.inspect(transition)
        self.assertEqual([a["kind"] for a in transition["next_actions"]], ["archive"])
        self.native.archive(transition["next_actions"][0]["thread_id"])
        transition = self.inspect(transition)
        self.assertEqual(transition["phase"], "complete")
        self.assertEqual(workflows.status(self.root)["selected_mode"], "oasis")
        self.assertEqual(transition["navigation"]["thread_id"], transition["primary_thread_id"])
        self.assertIsNotNone(transition["navigation"]["oasis_thread_id"])
        reverse = self.begin(self.prepare("pioneer", context={"status": "Saved checkpoint"}))
        self.assertEqual(self.native.started, 4)
        self.assertNotEqual(reverse["next_actions"][0]["thread_id"], original["primary_thread_id"])

    def test_switch_task_is_offered_only_after_verified_archive_and_commit(self):
        original = self.initialized()
        transition = self.begin(self.prepare("oasis", context={"status": "Saved"}, task="Implement the owner's next feature"))
        for action in transition["next_actions"]:
            self.native.deliver(action)
        transition = self.inspect(transition)
        self.native.archive(original["primary_thread_id"])
        transition = self.inspect(transition)
        self.assertEqual(transition["phase"], "task_pending")
        self.assertEqual(transition["next_actions"][0]["kind"], "task")
        self.assertEqual(workflows.status(self.root)["selected_mode"], "oasis")
        self.native.deliver(transition["next_actions"][0], status="inProgress")
        self.assertEqual(self.inspect(transition)["phase"], "complete")
        self.assertIsNone(workflows.status(self.root)["pending_operation"])

    def test_lost_creation_reconciles_one_id_and_never_recreates(self):
        self.native.lost_creation = True
        value = self.prepare()
        with self.assertRaises(HarnessError):
            self.begin(value)
        pending = workflows.status(self.root)["pending_operation"]
        result = workflows.resume(pending, "original request", self.native)
        self.assertEqual(result["phase"], "standby")
        self.assertEqual(self.native.started, 1)

    def test_other_pending_operation_blocks_before_metadata_resume(self):
        self.native.lost_creation = True
        value = self.prepare()
        with self.assertRaises(HarnessError):
            self.begin(value)
        pending = workflows.status(self.root)["pending_operation"]
        state_path = self.root / ".oasis/local/workflows/state.json"
        state = read_json(state_path)
        state["pending_operation"] = "different-owner-operation"
        write_json(state_path, state)
        before = list(self.native.calls)
        with self.assertRaisesRegex(HarnessError, "owns current state"):
            workflows.resume(pending, "old request", self.native)
        self.assertEqual(self.native.calls, before)
        self.assertEqual(self.native.started, 1)

    def test_drift_after_partial_metadata_blocks_before_any_new_creation(self):
        self.native.lost_creation = True
        value = self.prepare("oasis")
        with self.assertRaises(HarnessError):
            self.begin(value)
        pending = workflows.status(self.root)["pending_operation"]
        (self.root / "app.py").write_text("Owner checkpoint changed", encoding="utf-8")
        with self.assertRaisesRegex(HarnessError, "Source/index state changed"):
            workflows.resume(pending, "original owner scope", self.native)
        self.assertEqual(self.native.started, 1)
        self.assertNotIn("thread/archive", self.native.calls)

    def test_foreign_descendant_blocks_before_new_target_creation(self):
        original = self.initialized()
        child = self.native.add("unrelated", name="Ordinary chat", first="Unrelated task", parent=original["primary_thread_id"])
        child["projectId"] = "different-project"
        with self.assertRaisesRegex(HarnessError, "unscoped descendant"):
            self.prepare("oasis", context={"status": "Saved"})
        self.assertEqual(self.native.started, 1)
        self.assertIsNone(workflows.status(self.root)["pending_operation"])

    def test_new_foreign_descendant_after_standby_prevents_archive(self):
        original = self.initialized()
        transition = self.begin(self.prepare("oasis", context={"status": "Saved"}))
        for action in transition["next_actions"]:
            self.native.deliver(action)
        self.native.add("unrelated", first="Unrelated task", parent=original["primary_thread_id"])
        with self.assertRaisesRegex(HarnessError, "unscoped descendant"):
            self.inspect(transition)
        self.assertFalse(self.native.threads[original["primary_thread_id"]]["archived"])

    def test_new_separately_rooted_linked_worker_after_start_prevents_archive(self):
        original = self.initialized()
        transition = self.begin(self.prepare("oasis", context={"status": "Saved"}))
        for action in transition["next_actions"]:
            self.native.deliver(action)
        worker = self.worker(original["primary_thread_id"])
        worker["parent"] = None  # Native archive cascade cannot discover this link.
        with self.assertRaisesRegex(HarnessError, "new connected worker"):
            self.inspect(transition)
        self.assertFalse(self.native.threads[original["primary_thread_id"]]["archived"])

    def worker(self, primary, *, marker=True):
        originator = "worker-fixture"
        text = f"[OASIS_SESSION_ROLE {originator} Developer]\nOwner delegated this ordinary task" if marker else "Unassigned"
        row = self.native.add("worker", name="Developer_Test", first=text, parent=primary)
        write_json(self.root / f".oasis/local/sessions/{originator}/receipt.json", {
            "phase": "ready", "originator": originator, "thread_id": row["id"], "role": "Developer",
            "target": str(self.root), "project_id": "fixture-project", "parent_thread_id": primary,
            "assignment_marker": f"[OASIS_SESSION_ROLE {originator} Developer]", "authority_reference": "Owner delegated"})
        return row

    def test_linked_worker_is_automatically_scoped_and_archived_first(self):
        original = self.initialized()
        worker = self.worker(original["primary_thread_id"])
        transition = self.begin(self.prepare("oasis", context={"status": "All work saved", "open_work": ["Remaining work"]}))
        for action in transition["next_actions"]:
            self.native.deliver(action)
        transition = self.inspect(transition)
        self.assertEqual([a["thread_id"] for a in transition["next_actions"]], [worker["id"]])
        self.native.archive(worker["id"])
        transition = self.inspect(transition)
        self.assertEqual([a["thread_id"] for a in transition["next_actions"]], [original["primary_thread_id"]])

    def test_running_or_unassigned_worker_blocks_with_no_pending_journal(self):
        original = self.initialized()
        worker = self.worker(original["primary_thread_id"])
        worker["status"] = {"type": "active"}
        with self.assertRaisesRegex(HarnessError, "saved checkpoint"):
            self.prepare("oasis", context={"status": "Saved"})
        self.assertEqual(self.native.started, 1)
        self.assertIsNone(workflows.status(self.root)["pending_operation"])
        worker["status"] = {"type": "idle"}
        worker["turns"][0]["items"][0]["content"][0]["text"] = "Unassigned"
        with self.assertRaisesRegex(HarnessError, "verified native role assignment"):
            self.prepare("oasis", context={"status": "Saved"})

    def test_reactivated_worker_receipt_is_not_silently_skipped(self):
        original = self.initialized()
        self.worker(original["primary_thread_id"])
        path = self.root / ".oasis/local/sessions/worker-fixture/receipt.json"
        value = read_json(path)
        value["phase"] = "archived"
        write_json(path, value)
        with self.assertRaisesRegex(HarnessError, "reactivated"):
            self.prepare("oasis", context={"status": "Saved"})
        self.assertEqual(self.native.started, 1)

    def test_source_checkpoint_drift_refuses_without_rewriting_source(self):
        value = self.prepare()
        path = self.root / "app.py"
        path.write_text("Owner's saved work", encoding="utf-8")
        with self.assertRaisesRegex(HarnessError, "Source/index state changed"):
            self.begin(value)
        self.assertEqual(path.read_text(encoding="utf-8"), "Owner's saved work")
        self.assertEqual(self.native.started, 0)

    def test_dirty_worktree_and_staged_index_survive_initialization(self):
        run(["git", "-C", str(self.root), "init"])
        source = self.root / "app.py"
        source.write_text("staged owner work\n", encoding="utf-8")
        run(["git", "-C", str(self.root), "add", "app.py"])
        index = self.root / ".git/index"
        index_before = index.read_bytes()
        source.write_text("unstaged owner work\n", encoding="utf-8")
        self.initialized()
        self.assertEqual(index.read_bytes(), index_before)
        self.assertEqual(source.read_text(encoding="utf-8"), "unstaged owner work\n")

    def test_explicit_legacy_binding_requires_native_message_hash_not_title(self):
        self.native.add("legacy", name="Pioneer", first="Owner explicitly assigned Pioneer")
        with self.assertRaisesRegex(HarnessError, "Unbound existing role"):
            self.prepare()
        row = {"role": "Pioneer", "thread_id": "legacy", "parent_thread_id": None,
               "first_user_message_sha256": digest(b"Owner explicitly assigned Pioneer")}
        result = self.begin(self.prepare(bindings=[row]))
        self.assertEqual(result["primary_thread_id"], "legacy")
        self.assertEqual(self.native.started, 0)

    def test_reviewed_unrelated_chat_with_role_title_is_preserved(self):
        self.native.add("unrelated", name="Pioneer", first="Ordinary unrelated conversation")
        binding = {"role": "Unrelated", "thread_id": "unrelated", "parent_thread_id": None,
                   "first_user_message_sha256": digest(b"Ordinary unrelated conversation")}
        result = self.begin(self.prepare(bindings=[binding]))
        self.native.deliver(result["next_actions"][0])
        result = self.inspect(result)
        self.assertEqual(result["phase"], "complete")
        self.assertFalse(self.native.threads["unrelated"]["archived"])
        self.assertEqual(len(workflows.status(self.root)["roles"]), 1)

    def test_pioneer_binding_and_developer_actual_caller_guard(self):
        original = self.initialized()
        identity = original["primary_thread_id"]
        self.assertEqual(workflows.bound_pioneer(self.root, identity, self.native), identity)
        with self.assertRaises(HarnessError):
            workflows.bound_pioneer(self.root, "caller", self.native)
        self.assertEqual(sessions.title_for("Developer", "Task", {"id": identity, "name": "Pioneer"}, [], [], pioneer_id=identity), "Developer_Task")
        with self.assertRaises(HarnessError):
            sessions.title_for("Developer", "Task", {"id": "imposter", "name": "Pioneer"}, [], [], pioneer_id=identity)
        with self.assertRaises(HarnessError):
            sessions.title_for("Calf", "Task", {"id": identity, "name": "Pioneer"}, [], [])

    @unittest.skipUnless(os.name == "nt", "Windows link boundary")
    def test_linked_root_is_refused_before_reads_or_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            link = Path(tmp) / "linked"
            try:
                link.symlink_to(self.root, target_is_directory=True)
            except OSError:
                self.skipTest("Host does not permit disposable directory symlinks")
            with self.assertRaises(HarnessError):
                workflows.status(link)
            self.assertFalse((self.root / ".oasis/local/workflows/state.json").exists())


if __name__ == "__main__":
    unittest.main()
