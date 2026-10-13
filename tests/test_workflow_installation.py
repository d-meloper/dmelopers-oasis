"""Mode selection changes owned project bytes, never chats or donor bases."""
import argparse
import json
from pathlib import Path
import tempfile
import unittest

from oasis_harness import installation, skills
from oasis_harness.common import HarnessError, digest, read_json, write_json


PACKAGE = Path(__file__).resolve().parents[1]


class WorkflowInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="oasis-mode-install-")
        self.root = Path(self.temp.name) / "프로젝트 中文 😀"
        self.root.mkdir()
        self.journals = Path(self.temp.name) / "journals"

    def tearDown(self):
        self.temp.cleanup()

    def install(self, **kwargs):
        plan = installation.plan(self.root, PACKAGE, **kwargs)
        self.assertEqual(plan["conflicts"], [])
        installation.apply(plan, state_root=self.journals)
        return plan

    def test_empty_defaults_pioneer_with_original_neutral_base_and_no_native_side_effects(self):
        plan = self.install()
        self.assertEqual(plan["workflow"]["mode"], "pioneer")
        self.assertTrue(plan["workflow"]["initialization_required"])
        self.assertEqual(plan["workflow"]["required_roles"], ["Pioneer"])
        project = read_json(self.root / ".oasis/project.json")
        self.assertEqual(project["extensions"]["workflow"]["mode"], "pioneer")
        original = (PACKAGE / "seed/.oasis/project.json").read_bytes()
        record = read_json(self.root / installation.MANIFEST)["managed"][".oasis/project.json"]
        self.assertEqual(record["base_sha256"], digest(original))
        self.assertEqual((self.root / ".oasis/base" / record["base_sha256"]).read_bytes(), original)
        self.assertEqual(read_json(PACKAGE / "seed/.oasis/project.json")["extensions"], {})
        self.assertFalse((self.root / ".git").exists())
        self.assertFalse((self.root / ".oasis/local/workflows").exists())
        repeat = installation.plan(self.root, PACKAGE)
        self.assertEqual(repeat["workflow"]["mode"], "pioneer")
        self.assertFalse(repeat["workflow"]["initialization_required"])
        self.assertEqual(repeat["operations"], [])

    def test_setup_only_is_empty_but_application_skeleton_and_data_are_existing(self):
        for name in (".git", ".vscode", "docs"):
            (self.root / name).mkdir()
        (self.root / ".git/config").write_text("existing Git setup", encoding="utf-8")
        (self.root / ".vscode/settings.json").write_text("{}", encoding="utf-8")
        (self.root / "LICENSE").write_text("Owner product license", encoding="utf-8")
        (self.root / "docs/design.md").write_text("Desired application", encoding="utf-8")
        (self.root / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
        self.assertEqual(installation.classify_initial_workflow(self.root)["mode"], "pioneer")
        (self.root / "src").mkdir()
        (self.root / "src/main.py").write_text("pass\n", encoding="utf-8")
        classification = installation.classify_initial_workflow(self.root)
        self.assertEqual(classification["mode"], "oasis")
        self.assertEqual(classification["product_material"], ["src/main.py"])
        (self.root / "src/main.py").unlink()
        (self.root / "records.csv").write_text("id,value\n", encoding="utf-8")
        self.assertEqual(installation.classify_initial_workflow(self.root)["mode"], "oasis")

    def test_code_with_a_guide_name_is_existing_and_unreadable_material_is_not_empty(self):
        (self.root / "README.py").write_text("pass\n", encoding="utf-8")
        self.assertEqual(installation.classify_initial_workflow(self.root)["mode"], "oasis")
        from unittest.mock import patch
        def unreadable(*args, **kwargs):
            kwargs["onerror"](PermissionError("fixture directory denied"))
            yield
        with patch.object(installation.os, "walk", side_effect=unreadable):
            with self.assertRaisesRegex(HarnessError, "Unreadable project material"):
                installation.classify_initial_workflow(self.root)

    def test_inline_application_in_setup_manifest_is_existing_material(self):
        manifest = self.root / "package.json"
        write_json(manifest, {"dependencies": {"fixture-lib": "1.0.0"}, "scripts": {"test": "echo ready"}})
        self.assertEqual(installation.classify_initial_workflow(self.root)["mode"], "pioneer")
        for command in ("node -e \"require('http').createServer((req,res)=>res.end('hello')).listen(3000)\"",
                        "node --eval=\"console.log('application')\"",
                        "python -c \"print('application')\""):
            with self.subTest(command=command):
                write_json(manifest, {"scripts": {"start": command}})
                result = installation.classify_initial_workflow(self.root)
                self.assertEqual(result["mode"], "oasis")
                self.assertEqual(result["product_material"], ["package.json"])
        manifest.write_text("unclassified incomplete setup", encoding="utf-8")
        self.assertEqual(installation.classify_initial_workflow(self.root)["mode"], "oasis")

    def test_existing_program_defaults_oasis_and_explicit_initial_choice_is_reviewable(self):
        (self.root / "main.py").write_text("pass\n", encoding="utf-8")
        default = installation.plan(self.root, PACKAGE)
        self.assertEqual(default["workflow"]["mode"], "oasis")
        self.assertEqual(default["workflow"]["required_roles"], ["Oasis", "Cameleer"])
        explicit = self.install(mode="pioneer")
        self.assertEqual(explicit["workflow"]["classification_basis"], "owner-selected")
        self.assertEqual(explicit["workflow"]["detected_basis"], "existing-program")
        self.assertEqual((self.root / "main.py").read_text(encoding="utf-8"), "pass\n")

    def test_upgrade_preserves_mode_settings_and_legacy_absence_with_all_capabilities(self):
        self.install()
        path = self.root / ".oasis/project.json"
        project = read_json(path)
        project["extensions"]["workflow"]["mode"] = "oasis"
        project["extensions"]["project_fact"] = "owner-selected fact"
        project["capabilities"] = ["oasis-review"]
        write_json(path, project)
        self.install(upgrade=True)
        project["capabilities"] = list(skills.OPTIONAL_NAMES)
        self.assertEqual(read_json(path), project)
        project["extensions"].pop("workflow")
        write_json(path, project)
        plan = self.install(upgrade=True)
        self.assertEqual(plan["workflow"]["classification_basis"], "legacy-oasis-fallback")
        self.assertFalse(plan["workflow"]["initialization_required"])
        self.assertEqual(read_json(path), project)
        self.assertFalse((self.root / ".oasis/local/workflows").exists())
        for upgrade in (False, True):
            with self.assertRaisesRegex(HarnessError, "preserves the existing mode"):
                installation.plan(self.root, PACKAGE, upgrade=upgrade, mode="pioneer")

    def test_partial_installation_requires_recovery_even_with_explicit_mode(self):
        (self.root / ".oasis").mkdir()
        (self.root / ".oasis/project.json").write_text("{}", encoding="utf-8")
        before = (self.root / ".oasis/project.json").read_bytes()
        for mode in (None, "pioneer", "oasis"):
            with self.assertRaisesRegex(HarnessError, "Partial .oasis installation"):
                installation.plan(self.root, PACKAGE, mode=mode)
        self.assertEqual((self.root / ".oasis/project.json").read_bytes(), before)
        self.assertFalse((self.root / installation.MANIFEST).exists())

    def test_cli_initial_mode_is_separate_from_upgrade(self):
        parser = argparse.ArgumentParser()
        installation.register(parser.add_subparsers(dest="command"))
        args = parser.parse_args(["install", "plan", "--target", str(self.root), "--package", str(PACKAGE), "--mode", "oasis"])
        plan = args.func(args)
        self.assertEqual(plan["workflow"]["mode"], "oasis")
        self.assertFalse((self.root / ".oasis").exists())

    def test_project_schema_rejects_invalid_mode_without_sealing_core_text(self):
        neutral = read_json(PACKAGE / "seed/.oasis/project.json")
        for mode in ("pioneer", "oasis"):
            project = json.loads(json.dumps(neutral))
            project["extensions"] = {"workflow": {"mode": mode}}
            self.assertEqual(skills.validate_project(project), project)
        for value in (None, [], "quick", {"mode": []}, {"mode": "prototype"}, {"mode": None}):
            project = json.loads(json.dumps(neutral))
            project["extensions"] = {"workflow": value}
            with self.assertRaises(HarnessError):
                skills.validate_project(project)
        self.assertEqual(read_json(PACKAGE / "seed/.oasis/core.json")["core_version"], "2.0.0")


if __name__ == "__main__":
    unittest.main()
