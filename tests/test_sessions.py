"""Native protocol fixtures: no real chats, turns or global settings writes."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from oasis_harness import sessions
from oasis_harness.common import HarnessError, read_json, write_json

SAVED = {"active_permission_profile": {"id": "custom-readonly"}, "sandbox_policy": {"type": "read-only"},
         "approval_policy": "on-request", "approvals_reviewer": "user", "model": "chosen-model", "reasoning_effort": "high"}


class NativeFixture:
    """A durable native store with controllable definite and ambiguous failures."""
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.threads = {}
        self.calls = []
        self.started = 0
        self.sent = 0
        self.originator = "fixture"
        self.lose = {}
        self.reject = {}
        self.persist_lost_send = True
        self.setter = True
        self.plan_supported = True
        self.turn_mode = True
        self.mismatch = False
        self.archive_effective = True
        self.active_start_same_turn = True
        self.echo_client_id = True
        self.no_settings_on_start = False
        self.on_turn = None
        if not (self.root / ".oasis/project.json").exists():
            write_json(self.root / ".oasis/project.json", {"name": "Fixture", "extensions": {"workflow": {"mode": "oasis"}}, "git": {"profile": "unmanaged"}})
        self.add("caller", name="Owner")

    def __call__(self, originator):
        self.originator = originator
        return self

    def __enter__(self): return self
    def __exit__(self, *_): pass

    def add(self, identity, *, name=None, parent=None, archived=False, status="idle", saved=None):
        path = self.root / ".oasis/local/native-fixture" / (identity + ".jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"type": "turn_context", "payload": saved or SAVED}) + "\n", encoding="utf-8")
        row = {"id": identity, "name": name, "cwd": str(self.root), "projectId": "fixture-project",
               "originator": self.originator, "path": str(path), "status": {"type": status}, "turns": [],
               "archived": archived, "parent": parent}
        self.threads[identity] = row
        return row

    def save(self, row, mode):
        try:
            current = sessions.latest_settings(row["path"])
        except sessions.MissingSavedSettings:
            current = copy.deepcopy(SAVED)
        current["collaboration_mode"] = mode
        with Path(row["path"]).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"type": "turn_context", "payload": current}) + "\n")

    def pages(self, method, params):
        self.calls.append((method, copy.deepcopy(params)))
        if method == "project/list":
            return [{"id": "fixture-project", "roots": [{"path": str(self.root)}]}]
        if method == "permissionProfile/list":
            return [{"id": "custom-readonly", "allowed": True}]
        if method == "thread/turns/list":
            return copy.deepcopy(self.threads[params["threadId"]]["turns"])
        if method != "thread/list":
            raise AssertionError(method)
        rows = [copy.deepcopy(row) for row in self.threads.values() if row["archived"] == params.get("archived", False)]
        if "ancestorThreadId" in params:
            def descendant(row):
                parent = row.get("parent")
                while parent:
                    if parent == params["ancestorThreadId"]:
                        return True
                    parent = self.threads[parent].get("parent")
                return False
            rows = [row for row in rows if descendant(row)]
        return rows

    def call(self, method, params):
        self.calls.append((method, copy.deepcopy(params)))
        if method in self.reject:
            raise sessions.NativeError(method, self.reject.pop(method))
        lose = self.lose.get(method, 0) > 0
        if lose:
            self.lose[method] -= 1
        if method == "thread/start":
            self.started += 1
            row = self.add("created-" + str(self.started))
            if self.no_settings_on_start:
                Path(row["path"]).write_text(json.dumps({"type": "session_meta", "payload": {"id": row["id"]}}) + "\n", encoding="utf-8")
        elif method == "thread/read":
            row = copy.deepcopy(self.threads[params["threadId"]])
            if not params.get("includeTurns"):
                row.pop("turns")
            return {"thread": row}
        elif method == "thread/resume":
            row = self.threads[params["threadId"]]
            row["status"] = {"type": "idle"}
            try:
                current = sessions.latest_settings(row["path"])
            except sessions.MissingSavedSettings:
                current = copy.deepcopy(SAVED)
            # The observed host resets omitted resume selections to defaults.
            # This fixture deliberately rejects the old preservation assumption.
            current["active_permission_profile"] = {"id": params["permissions"]} if "permissions" in params else None
            current["approval_policy"] = params.get("approvalPolicy", "on-request")
            current["approvals_reviewer"] = params.get("approvalsReviewer", "user")
            current["model"] = params.get("model", current["model"])
            current["reasoning_effort"] = params.get("config", {}).get("model_reasoning_effort")
            current.pop("effort", None)
            with Path(row["path"]).open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"type": "event_msg", "payload": {
                    "type": "thread_settings_applied", "thread_settings": current}}) + "\n")
            effective = sessions.inherited_settings({**current, "active_permission_profile": SAVED["active_permission_profile"]})["effective_sandbox"]
            return {"thread": copy.deepcopy(row), "cwd": str(self.root), "activePermissionProfile": current["active_permission_profile"],
                    "approvalPolicy": current["approval_policy"], "approvalsReviewer": current["approvals_reviewer"],
                    "sandbox": {"type": "dangerFullAccess"} if self.mismatch else effective,
                    "model": current["model"], "reasoningEffort": current["reasoning_effort"]}
        elif method == "thread/name/set":
            self.threads[params["threadId"]]["name"] = params["name"]
            return {}
        elif method == "collaborationMode/list":
            return {"data": [{"mode": "plan"}, {"mode": "default"}] if self.plan_supported else [{"mode": "default"}]}
        elif method == "thread/settings/update":
            if not self.setter:
                raise sessions.NativeError(method, {"code": -32601, "message": "Method not found"})
            self.save(self.threads[params["threadId"]], params["collaborationMode"])
            return {}
        elif method == "turn/start":
            if "collaborationMode" in params and not self.turn_mode:
                raise sessions.NativeError(method, {"code": -32602, "message": "Unsupported collaborationMode"})
            row = self.threads[params["threadId"]]
            if row["status"]["type"] == "notLoaded":
                raise sessions.NativeError(method, {"code": -32000, "message": "Thread not loaded"})
            self.sent += 1
            item = {"id": "user-" + str(self.sent), "clientId": params.get("clientUserMessageId") if self.echo_client_id else None,
                    "type": "userMessage", "content": copy.deepcopy(params["input"])}
            existing = row["status"]["type"] == "active" and row["turns"] and self.active_start_same_turn
            turn = row["turns"][-1] if existing else {"id": "turn-" + str(self.sent), "status": "completed", "items": []}
            if not lose or self.persist_lost_send:
                turn["items"].append(item)
                if not existing:
                    row["turns"].append(turn)
                if "collaborationMode" in params:
                    self.save(row, params["collaborationMode"])
                if self.on_turn:
                    self.on_turn(row, turn)
            if lose:
                raise HarnessError("Native send response was lost")
            return {"turn": copy.deepcopy(turn)}
        elif method in ("thread/archive", "thread/unarchive"):
            if self.archive_effective or method == "thread/unarchive":
                self.threads[params["threadId"]]["archived"] = method == "thread/archive"
            if lose:
                raise HarnessError("Native lifecycle response was lost")
            return {}
        else:
            raise AssertionError(method)
        if lose:
            raise HarnessError("Native creation response was lost")
        settings = sessions.inherited_settings(SAVED)
        return {"thread": copy.deepcopy(row), "cwd": str(self.root), "activePermissionProfile": {"id": settings["permissions"]},
                "approvalPolicy": settings["approvalPolicy"], "approvalsReviewer": settings["approvalsReviewer"],
                "sandbox": {"type": "dangerFullAccess"} if self.mismatch else settings["effective_sandbox"],
                "model": settings["model"], "reasoningEffort": settings["reasoning"]}

    def methods(self):
        return [method for method, _ in self.calls]


def receipt(root):
    return {"originator": "fixture-originator", "target": str(Path(root).resolve()), "project_id": "fixture-project",
            "settings": sessions.inherited_settings(SAVED), "title": "Unrestricted naming", "role": "Camel", "phase": "prepared"}


class SessionContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.native = NativeFixture(self.root)
        self.path = self.root / ".oasis/local/delivery.json"

    def test_creation_preserves_settings_once_without_resume_or_turn(self):
        row = receipt(self.root)
        actual = sessions.create_metadata(self.path, row, self.native)
        self.assertEqual(actual["phase"], "ready")
        self.assertEqual(self.native.methods().count("thread/start"), 1)
        self.assertNotIn("thread/resume", self.native.methods())
        self.assertNotIn("turn/start", self.native.methods())
        params = next(params for method, params in self.native.calls if method == "thread/start")
        self.assertEqual(params["permissions"], "custom-readonly")
        self.assertEqual(params["model"], "chosen-model")
        self.assertEqual(params["config"], {"model_reasoning_effort": "high"})

    def test_creation_response_loss_reuses_actual_id(self):
        row = receipt(self.root)
        self.native.lose["thread/start"] = 1
        with self.assertRaises(HarnessError):
            sessions.create_metadata(self.path, row, self.native)
        with self.assertRaises(HarnessError):
            sessions.create_metadata(self.path, read_json(self.path), self.native)
        recovered = sessions.resume(self.path, factory=self.native)
        self.assertEqual(recovered["thread_id"], "created-1")
        self.assertEqual(self.native.started, 1)

    def test_permission_mismatch_does_not_name_or_deliver(self):
        self.native.mismatch = True
        with self.assertRaises(HarnessError):
            sessions.create_metadata(self.path, receipt(self.root), self.native)
        self.assertNotIn("thread/name/set", self.native.methods())
        self.assertNotIn("turn/start", self.native.methods())
        with self.assertRaises(HarnessError):
            sessions.resume(self.path, factory=self.native)
        self.assertNotIn("thread/name/set", self.native.methods())
        self.native.mismatch = False
        self.assertEqual(sessions.resume(self.path, factory=self.native)["phase"], "ready")

    def test_title_is_convention_and_new_calf_has_no_native_calls(self):
        self.assertEqual(sessions.title_for("Camel", "한글 목표", {"name": "renamed"}), "camel_A_한글 목표")
        self.assertEqual(sessions.title_for("Developer", "direct work", {}), "Developer_direct work")
        actual = sessions.create(self.root, "Calf", None, apply=True, factory=self.native)
        self.assertEqual(actual["status"], "retired_role")
        self.assertEqual(self.native.calls, [])

    def test_direct_message_has_no_report_format_requirement_and_deduplicates(self):
        text = "Done — see the result."
        actual = sessions.send_once(self.path, "caller", text, self.native)
        self.assertEqual(actual["state"], "accepted")
        self.assertEqual(sessions.send_once(self.path, "caller", text, self.native)["turn_id"], actual["turn_id"])
        self.assertEqual(self.native.sent, 1)

    def test_lost_send_reconciles_client_id_and_never_replays(self):
        self.native.lose["turn/start"] = 1
        with self.assertRaises(HarnessError):
            sessions.send_once(self.path, "caller", "A result", self.native)
        actual = sessions.send_once(self.path, "caller", "A result", self.native)
        self.assertEqual(actual["state"], "accepted")
        self.assertEqual(self.native.sent, 1)

    def test_unobserved_send_keeps_uncertainty_without_replay(self):
        self.native.lose["turn/start"] = 1
        self.native.persist_lost_send = False
        with self.assertRaises(HarnessError):
            sessions.send_once(self.path, "caller", "A result", self.native)
        self.assertEqual(sessions.send_once(self.path, "caller", "A result", self.native)["state"], "uncertain")
        self.assertEqual(self.native.sent, 1)

    def test_active_input_lost_response_reconciles_inside_existing_turn(self):
        for echo_client_id in (True, False):
            self.native.add("caller", status="active")
            self.native.echo_client_id = echo_client_id
            self.native.threads["caller"]["turns"] = [{"id": "already-active", "status": "inProgress", "items": [
                {"id": "old-user-item", "type": "userMessage", "content": [{"type": "text", "text": "Owner request"}]}]}]
            path = self.root / f".oasis/local/active-{echo_client_id}.json"
            self.native.lose["turn/start"] = 1
            with self.assertRaises(HarnessError):
                sessions.send_once(path, "caller", "Camel completed", self.native)
            before = self.native.sent
            actual = sessions.send_once(path, "caller", "Camel completed", self.native)
            self.assertEqual(actual["state"], "accepted")
            self.assertEqual(actual["turn_id"], "already-active")
            self.assertEqual(self.native.sent, before)

    def test_definite_rejection_can_retry_same_action_without_policy_fallback(self):
        self.native.reject["turn/start"] = {"code": -32000, "message": "Permission denied"}
        with self.assertRaises(sessions.NativeError):
            sessions.send_once(self.path, "caller", "A result", self.native)
        self.assertEqual(read_json(self.path)["state"], "rejected")
        self.assertEqual(sessions.send_once(self.path, "caller", "A result", self.native)["state"], "accepted")
        self.assertEqual(self.native.sent, 1)

    def test_native_plan_sets_builtins_and_preserves_model_effort(self):
        actual = sessions.send_once(self.path, "caller", "Plan the task", self.native, planning=True)
        self.assertEqual(actual["plan_route"], "settings")
        params = next(params for method, params in self.native.calls if method == "turn/start")
        self.assertEqual(params["collaborationMode"], {"mode": "plan", "settings": {
            "model": "chosen-model", "reasoning_effort": "high", "developer_instructions": None}})
        self.assertNotIn("permissions", params)
        self.assertEqual(self.native.sent, 1)

    def test_native_plan_turn_route_and_manual_fallback_once(self):
        self.native.setter = False
        actual = sessions.send_once(self.path, "caller", "Plan", self.native, planning=True)
        self.assertEqual(actual["plan_route"], "turn")
        self.path.unlink()
        self.native.save(self.native.threads["caller"], {"mode": "default"})
        self.native.plan_supported = False
        first = sessions.send_once(self.path, "caller", "Plan", self.native, planning=True)
        second = sessions.send_once(self.path, "caller", "Plan", self.native, planning=True)
        self.assertEqual(first["state"], "manual_plan")
        self.assertIn("instruction", first)
        self.assertNotIn("instruction", second)
        self.assertEqual(self.native.sent, 1)
        self.native.save(self.native.threads["caller"], {"mode": "plan"})
        self.assertEqual(sessions.send_once(self.path, "caller", "Plan", self.native, planning=True)["state"], "accepted")
        self.assertEqual(self.native.sent, 2)

    def test_plan_permission_denial_is_not_manual_fallback(self):
        self.native.reject["thread/settings/update"] = {"code": -32000, "message": "Permission denied"}
        with self.assertRaises(sessions.NativeError):
            sessions.send_once(self.path, "caller", "Plan", self.native, planning=True)
        self.assertEqual(self.native.sent, 0)

    def test_cold_recipient_loads_once_with_current_selections(self):
        self.native.threads["caller"]["status"] = {"type": "notLoaded"}
        sessions.send_once(self.path, "caller", "Resume cold thread", self.native)
        self.assertEqual([params for method, params in self.native.calls if method == "thread/resume"],
                         [{"threadId": "caller", "excludeTurns": True, "permissions": "custom-readonly",
                           "approvalPolicy": "on-request", "approvalsReviewer": "user", "model": "chosen-model",
                           "config": {"model_reasoning_effort": "high"}}])
        sessions.send_once(self.path, "caller", "Resume cold thread", self.native)
        self.assertEqual(self.native.methods().count("thread/resume"), 1)

    def initial_thread(self):
        self.native.no_settings_on_start = True
        row = receipt(self.root)
        path = self.root / ".oasis/local/sessions/fixture-originator/receipt.json"
        sessions.create_metadata(path, row, self.native)
        return row, path

    def test_fresh_plan_uses_verified_creation_settings_without_resume(self):
        row, _ = self.initial_thread()
        with self.assertRaises(sessions.MissingSavedSettings):
            sessions.latest_settings(self.native.threads[row["thread_id"]]["path"])
        actual = sessions.send_once(self.path, row["thread_id"], "Plan the first task", self.native, planning=True)
        self.assertEqual(actual["state"], "accepted")
        self.assertNotIn("thread/resume", self.native.methods())
        params = next(params for method, params in self.native.calls if method == "turn/start")
        self.assertEqual(params["collaborationMode"]["settings"], {
            "model": "chosen-model", "reasoning_effort": "high", "developer_instructions": None})
        for key in ("permissions", "approvalPolicy", "approvalsReviewer", "sandboxPolicy"):
            self.assertNotIn(key, params)
        before = len(self.native.calls)
        sessions.send_once(self.path, row["thread_id"], "Plan the first task", self.native, planning=True)
        self.assertEqual(len(self.native.calls), before)

    def test_current_saved_model_effort_take_precedence_over_creation(self):
        row, _ = self.initial_thread()
        native = self.native.threads[row["thread_id"]]
        current = {**SAVED, "model": "owner-selected-now", "reasoning_effort": "max"}
        Path(native["path"]).write_text(json.dumps({"type": "turn_context", "payload": current}) + "\n", encoding="utf-8")
        sessions.send_once(self.path, row["thread_id"], "Plan", self.native, planning=True)
        params = next(params for method, params in self.native.calls if method == "turn/start")
        self.assertEqual(params["collaborationMode"]["settings"]["model"], "owner-selected-now")
        self.assertEqual(params["collaborationMode"]["settings"]["reasoning_effort"], "max")
        self.assertNotIn("thread/resume", self.native.methods())

    def test_malformed_or_unsupported_saved_settings_do_not_use_initial_fallback(self):
        row, _ = self.initial_thread()
        path = Path(self.native.threads[row["thread_id"]]["path"])
        payloads = ["{", json.dumps({"type": "turn_context", "payload": {}}),
                    json.dumps({"type": "turn_context", "payload": None}),
                    json.dumps({"type": "event_msg", "payload": {"type": "thread_settings_applied"}}),
                    json.dumps({"type": "turn_context", "payload": {**SAVED, "sandbox_policy": {"type": "unsupported"}}})]
        for payload in payloads:
            with self.subTest(payload=payload):
                path.write_text(payload + "\n", encoding="utf-8")
                with self.assertRaises((HarnessError, ValueError)):
                    sessions.send_once(self.path, row["thread_id"], "Plan", self.native, planning=True)
                self.assertEqual(path.read_text(encoding="utf-8"), payload + "\n")
        self.assertNotIn("thread/resume", self.native.methods())
        self.assertNotIn("thread/settings/update", self.native.methods())
        self.assertNotIn("turn/start", self.native.methods())

    def test_missing_settings_requires_matching_verified_initial_identity(self):
        row, metadata = self.initial_thread()
        captured = read_json(metadata)
        for delta in ({"creation_verified": False}, {"thread_id": "unrelated"}, {"project_id": "another-project"},
                      {"target": str(self.root / "another-root")}):
            with self.subTest(delta=delta):
                write_json(metadata, {**captured, **delta})
                with self.assertRaises(HarnessError):
                    sessions.send_once(self.path, row["thread_id"], "Plan", self.native, planning=True)
        self.assertNotIn("thread/resume", self.native.methods())
        self.assertNotIn("turn/start", self.native.methods())

    def test_cold_resume_preserves_latest_model_effort_and_permission_choices(self):
        current = {**SAVED, "model": "owner-current-model", "reasoning_effort": "max", "approval_policy": "never"}
        self.native.add("caller", status="notLoaded", saved=current)
        sessions.send_once(self.path, "caller", "Resume", self.native)
        options = next(params for method, params in self.native.calls if method == "thread/resume")
        self.assertEqual(options, {"threadId": "caller", "excludeTurns": True, "model": "owner-current-model",
                         "permissions": "custom-readonly", "approvalPolicy": "never", "approvalsReviewer": "user",
                         "config": {"model_reasoning_effort": "max"}})
        after = sessions.latest_settings(self.native.threads["caller"]["path"])
        self.assertEqual(sessions.inherited_settings(after), sessions.inherited_settings(current))
        self.assertNotIn("sandboxPolicy", options)

    def test_native_no_override_resume_reset_is_explicitly_modeled(self):
        current = {**SAVED, "reasoning_effort": "max", "approval_policy": "never"}
        self.native.add("caller", status="notLoaded", saved=current)
        response = self.native.call("thread/resume", {"threadId": "caller", "excludeTurns": True})
        self.assertEqual(response["model"], current["model"])
        self.assertIsNone(response["reasoningEffort"])
        self.assertIsNone(response["activePermissionProfile"])
        self.assertEqual(response["approvalPolicy"], "on-request")

    def test_cold_resume_mismatch_blocks_delivery_without_broadening_fallback(self):
        self.native.threads["caller"]["status"] = {"type": "notLoaded"}
        self.native.mismatch = True
        with self.assertRaises(HarnessError):
            sessions.send_once(self.path, "caller", "Resume", self.native)
        self.assertEqual(self.native.methods().count("thread/resume"), 1)
        self.assertNotIn("turn/start", self.native.methods())

    def test_paginated_reconcile_uses_full_turn_page(self):
        self.native.lose["turn/start"] = 1
        with self.assertRaises(HarnessError):
            sessions.send_once(self.path, "caller", "Result", self.native)
        original = self.native.call
        def paginated(method, params):
            value = original(method, params)
            if method == "thread/read" and params.get("includeTurns"):
                value["thread"].pop("turns", None)
            return value
        self.native.call = paginated
        self.assertEqual(sessions.send_once(self.path, "caller", "Result", self.native)["state"], "accepted")
        self.assertIn("thread/turns/list", self.native.methods())

    def test_saved_fields_and_current_disabled_profile(self):
        self.native.save(self.native.threads["caller"], {"mode": "plan"})
        self.assertEqual(sessions.latest_settings(self.native.threads["caller"]["path"])["collaboration_mode"]["mode"], "plan")
        current = {"active_permission_profile": {"id": ":danger-full-access"}, "permission_profile": {"type": "disabled"},
                   "approval_policy": "never", "approvals_reviewer": "user", "model": "chosen", "effort": "ultra"}
        self.assertEqual(sessions.inherited_settings(current)["reasoning"], "ultra")
        with self.assertRaises(HarnessError):
            sessions.inherited_settings({**current, "reasoning_effort": "low"})


if __name__ == "__main__":
    unittest.main()
