import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from oasis_harness.common import HarnessError, digest, file_hash, read_json, write_json
from oasis_harness.common import clean_environment
from oasis_harness import skills

PACKAGE = Path(__file__).resolve().parents[1]


class SkillContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="oasis-skills-")
        self.root = Path(self.temp.name) / "project"
        shutil.copytree(PACKAGE / "seed", self.root)
        write_json(self.root / ".oasis/install-manifest.json", {"schema_version": 1, "package_version": "1", "managed": {}, "enabled_capabilities": []})

    def tearDown(self):
        self.temp.cleanup()

    def select(self, *names):
        path = self.root / ".oasis/project.json"
        value = read_json(path)
        value["capabilities"] = list(names)
        write_json(path, value)

    def test_core_identity_pin_and_profile_contract(self):
        self.assertEqual(digest(read_json(self.root / ".oasis/core.json")), skills.EXPECTED_CORE_DIGEST)
        for profile in ("unmanaged", "single-main", "main-test"):
            value = read_json(self.root / ".oasis/project.json")
            value["git"]["profile"] = profile
            self.assertEqual(skills.validate_project(value)["git"]["profile"], profile)
        value["git"]["profile"] = "branch-worktree"
        with self.assertRaises(HarnessError):
            skills.validate_project(value)

    def test_core_drift_and_nested_authority_override_blocked(self):
        value = read_json(self.root / ".oasis/core.json")
        value["routing"]["owner_relay"] = "automatic"
        write_json(self.root / ".oasis/core.json", value)
        with self.assertRaisesRegex(HarnessError, "core contract drift"):
            skills.check_core(self.root)
        project = read_json(self.root / ".oasis/project.json")
        project["extensions"] = {"nested": [{"approval_policy": "never"}]}
        with self.assertRaisesRegex(HarnessError, "Protected core key"):
            skills.validate_project(project)

    def test_optional_library_not_active_or_discovery_proof(self):
        result = skills.list_skills(self.root)
        self.assertEqual(len(result["skills"]), 25)
        self.assertFalse(result["discovery_verified"])
        optional = [row for row in result["skills"] if row["kind"] == "optional"]
        self.assertEqual(len(optional), 15)
        self.assertTrue(all(not row["selected"] and not row["installed"] for row in optional))
        self.assertEqual(skills.validate_skills(self.root)["semantic_review"], "not performed")

    def test_doctor_is_required_default_without_changing_core_roles(self):
        self.assertEqual(len(skills.CORE_NAMES), 8)
        self.assertNotIn("oasis-harness-doctor", skills.CORE_NAMES)
        result = skills.list_skills(self.root)
        doctor = next(row for row in result["skills"] if row["name"] == "oasis-harness-doctor")
        self.assertEqual(doctor["kind"], "default")
        self.assertTrue(doctor["selected"] and doctor["installed"])
        self.assertNotIn("oasis-harness-doctor", skills.OPTIONAL_NAMES)
        path = self.root / ".agents/skills/oasis-harness-doctor/SKILL.md"
        path.unlink()
        with self.assertRaisesRegex(HarnessError, "Missing regular SKILL.md"):
            skills.validate_skills(self.root)

    def test_pioneer_is_required_default_outside_protected_eight_roles(self):
        self.assertEqual(len(skills.DEFAULT_NAMES), 10)
        self.assertNotIn("oasis-pioneer", skills.CORE_NAMES)
        self.assertNotIn("oasis-pioneer", skills.OPTIONAL_NAMES)
        result = skills.list_skills(self.root)
        pioneer = next(row for row in result["skills"] if row["name"] == "oasis-pioneer")
        self.assertEqual(pioneer["kind"], "default")
        self.assertTrue(pioneer["selected"] and pioneer["installed"])
        path = self.root / ".agents/skills/oasis-pioneer/SKILL.md"
        path.unlink()
        with self.assertRaisesRegex(HarnessError, "Missing regular SKILL.md"):
            skills.validate_skills(self.root)

    def test_unselected_capability_cannot_activate(self):
        with self.assertRaisesRegex(HarnessError, "not selected"):
            skills.activate(self.root, ["oasis-review"])
        self.assertFalse((self.root / ".agents/skills/oasis-review").exists())

    def test_linked_project_refused_before_creating_lock_or_files(self):
        from oasis_harness import installation, knowledge
        from tests.test_knowledge import example
        self.select("oasis-review")
        before = (self.root / ".oasis/install-manifest.json").read_bytes()
        real_check = installation.is_reparse
        def linked_root(path):
            return Path(path).absolute() == self.root.absolute() or real_check(path)
        with patch.object(installation, "is_reparse", side_effect=linked_root):
            with self.assertRaisesRegex(HarnessError, "Linked installation root"):
                skills.activate(self.root, ["oasis-review"])
            with self.assertRaisesRegex(HarnessError, "Linked installation root"):
                knowledge.capture(self.root, example())
        self.assertEqual((self.root / ".oasis/install-manifest.json").read_bytes(), before)
        self.assertFalse((self.root / ".oasis/local/operations.lock").exists())
        self.assertFalse((self.root / ".agents/skills/oasis-review").exists())

    def test_baseline_bytes_survive_git_autocrlf_without_changing_product_policy(self):
        repository = Path(self.temp.name) / "autocrlf-fixture"
        repository.mkdir()
        environment = clean_environment({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        def git(*arguments):
            result = subprocess.run(["git", "-C", str(repository), *arguments], env=environment, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
            return result.stdout
        git("init", "--template=", "--initial-branch=main")
        git("config", "user.name", "Fixture")
        git("config", "user.email", "fixture@example.invalid")
        git("config", "core.autocrlf", "true")
        shutil.copyfile(PACKAGE / "seed/.gitattributes", repository / ".gitattributes")
        original = b"immutable\r\ntext-like baseline\n"
        relative = ".oasis/base/" + digest(original)
        baseline = repository / relative
        baseline.parent.mkdir(parents=True)
        baseline.write_bytes(original)
        (repository / "ordinary.txt").write_bytes(b"ordinary\r\n")
        git("add", "--", ".gitattributes", relative, "ordinary.txt")
        git("commit", "-m", "Fixture immutable baseline")
        self.assertEqual(git("cat-file", "blob", "HEAD:" + relative), original)
        self.assertEqual(git("cat-file", "blob", "HEAD:ordinary.txt"), b"ordinary\n")
        baseline.unlink()
        git("restore", "--", relative)
        self.assertEqual(baseline.read_bytes(), original)

    def test_activation_records_baseline_and_preserves_other_skill(self):
        local = self.root / ".agents/skills/local-skill"
        local.mkdir()
        (local / "SKILL.md").write_text("user owned", encoding="utf-8")
        self.select("oasis-review")
        result = skills.activate(self.root, ["oasis-review"])
        self.assertEqual(result["status"], "installed")
        self.assertEqual((local / "SKILL.md").read_text(), "user owned")
        manifest = read_json(self.root / ".oasis/install-manifest.json")
        key = ".agents/skills/oasis-review/SKILL.md"
        entry = manifest["managed"][key]
        self.assertEqual(entry["owner"], "capability:oasis-review")
        self.assertEqual(file_hash(self.root / key), entry["base_sha256"])
        self.assertEqual(file_hash(self.root / ".oasis/base" / entry["base_sha256"]), entry["base_sha256"])
        self.assertEqual(manifest["enabled_capabilities"], ["oasis-review"])

    def test_existing_skill_and_contending_lock_are_not_removed(self):
        self.select("oasis-review")
        target = self.root / ".agents/skills/oasis-review"
        target.mkdir()
        (target / "SKILL.md").write_text("local specialization", encoding="utf-8")
        with self.assertRaisesRegex(HarnessError, "Existing skill preserved"):
            skills.activate(self.root, ["oasis-review"])
        self.assertEqual((target / "SKILL.md").read_text(), "local specialization")
        lock = self.root / ".oasis/local/operations.lock"
        write_json(lock, {"token": "another-owner"})
        with self.assertRaisesRegex(HarnessError, "locked"):
            skills.activate(self.root, ["oasis-review"])
        self.assertEqual(read_json(lock)["token"], "another-owner")

    def test_broken_installed_resource_is_rejected(self):
        path = self.root / ".agents/skills/oasis-knowledge/SKILL.md"
        path.write_text(path.read_text() + "\n[missing](references/missing.md)\n", encoding="utf-8")
        with self.assertRaisesRegex(HarnessError, "Broken installed"):
            skills.validate_skills(self.root)

    def test_partial_failure_does_not_claim_complete_activation(self):
        self.select("oasis-review")
        real_inspect = skills.inspect_skill
        def failed_destination(path):
            if Path(path).resolve() == (self.root / ".agents/skills/oasis-review").resolve():
                raise HarnessError("fixture destination check failed")
            return real_inspect(path)
        with patch.object(skills, "inspect_skill", side_effect=failed_destination):
            with self.assertRaisesRegex(HarnessError, "incomplete"):
                skills.activate(self.root, ["oasis-review"])
        self.assertEqual(read_json(self.root / ".oasis/install-manifest.json")["enabled_capabilities"], [])
        self.assertTrue((self.root / ".agents/skills/oasis-review").exists())
        self.assertFalse((self.root / ".oasis/local/capability-activation.json").exists())

    def test_installed_runtime_resolves_library_without_seed(self):
        from oasis_harness import installation
        target = Path(self.temp.name) / "installed"
        target.mkdir()
        installation.apply(installation.plan(target, PACKAGE))
        runtime = target / ".oasis/runtime"
        core_root, library_root = skills.resource_roots(runtime)
        self.assertEqual(core_root, target / ".agents/skills")
        self.assertEqual(library_root, target / ".oasis/library")
        self.assertFalse((runtime / "seed").exists())
        self.assertTrue((core_root / "oasis-harness-doctor/references/workflow.md").is_file())
        result = subprocess.run([sys.executable, str(target / "tools/oasis.py"), "skills", "validate", "--project", str(target)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "structural_pass")
        project = read_json(target / ".oasis/project.json")
        project["capabilities"] = ["oasis-review"]
        write_json(target / ".oasis/project.json", project)
        result = subprocess.run([sys.executable, str(target / "tools/oasis.py"), "skills", "activate", "--project", str(target), "--skill", "oasis-review"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "installed")
        # Upgrade may refresh the inactive library, but never silently replace
        # the selected project's refined active skill with upstream bytes.
        active = target / ".agents/skills/oasis-review/SKILL.md"
        active.write_text(active.read_text(encoding="utf-8") + "\nProject-local reviewed refinement.\n", encoding="utf-8")
        before = active.read_bytes()
        upgrade = installation.plan(target, PACKAGE, upgrade=True)
        self.assertEqual(upgrade["conflicts"], [])
        installation.apply(upgrade)
        self.assertEqual(active.read_bytes(), before)
        self.assertIn("oasis-review", read_json(target / ".oasis/install-manifest.json")["enabled_capabilities"])
        from tests.test_knowledge import example
        case = Path(self.temp.name) / "case.json"
        write_json(case, example())
        result = subprocess.run([sys.executable, str(target / "tools/oasis.py"), "knowledge", "capture", "--project", str(target), "--case", str(case)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["adopted_rule"])

    def test_complete_sanitized_adaptation_inventory(self):
        inventory = read_json(PACKAGE / "docs/adaptation-map.json")
        self.assertEqual(inventory["source_skill_count"], 26)
        files = [item for skill in inventory["skills"] for item in skill["files"]]
        self.assertEqual(len(files), 69)
        self.assertEqual(len({item["source_file_id"] for item in files}), 69)
        for item in files:
            self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$")
            for destination in item["destinations"]:
                self.assertTrue((PACKAGE / destination).is_file(), destination)
        serialized = json.dumps(inventory)
        self.assertNotIn("source_path", serialized)
        self.assertNotIn("C:\\", serialized)

    def test_all_optional_workflows_have_distinct_evaluation_cases(self):
        for name in skills.OPTIONAL_NAMES:
            skill = PACKAGE / "library" / name
            value = read_json(skill / "capability.json")
            self.assertEqual(value["name"], name)
            self.assertEqual(value["execution"], "tool-guided")
            self.assertEqual({row["kind"] for row in value["scenarios"]}, {"positive", "negative", "ambiguous"})
            self.assertEqual(len({row["trigger"] for row in value["scenarios"]}), 3)
            skills.inspect_skill(skill)


if __name__ == "__main__":
    unittest.main()
