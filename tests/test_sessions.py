import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from oasis_harness.common import HarnessError, read_json, write_json
from oasis_harness.sessions import create_metadata, inherited_settings, latest_settings, resume, title_for


class MetadataFixture:
    def __init__(self, receipt):
        self.receipt = receipt
        self.started = 0
        self.lost = False
        self.name = None
        self.calls = []
        self.mismatch = False

    def __call__(self, originator): return self
    def __enter__(self): return self
    def __exit__(self, *_): pass

    def thread(self):
        return {"id":"fixture-thread", "name":self.name, "cwd":self.receipt["target"], "projectId":"fixture-project", "originator":self.receipt["originator"]}

    def pages(self, method, params):
        self.calls.append(method)
        return [self.thread()] if self.started else []

    def call(self, method, params):
        self.calls.append(method)
        if method == "thread/start":
            self.started += 1
            if self.lost:
                self.lost = False
                raise HarnessError("Lost creation response")
        if method == "thread/name/set":
            self.name = params["name"]
            return {}
        if method == "thread/read": return {"thread":self.thread()}
        settings = self.receipt["settings"]
        return {"thread":self.thread(), "cwd":self.receipt["target"], "activePermissionProfile":{"id": settings["permissions"]},
                "approvalPolicy":settings["approvalPolicy"], "approvalsReviewer":settings["approvalsReviewer"],
                "sandbox": {"type":"dangerFullAccess"} if self.mismatch else settings["effective_sandbox"],
                "model":settings["model"], "reasoningEffort":settings["reasoning"]}


def receipt(root):
    settings=inherited_settings({"active_permission_profile":{"id":"custom-readonly"},"sandbox_policy":{"type":"read-only"},"approval_policy":"on-request","approvals_reviewer":"user","model":"user-selected","reasoning_effort":"high"})
    return {"originator":"fixture-originator", "target":str(root.resolve()), "project_id":"fixture-project", "settings":settings, "title":"Oasis", "phase":"prepared", "source_readiness":{"profile":"unmanaged"}}


class SessionContracts(unittest.TestCase):
    def setUp(self):
        self.readiness=patch("oasis_harness.sessions.source_readiness",return_value={"profile":"unmanaged"}).start()
        self.addCleanup(patch.stopall)

    def test_changed_readiness_stops_before_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            row=receipt(Path(tmp));fake=MetadataFixture(row)
            self.readiness.return_value={"profile":"main-test","branch":"main","head":"changed"}
            with self.assertRaises(HarnessError):create_metadata(Path(tmp)/"receipt.json",row,fake)
            self.assertEqual(fake.started,0)

    def test_restricted_policy_survives_cold_resume_without_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            row=receipt(Path(tmp));fake=MetadataFixture(row);path=Path(tmp)/"receipt.json"
            result=create_metadata(path,row,fake)
            self.assertEqual(result["phase"],"ready")
            self.assertEqual(fake.started,1)
            self.assertFalse(result["first_turn_verified"])
            self.assertNotIn("turn/start",fake.calls)
            self.assertEqual(fake.calls.count("thread/resume"),2)

    def test_lost_creation_blocks_new_and_reconciles_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            row=receipt(Path(tmp));fake=MetadataFixture(row);fake.lost=True;path=Path(tmp)/"receipt.json"
            with self.assertRaises(HarnessError):create_metadata(path,row,fake)
            with self.assertRaises(HarnessError):create_metadata(path,read_json(path),fake)
            self.assertEqual(fake.started,1)
            self.assertEqual(resume(path,"actual request",fake)["phase"],"ready")
            self.assertEqual(fake.started,1)

    def test_policy_mismatch_never_falls_back_or_delivers(self):
        with tempfile.TemporaryDirectory() as tmp:
            row=receipt(Path(tmp));fake=MetadataFixture(row);fake.mismatch=True
            with self.assertRaises(HarnessError):create_metadata(Path(tmp)/"receipt.json",row,fake)
            self.assertNotIn("thread/name/set",fake.calls)
            self.assertNotIn("turn/start",fake.calls)

    def test_last_saved_settings_win(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"rollout.jsonl"
            rows=[{"type":"turn_context","payload":{"model":"old"}}, {"type":"event_msg","payload":{"type":"thread_settings_applied","thread_settings":{"model":"new"}}}]
            path.write_text("\n".join(json.dumps(r) for r in rows),encoding="utf-8")
            self.assertEqual(latest_settings(path)["model"],"new")

    def test_current_disabled_profile_requires_exact_saved_provenance(self):
        saved = {"active_permission_profile":{"id":":danger-full-access"},
                 "permission_profile":{"type":"disabled"}, "approval_policy":"never",
                 "approvals_reviewer":"user", "model":"chosen-model", "reasoning_effort":"high"}
        actual = inherited_settings(saved)
        self.assertEqual(actual["permissions"], ":danger-full-access")
        self.assertEqual(actual["effective_sandbox"], {"type":"dangerFullAccess"})
        self.assertEqual(actual["model"], "chosen-model")
        current_turn = {key:value for key,value in saved.items() if key != "reasoning_effort"}
        current_turn["effort"] = "ultra"
        self.assertEqual(inherited_settings(current_turn)["reasoning"], "ultra")
        with self.assertRaisesRegex(HarnessError, "reasoning fields disagree"):
            inherited_settings({**saved, "effort":"low"})
        for replacement in ({}, {"active_permission_profile":{"id":":workspace"}},
                            {"permission_profile":{"type":"disabled","unknown_constraint":True}},
                            {"permission_profile":{"type":"restricted"}},
                            {"sandbox_policy":{"type":"read-only"}}):
            value = {**saved, **replacement} if replacement else {k:v for k,v in saved.items() if k != "permission_profile"}
            with self.assertRaises(HarnessError):
                inherited_settings(value)
        with self.assertRaises(HarnessError):
            inherited_settings({"active_permission_profile":{"id":":danger-full-access"},
                                "sandbox_policy":{"type":"read-only"}})

    def test_naming_and_authority_routes(self):
        self.assertEqual(title_for("Camel","Inspect",{"name":"Cameleer"},[],[]),"Camel_A_Inspect")
        self.assertEqual(title_for("Camel","Inspect",{"name":"Cameleer"},[{"name":"Calf_A_Orphan"}],[]),"Camel_B_Inspect")
        self.assertEqual(title_for("Calf","Inspect",{"name":"Camel_AB_Bundle"},[],[]),"Calf_AB_Inspect")
        with self.assertRaises(HarnessError):title_for("Camel","Inspect",{"name":"Developer"},[],[])
        with self.assertRaises(HarnessError):title_for("Oasis",None,{},[],[{"phase":"creation_started"}])
        with self.assertRaises(HarnessError):inherited_settings({"sandbox_policy":{"type":"new-unsupported"}})
