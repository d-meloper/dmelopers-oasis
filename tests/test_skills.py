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
        for name in skills.OPTIONAL_NAMES:
            shutil.copytree(PACKAGE / "library" / name, self.root / ".agents/skills" / name)
        write_json(self.root / ".oasis/install-manifest.json", {"schema_version": 1, "package_version": "1", "managed": {}, "enabled_capabilities": []})

    def tearDown(self):
        self.temp.cleanup()

    def select(self, *names):
        path = self.root / ".oasis/project.json"
        value = read_json(path)
        value["capabilities"] = list(names)
        write_json(path, value)

    def test_descriptive_core_version_and_profile_input_contract(self):
        self.assertEqual(skills.check_core(self.root)["core_version"], "2.0.0")
        for profile in ("unmanaged", "single-main", "main-test"):
            value = read_json(self.root / ".oasis/project.json")
            value["git"]["profile"] = profile
            self.assertEqual(skills.validate_project(value)["git"]["profile"], profile)
        value["git"]["profile"] = "branch-worktree"
        with self.assertRaises(HarnessError):
            skills.validate_project(value)

    def test_core_and_project_extensions_are_not_behavior_seals(self):
        value = read_json(self.root / ".oasis/core.json")
        value["project_notes"] = "Use the project's native workflow adapter"
        write_json(self.root / ".oasis/core.json", value)
        self.assertEqual(skills.check_core(self.root)["core_version"], "2.0.0")
        project = read_json(self.root / ".oasis/project.json")
        project["extensions"] = {"nested": [{"approval_policy": "never", "roles": {"reviewer": "local"}}]}
        project["adapters"] = {"native": {"model": "existing", "permissions": "inherit"}}
        self.assertEqual(skills.validate_project(project), project)
        for invalid in ({}, [], {"schema_version": True, "core_version": "2.0.0"},
                        {"schema_version": 1, "core_version": []}):
            with self.subTest(core=invalid), self.assertRaises(HarnessError):
                skills.validate_core(invalid)
        self.assertEqual(skills.validate_core({"schema_version": 1, "core_version": "1.0.0"})["core_version"], "1.0.0")

    def test_all_twenty_four_skills_active_without_claiming_native_discovery(self):
        result = skills.list_skills(self.root)
        self.assertEqual(len(result["skills"]), 24)
        self.assertFalse(result["discovery_verified"])
        optional = [row for row in result["skills"] if row["kind"] == "capability"]
        self.assertEqual(len(optional), 15)
        self.assertTrue(all(row["selected"] and row["installed"] for row in optional))
        self.assertEqual(skills.validate_skills(self.root)["semantic_review"], "not performed")

    def test_doctor_is_required_default(self):
        self.assertEqual(len(skills.CORE_NAMES), 7)
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

    def test_pioneer_is_required_default_and_calf_is_retired(self):
        self.assertEqual(len(skills.DEFAULT_NAMES), 9)
        self.assertNotIn("oasis-calf", skills.DEFAULT_NAMES)
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
                skills.validate_skills(self.root)
            with self.assertRaisesRegex(HarnessError, "Linked installation root"):
                knowledge.capture(self.root, example())
        self.assertEqual((self.root / ".oasis/install-manifest.json").read_bytes(), before)
        self.assertFalse((self.root / ".oasis/local/operations.lock").exists())
        self.assertTrue((self.root / ".agents/skills/oasis-review").is_dir())

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

    def test_broken_installed_resource_is_rejected(self):
        path = self.root / ".agents/skills/oasis-knowledge/SKILL.md"
        path.write_text(path.read_text() + "\n[missing](references/missing.md)\n", encoding="utf-8")
        with self.assertRaisesRegex(HarnessError, "Broken installed"):
            skills.validate_skills(self.root)

    def test_installed_runtime_resolves_library_without_seed(self):
        from oasis_harness import installation
        target = Path(self.temp.name) / "installed"
        target.mkdir()
        installation.apply(installation.plan(target, PACKAGE))
        runtime = target / ".oasis/runtime"
        core_root, library_root = skills.resource_roots(runtime)
        self.assertEqual(core_root, target / ".agents/skills")
        self.assertEqual(library_root, target / ".agents/skills")
        self.assertFalse((runtime / "seed").exists())
        self.assertTrue((core_root / "oasis-harness-doctor/references/best-practices.md").is_file())
        result = subprocess.run([sys.executable, "-B", "-X", "utf8", str(target / "tools/oasis.py"), "skills", "validate", "--project", str(target)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "structural_pass")
        active = target / ".agents/skills/oasis-review/SKILL.md"
        self.assertTrue(active.is_file())
        active.write_bytes(active.read_bytes() + b"\nProject-local reviewed refinement.\n")
        before = active.read_bytes()
        upgrade = installation.plan(target, PACKAGE, upgrade=True)
        self.assertEqual(upgrade["conflicts"], [])
        installation.apply(upgrade)
        self.assertEqual(active.read_bytes(), before)
        self.assertIn("oasis-review", read_json(target / installation.MANIFEST)["enabled_capabilities"])
        from tests.test_knowledge import example
        case = Path(self.temp.name) / "case.json"
        write_json(case, example())
        result = subprocess.run([sys.executable, "-B", "-X", "utf8", str(target / "tools/oasis.py"), "knowledge", "capture", "--project", str(target), "--case", str(case)], capture_output=True, text=True, encoding="utf-8")
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
