from pathlib import Path
import shutil
import tempfile
import unittest

from oasis_harness import doctor, installation, skills
from oasis_harness.common import HarnessError, file_hash, read_json, write_json

PACKAGE = Path(__file__).resolve().parents[1]


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="oasis-doctor-")
        self.base = Path(self.temp.name).resolve()
        self.package = self.base / "donor"
        for name in ("seed/.oasis", "library/oasis-review", "docs", "oasis_harness"):
            (self.package / name).mkdir(parents=True)
        for name in ("core.json", "project.json"):
            shutil.copyfile(PACKAGE / "seed/.oasis" / name, self.package / "seed/.oasis" / name)
        for name in skills.DEFAULT_NAMES:
            folder = self.package / "seed/.agents/skills" / name
            folder.mkdir(parents=True)
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
        project = read_json(self.root / ".oasis/project.json")
        project["capabilities"] = ["oasis-review"]
        write_json(self.root / ".oasis/project.json", project)
        skills.activate(self.root, ["oasis-review"], package=self.package)

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

    def test_selected_skill_refresh_preserves_ownership_and_local_knowledge(self):
        self.select_review()
        active = self.root / ".agents/skills/oasis-review/rule.txt"
        active.write_text("one\ntwo\nproject\n", encoding="utf-8")
        (self.package / "library/oasis-review/rule.txt").write_text("upstream\ntwo\nthree\n", encoding="utf-8")
        ordinary = installation.plan(self.root, self.package, upgrade=True)
        self.assertFalse(any(op["path"] == ".agents/skills/oasis-review/rule.txt" for op in ordinary["operations"]))
        installation.apply(doctor.plan(self.root, self.package), state_root=self.state)
        self.assertEqual(active.read_text(encoding="utf-8"), "upstream\ntwo\nproject\n")
        record = read_json(self.root / installation.MANIFEST)["managed"][".agents/skills/oasis-review/rule.txt"]
        self.assertEqual(record["owner"], "capability:oasis-review")
        self.assertEqual(record["base_sha256"], file_hash(self.package / "library/oasis-review/rule.txt"))
        self.assertEqual(doctor.audit(self.root, self.package)["status"], "current")

    def test_reports_default_and_selected_conflicts_together_without_apply(self):
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

    def test_incoming_core_change_is_blocked(self):
        core = read_json(self.package / "seed/.oasis/core.json")
        core["routing"]["owner_relay"] = "automatic"
        write_json(self.package / "seed/.oasis/core.json", core)
        before = self.hashes()
        result = doctor.audit(self.root, self.package)
        self.assertEqual({row["kind"] for row in result["issues"]}, {"core_migration"})
        with self.assertRaises(HarnessError):
            doctor.plan(self.root, self.package)
        self.assertEqual(self.hashes(), before)

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

    def test_new_defaults_install_into_an_older_eight_skill_adopter(self):
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
        self.assertEqual(len(skills.validate_skills(older)["skills"]), 10)

    def test_retired_selected_resources_preserve_specialization(self):
        for name in ("obsolete.txt", "specialized.txt"):
            (self.package / "library/oasis-review" / name).write_bytes(b"base")
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

    def test_selection_mismatch_is_a_pending_decision(self):
        project = read_json(self.root / ".oasis/project.json")
        project["capabilities"] = ["oasis-review"]
        write_json(self.root / ".oasis/project.json", project)
        before = self.hashes()
        report = doctor.audit(self.root, self.package)
        self.assertEqual(report["status"], "blocked")
        self.assertTrue(any(row["kind"] == "selection_mismatch" for row in report["issues"]))
        with self.assertRaises(HarnessError):
            doctor.plan(self.root, self.package)
        self.assertEqual(self.hashes(), before)


if __name__ == "__main__":
    unittest.main()
