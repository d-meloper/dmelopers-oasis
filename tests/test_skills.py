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
        from oasis_harness.installation import package_files
        self.root.mkdir()
        for name, data in package_files(PACKAGE).items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
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

    def test_project_catalog_reads_actual_customized_skill_and_reports_missing_or_invalid(self):
        path = self.root / ".agents/skills/oasis-camel/SKILL.md"
        original = path.read_text(encoding="utf-8")
        changed = original.replace("description: Investigate, implement and check an assigned task, coordinate its dependencies, and send completion directly to Cameleer.",
                                   "description: Work on this project's customized storage contract.")
        self.assertNotEqual(changed, original)
        path.write_text(changed, encoding="utf-8")
        missing = self.root / ".agents/skills/oasis-pioneer/SKILL.md"
        missing.unlink()
        invalid = self.root / ".agents/skills/oasis-review/SKILL.md"
        invalid.write_text("not valid skill metadata", encoding="utf-8")
        malformed = self.root / ".agents/skills/oasis-asset-pipeline/SKILL.md"
        malformed.write_bytes(b"\xff")
        result = {row["name"]: row for row in skills.list_skills(self.root)["skills"]}
        self.assertEqual(len(result), 24)
        self.assertEqual(result["oasis-camel"]["description"], "Work on this project's customized storage contract.")
        self.assertEqual(result["oasis-camel"]["files"]["SKILL.md"], file_hash(path))
        self.assertEqual(result["oasis-camel"]["file_status"], "present")
        self.assertEqual(result["oasis-pioneer"]["file_status"], "missing")
        self.assertFalse(result["oasis-pioneer"]["installed"])
        self.assertIsNone(result["oasis-pioneer"]["description"])
        self.assertEqual(result["oasis-review"]["file_status"], "invalid")
        self.assertTrue(result["oasis-review"]["installed"])
        self.assertIsNone(result["oasis-review"]["description"])
        self.assertEqual(result["oasis-asset-pipeline"]["file_status"], "invalid")
        self.assertEqual((PACKAGE / "seed/.agents/skills/oasis-camel/SKILL.md").read_text(encoding="utf-8"), original)

    def test_summary_cli_preserves_catalog_and_omits_resource_inventory(self):
        complete = skills.list_skills(self.root)
        command = [sys.executable, "-B", "-X", "utf8", str(PACKAGE / "oasis.py"),
                   "skills", "list", "--project", str(self.root), "--summary"]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertFalse(summary["discovery_verified"])
        self.assertEqual([(row["name"], row["description"], row["file_status"]) for row in summary["skills"]],
                         [(row["name"], row["description"], row["file_status"]) for row in complete["skills"]])
        self.assertTrue(all("files" not in row for row in summary["skills"]))
        self.assertTrue(all(row["files"] for row in complete["skills"]))

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

    def test_reference_body_and_heading_are_checked(self):
        path = self.root / ".agents/skills/oasis-camel/references/best-practices.md"
        original = path.read_text(encoding="utf-8")
        for extra in ("\n[missing](missing.md)\n", "\n[missing heading](../../../../ProjectGuide.md#missing-section)\n"):
            with self.subTest(extra=extra):
                path.write_text(original + extra, encoding="utf-8")
                with self.assertRaisesRegex(HarnessError, "Broken installed skill resource"):
                    skills.inspect_skill(path.parent.parent)
        path.write_text(original, encoding="utf-8")

    def test_markdown_fragments_unicode_duplicates_explicit_anchors_and_code_examples(self):
        files = {"guide (local).md": b"# Save\n\n# Save\n\n<a id='custom'></a>\n\n## \xed\x98\x84\xec\x9e\xac \xeb\xb3\xb5\xea\xb5\xac\n"}
        text = ("[duplicate](<../guide (local).md#save-1>)\n"
                "[unicode](<../guide (local).md#현재-복구>)\n"
                "[anchor](<../guide (local).md#custom>)\n"
                "`[example](missing.md)`\n\n```markdown\n[example](missing.md)\n# Phantom\n```\n")
        skills.validate_markdown_links("refs/tips.md", text, files.get)
        for fragment in ("absent", "phantom"):
            with self.subTest(fragment=fragment), self.assertRaisesRegex(HarnessError, "Missing Markdown heading"):
                skills.validate_markdown_links("refs/tips.md", "[bad](<../guide (local).md#" + fragment + ">)", files.get)
        with self.assertRaisesRegex(HarnessError, "escapes its project"):
            skills.validate_markdown_links("refs/tips.md", "[outside](../../outside.md)", files.get)
        reference = "[restore][Policy]\n\n[policy]: <../guide (local).md#save-1>\n"
        skills.validate_markdown_links("refs/tips.md", reference, files.get)
        with self.assertRaisesRegex(HarnessError, "Missing Markdown heading"):
            skills.validate_markdown_links("refs/tips.md", reference.replace("#save-1", "#absent"), files.get)

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

    def test_complete_sanitized_historical_inventory_is_retained_in_version_history(self):
        archived = read_json(PACKAGE / "docs/upgrade-index.json")["history"]["adaptation_inventory"]
        self.assertEqual(archived["package_version"], "1.2.0")
        self.assertEqual(archived["source_file"], "docs/adaptation-map.json")
        self.assertEqual(archived["source_sha256"], "44661ad3083e7e62b4a3575436d37d3c0d02a435c3f69ac756bbdda1e6bb18e8")
        inventory = archived["inventory"]
        # Pin the complete original data, not its former live destination layout.
        self.assertEqual(digest(inventory), "26cbf87c2ac15519b100ef92ecc14b3d2f74a28fc9f80f26b6ccb1de33855b13")
        self.assertEqual(inventory["source_skill_count"], 26)
        files = [item for skill in inventory["skills"] for item in skill["files"]]
        self.assertEqual(len(files), 69)
        self.assertEqual(len({item["source_file_id"] for item in files}), 69)
        for item in files:
            self.assertRegex(item["sha256"], r"^[0-9a-f]{64}$")
        serialized = json.dumps(inventory)
        self.assertNotIn("source_path", serialized)
        self.assertNotIn("C:\\", serialized)

    def test_evaluator_expectations_are_separate_from_installed_inputs(self):
        from tests.skill_evaluation_cases import DOMAIN_EXPECTATIONS, EVALUATION_EXPECTATIONS
        from oasis_harness.installation import package_files
        payload = package_files(PACKAGE)
        for name in skills.OPTIONAL_NAMES:
            skill = PACKAGE / "library" / name
            cases = DOMAIN_EXPECTATIONS[name]
            self.assertEqual({row["kind"] for row in cases}, {"positive", "negative", "ambiguous"})
            self.assertEqual(len({row["trigger"] for row in cases}), 3)
            self.assertFalse((skill / "capability.json").exists())
            model_input = payload[f".agents/skills/{name}/references/acceptance.md"].decode("utf-8")
            for row in cases:
                self.assertNotIn(row["expected"], model_input)
            skills.inspect_skill(skill)
        self.assertEqual(set(EVALUATION_EXPECTATIONS), {"worker", "no_lesson", "read_only", "integrator"})
        self.assertFalse(any("skill_evaluation_cases" in name for name in payload))


if __name__ == "__main__":
    unittest.main()
