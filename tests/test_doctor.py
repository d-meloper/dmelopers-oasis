from pathlib import Path
import shutil
import tempfile
import unittest

from oasis_harness import doctor, installation, skills
from oasis_harness.common import HarnessError, file_hash, read_json, write_json

PACKAGE = Path(__file__).resolve().parents[1]


class UpgradeGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="oasis-deltas-")
        self.addCleanup(self.temp.cleanup)
        self.package = Path(self.temp.name)
        (self.package / "docs").mkdir()
        self.index = self.package / "docs/upgrade-index.json"
        self.area = {"name":"Scoped fixture","paths":["AGENTS.md"],"change":"Fixture delta",
                     "apply":"Merge at authorized handoff","checks":["Scoped check"]}
        self.data = {"schema_version":1,"releases":[
            {"version":"1.0.1","previous":"1.0.0","summary":["Guide change"],"areas":[self.area],"source_only":[]},
            {"version":"1.0.2","previous":"1.0.1","summary":["Artwork change"],"areas":[],"source_only":["No adopter changes"]}]}
        write_json(self.index,self.data)

    def differences(self, *names):
        return [{"path":name,"upstream_changed":True,"local_changed":name=="AGENTS.md"} for name in names]

    def test_skipped_versions_select_only_actual_areas_and_keep_local_review(self):
        result=doctor.upgrade_guidance(self.package,"1.0.0","1.0.2",self.differences("AGENTS.md",".oasis/runtime/oasis_harness/__init__.py"))
        self.assertTrue(result["chain_complete"])
        self.assertEqual([r["version"] for r in result["releases"]],["1.0.1","1.0.2"])
        self.assertEqual(result["affected_areas"][0]["actual_paths"],["AGENTS.md"])
        self.assertEqual(result["unmapped_paths"],[])
        self.assertEqual(result["local_review_paths"],["AGENTS.md"])
        self.assertTrue(result["advisory_only"])

    def test_source_only_patch_needs_no_adopter_area(self):
        result=doctor.upgrade_guidance(self.package,"1.0.1","1.0.2",self.differences(".oasis/runtime/oasis_harness/__init__.py"))
        self.assertTrue(result["chain_complete"])
        self.assertEqual(result["affected_areas"],[])
        self.assertEqual(result["releases"][0]["source_only"],["No adopter changes"])

    def test_repeated_version_labels_from_explicit_reset_are_conservative(self):
        reset={**self.data["releases"][0],"previous":"1.0.2"}
        self.data["releases"].extend([reset,{**self.data["releases"][1],"previous":"1.0.1"}])
        write_json(self.index,self.data)
        ambiguous=doctor.upgrade_guidance(self.package,"1.0.1","1.0.2",self.differences("AGENTS.md"))
        self.assertFalse(ambiguous["chain_complete"])
        self.assertIn("Repeated installed version",ambiguous["reason"])
        first=doctor.upgrade_guidance(self.package,"1.0.0","1.0.2",self.differences("AGENTS.md"))
        self.assertTrue(first["chain_complete"])
        self.assertEqual(len(first["releases"]),4)

    def test_unknown_changed_paths_and_same_version_bytes_do_not_disappear(self):
        result=doctor.upgrade_guidance(self.package,"1.0.0","1.0.2",self.differences("new-unmapped.txt"))
        self.assertEqual(result["unmapped_paths"],["new-unmapped.txt"])
        result=doctor.upgrade_guidance(self.package,"1.0.2","1.0.2",self.differences("AGENTS.md"))
        self.assertFalse(result["chain_complete"])
        self.assertEqual(result["unmapped_paths"],["AGENTS.md"])

    def test_missing_malformed_or_cyclic_metadata_falls_back_to_complete_diff(self):
        for data in ([],{"schema_version":2,"releases":[]},
                     {"schema_version":1,"releases":[{**self.data["releases"][1],"previous":"1.0.2"}]},
                     {"schema_version":1,"releases":[{**self.data["releases"][1],"areas":[None]}]}):
            write_json(self.index,data)
            result=doctor.upgrade_guidance(self.package,"1.0.0","1.0.2",self.differences("AGENTS.md"))
            self.assertFalse(result["chain_complete"])
            self.assertEqual(result["unmapped_paths"],["AGENTS.md"])
        self.index.unlink()
        self.assertFalse(doctor.upgrade_guidance(self.package,"1.0.0","1.0.2",[])["chain_complete"])


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="oasis-doctor-")
        self.base = Path(self.temp.name).resolve()
        self.package = self.base / "donor"
        for name in ("seed/.oasis", "library/oasis-review", "docs", "oasis_harness"):
            (self.package / name).mkdir(parents=True)
        for name in ("core.json", "project.json"):
            shutil.copyfile(PACKAGE / "seed/.oasis" / name, self.package / "seed/.oasis" / name)
        for name in skills.ALL_NAMES:
            folder = (self.package / "library" if name in skills.OPTIONAL_NAMES else self.package / "seed/.agents/skills") / name
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "SKILL.md").write_text(f"---\nname: {name}\ndescription: Neutral disposable lifecycle fixture for owned resource updates.\n---\n", encoding="utf-8")
        (self.package / "seed/AGENTS.md").write_text("one\ntwo\nthree\n", encoding="utf-8")
        (self.package / "seed/.gitignore").write_text("/.oasis/local/\n", encoding="utf-8")
        (self.package / "oasis_harness/__init__.py").write_text('__version__ = "1.0.0"\n', encoding="utf-8")
        (self.package / "docs/sessions.md").write_text("old manual\n", encoding="utf-8")
        (self.package / "library/oasis-review/SKILL.md").write_text("---\nname: oasis-review\ndescription: Neutral selected capability for disposable upgrade lifecycle fixtures.\n---\n", encoding="utf-8")
        (self.package / "library/oasis-review/rule.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
        self.root = self.base / "project 한글 😀"
        self.root.mkdir()
        self.state = self.base / "journals"
        installation.apply(installation.plan(self.root, self.package), state_root=self.state)

    def tearDown(self):
        self.assertTrue(self.base.is_relative_to(Path(tempfile.gettempdir()).resolve()))
        self.assertTrue(self.base.name.startswith("oasis-doctor-"))
        self.temp.cleanup()

    def select_review(self):
        self.assertTrue((self.root / ".agents/skills/oasis-review/SKILL.md").is_file())

    def hashes(self):
        return {p.relative_to(self.root).as_posix(): file_hash(p) for p in self.root.rglob("*") if p.is_file()}

    def test_current_audit_has_no_effect_and_does_not_claim_remote_or_semantics(self):
        before = self.hashes()
        result = doctor.audit(self.root, self.package)
        self.assertEqual(result["status"], "current")
        self.assertEqual([row["path"] for row in result["differences"]], [".oasis/project.json"])
        self.assertTrue(result["differences"][0]["local_changed"])
        self.assertFalse(result["differences"][0]["upstream_changed"])
        self.assertEqual(read_json(self.root / ".oasis/project.json")["extensions"]["workflow"]["mode"], "pioneer")
        self.assertFalse(result["remote_verified"] or result["applied"])
        self.assertEqual(result["semantic_review"], "not performed")
        self.assertEqual(self.hashes(), before)
        self.assertEqual(doctor.plan(self.root, self.package)["operations"], [])

    def test_same_version_updated_bytes_merge_without_touching_user_state(self):
        (self.root / "AGENTS.md").write_text("one\ntwo\nproject\n", encoding="utf-8")
        (self.package / "seed/AGENTS.md").write_text("upstream\ntwo\nthree\n", encoding="utf-8")
        settings = self.root / ".codex/config.toml"
        settings.parent.mkdir()
        settings.write_bytes(b"user-settings\n")
        local = self.root / ".oasis/local/evidence.json"
        local.parent.mkdir(exist_ok=True)
        local.write_bytes(b"private-evidence\n")
        before = self.hashes()
        report = doctor.audit(self.root, self.package)
        self.assertEqual(report["status"], "outdated")
        self.assertEqual(report["installed_version"], report["incoming_version"])
        self.assertEqual(self.hashes(), before)
        installation.apply(doctor.plan(self.root, self.package), state_root=self.state)
        self.assertEqual((self.root / "AGENTS.md").read_text(encoding="utf-8"), "upstream\ntwo\nproject\n")
        self.assertEqual(settings.read_bytes(), b"user-settings\n")
        self.assertEqual(local.read_bytes(), b"private-evidence\n")
        self.assertEqual(doctor.audit(self.root, self.package)["status"], "current")

    def test_active_skill_refresh_preserves_ownership_and_local_knowledge(self):
        self.select_review()
        active = self.root / ".agents/skills/oasis-review/rule.txt"
        active.write_text("one\ntwo\nproject\n", encoding="utf-8")
        (self.package / "library/oasis-review/rule.txt").write_text("upstream\ntwo\nthree\n", encoding="utf-8")
        ordinary = installation.plan(self.root, self.package, upgrade=True)
        self.assertTrue(any(op["path"] == ".agents/skills/oasis-review/rule.txt" for op in ordinary["operations"]))
        installation.apply(doctor.plan(self.root, self.package), state_root=self.state)
        self.assertEqual(active.read_text(encoding="utf-8"), "upstream\ntwo\nproject\n")
        record = read_json(self.root / installation.MANIFEST)["managed"][".agents/skills/oasis-review/rule.txt"]
        self.assertEqual(record["owner"], "capability:oasis-review")
        self.assertEqual(record["base_sha256"], file_hash(self.package / "library/oasis-review/rule.txt"))
        self.assertEqual(doctor.audit(self.root, self.package)["status"], "current")

    def test_doctor_releases_project_knowledge_and_never_readopts_later_templates(self):
        from unittest.mock import patch
        for relative in installation.PROJECT_KNOWLEDGE_PATHS:
            source = self.package / "seed" / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(b"Original template knowledge\n")
        with patch.object(installation, "PROJECT_KNOWLEDGE_PATHS", frozenset()):
            installation.apply(installation.plan(self.root, self.package, upgrade=True), state_root=self.state)
        canonical = self.root / "BestPractice/README.md"
        canonical.write_bytes(b"Project's canonical policy, including its own skill system.\n")
        before = canonical.read_bytes()
        report = doctor.audit(self.root, self.package)
        self.assertEqual(report["status"], "outdated")
        value = doctor.plan(self.root, self.package)
        self.assertEqual(set(value["retained"]), set(installation.PROJECT_KNOWLEDGE_PATHS))
        self.assertFalse(any(op["path"] in installation.PROJECT_KNOWLEDGE_PATHS for op in value["operations"]))
        installation.apply(value, state_root=self.state)
        for relative in installation.PROJECT_KNOWLEDGE_PATHS:
            (self.package / "seed" / relative).write_bytes(b"Later donor policy\n")
        self.assertEqual(doctor.audit(self.root, self.package)["status"], "current")
        self.assertEqual(doctor.plan(self.root, self.package)["operations"], [])
        self.assertEqual(canonical.read_bytes(), before)
        self.assertTrue(installation.PROJECT_KNOWLEDGE_PATHS.isdisjoint(
            read_json(self.root / installation.MANIFEST)["managed"]))

    def test_reports_role_and_capability_conflicts_together_without_apply(self):
        self.select_review()
        (self.root / "AGENTS.md").write_text("local\ntwo\nthree\n", encoding="utf-8")
        (self.package / "seed/AGENTS.md").write_text("upstream\ntwo\nthree\n", encoding="utf-8")
        (self.root / ".agents/skills/oasis-review/rule.txt").write_text("local\ntwo\nthree\n", encoding="utf-8")
        (self.package / "library/oasis-review/rule.txt").write_text("upstream\ntwo\nthree\n", encoding="utf-8")
        before = self.hashes()
        report = doctor.audit(self.root, self.package)
        self.assertEqual(report["status"], "blocked")
        self.assertGreaterEqual(len(report["conflicts"]), 2)
        with self.assertRaisesRegex(HarnessError, "Doctor plan blocked"):
            doctor.plan(self.root, self.package)
        self.assertEqual(self.hashes(), before)

    def test_missing_file_and_corrupt_base_require_decisions(self):
        (self.root / "AGENTS.md").unlink()
        record = read_json(self.root / installation.MANIFEST)["managed"][".oasis/manual/sessions.md"]
        (self.root / ".oasis/base" / record["base_sha256"]).write_bytes(b"corrupt")
        before = self.hashes()
        report = doctor.audit(self.root, self.package)
        self.assertEqual(report["status"], "blocked")
        self.assertTrue(any(row["path"] == "AGENTS.md" and row["missing"] for row in report["differences"]))
        self.assertGreaterEqual(len(report["conflicts"]), 2)
        with self.assertRaises(HarnessError):
            doctor.plan(self.root, self.package)
        self.assertEqual(self.hashes(), before)

    def test_incoming_core_bytes_are_reviewed_without_a_hash_seal(self):
        core = read_json(self.package / "seed/.oasis/core.json")
        core["project_notes"] = "Native task links use actual chat IDs"
        write_json(self.package / "seed/.oasis/core.json", core)
        before = self.hashes()
        result = doctor.audit(self.root, self.package)
        self.assertEqual(result["status"], "outdated")
        self.assertEqual(result["issues"], [])
        self.assertTrue(any(op["path"] == ".oasis/core.json" for op in doctor.plan(self.root, self.package)["operations"]))
        self.assertEqual(self.hashes(), before)
        installation.apply(doctor.plan(self.root, self.package), state_root=self.state)
        self.assertEqual(read_json(self.root / ".oasis/core.json"), core)

    def test_core_one_to_two_upgrade_waits_on_real_task_links_without_blocking_on_version(self):
        legacy = self.base / "legacy-core-one"
        shutil.copytree(self.package, legacy)
        write_json(legacy / "seed/.oasis/core.json", {"schema_version": 1, "core_version": "1.0.0"})
        calf = legacy / "seed/.agents/skills/oasis-calf"
        calf.mkdir()
        (calf / "SKILL.md").write_bytes(b"---\nname: oasis-calf\ndescription: Legacy fixture.\n---\nLegacy instructions.\n")
        root = self.base / "legacy-project"
        root.mkdir()
        installation.apply(installation.plan(root, legacy), state_root=self.base / "legacy-journals")
        task_path = root / ".oasis/local/tasks/state.json"
        task = {"id": "legacy-task", "camel_thread_id": "actual-fixture-chat-id", "cameleer_thread_id": "fixture-manager-id",
                "goal": "Finish old work", "phase": "running", "location": str(root), "result": "", "checks": ""}
        write_json(task_path, {"schema_version": 1, "tasks": [task], "dependencies": []})
        report = doctor.audit(root, self.package)
        self.assertEqual(report["status"], "waiting")
        self.assertEqual(report["issues"], [])
        value = doctor.plan(root, self.package)
        self.assertEqual(value["operations"], [])
        with self.assertRaisesRegex(HarnessError, "waiting for unfinished"):
            installation.apply(value, state_root=self.base / "legacy-journals")
        task["phase"] = "completed"
        write_json(task_path, {"schema_version": 1, "tasks": [task], "dependencies": []})
        self.assertEqual(doctor.audit(root, self.package)["status"], "outdated")
        installation.apply(doctor.plan(root, self.package), state_root=self.base / "legacy-journals")
        self.assertEqual(read_json(root / ".oasis/core.json")["core_version"], "2.0.0")
        self.assertFalse((root / ".agents/skills/oasis-calf").exists())

    def test_private_payload_refuses_before_doctor_planning(self):
        private = self.package / "seed/.oasis/local/settings.json"
        private.parent.mkdir()
        private.write_bytes(b"private")
        before = self.hashes()
        for operation in (doctor.audit, doctor.plan):
            with self.assertRaisesRegex(HarnessError, "Protected installation path"):
                operation(self.root, self.package)
        self.assertEqual(self.hashes(), before)

    def test_self_installation_and_unowned_target_are_refused(self):
        with self.assertRaisesRegex(HarnessError, "self-installation"):
            doctor.audit(self.package, self.package)
        unowned = self.base / "unowned"
        unowned.mkdir()
        with self.assertRaisesRegex(HarnessError, "No installed manifest"):
            doctor.plan(unowned, self.package)
        self.assertEqual(list(unowned.iterdir()), [])

    def test_new_defaults_install_into_an_older_adopter(self):
        resource = self.package / "seed/.agents/skills/oasis-harness-doctor/SKILL.md"
        content = resource.read_bytes()
        resource.unlink()
        pioneer = self.package / "seed/.agents/skills/oasis-pioneer/SKILL.md"
        pioneer_content = pioneer.read_bytes()
        pioneer.unlink()
        older = self.base / "older-adopter"
        older.mkdir()
        installation.apply(installation.plan(older, self.package), state_root=self.base / "older-journals")
        resource.write_bytes(content)
        pioneer.write_bytes(pioneer_content)
        report = doctor.audit(older, self.package)
        self.assertEqual(report["status"], "outdated")
        self.assertTrue(any(row["path"].endswith("oasis-harness-doctor/SKILL.md") and row["new_upstream_file"] for row in report["differences"]))
        installation.apply(doctor.plan(older, self.package), state_root=self.base / "older-journals")
        self.assertEqual((older / ".agents/skills/oasis-harness-doctor/SKILL.md").read_bytes(), content)
        self.assertEqual((older / ".agents/skills/oasis-pioneer/SKILL.md").read_bytes(), pioneer_content)
        self.assertEqual(len(skills.validate_skills(older)["skills"]), 24)

    def test_retired_active_resources_preserve_specialization(self):
        for name in ("obsolete.txt", "specialized.txt"):
            (self.package / "library/oasis-review" / name).write_bytes(b"base")
        installation.apply(doctor.plan(self.root, self.package), state_root=self.state)
        self.select_review()
        active = self.root / ".agents/skills/oasis-review"
        (active / "specialized.txt").write_bytes(b"project knowledge")
        for name in ("obsolete.txt", "specialized.txt"):
            (self.package / "library/oasis-review" / name).unlink()
        value = doctor.plan(self.root, self.package)
        self.assertIn(".agents/skills/oasis-review/specialized.txt", value["retained"])
        installation.apply(value, state_root=self.state)
        self.assertFalse((active / "obsolete.txt").exists())
        self.assertEqual((active / "specialized.txt").read_bytes(), b"project knowledge")
        self.assertIn(".agents/skills/oasis-review/specialized.txt", read_json(self.root / installation.MANIFEST)["retained_specializations"])

    def test_legacy_capability_subset_does_not_gate_active_skill_updates(self):
        project = read_json(self.root / ".oasis/project.json")
        project["capabilities"] = ["oasis-review"]
        write_json(self.root / ".oasis/project.json", project)
        before = self.hashes()
        report = doctor.audit(self.root, self.package)
        self.assertEqual(report["status"], "current")
        self.assertEqual(report["issues"], [])
        self.assertEqual(report["capabilities_refreshed"], list(skills.OPTIONAL_NAMES))
        self.assertEqual(len(skills.validate_skills(self.root)["skills"]), 24)
        self.assertEqual(self.hashes(), before)


if __name__ == "__main__":
    unittest.main()
