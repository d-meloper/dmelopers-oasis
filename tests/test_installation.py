import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from oasis_harness import installation as install
from oasis_harness.common import HarnessError, canonical, digest, file_hash, read_json, write_json


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="oasis-install-")
        self.base = Path(self.temporary.name).resolve()
        self.package = self.base / "package"
        for name in ("seed", "library", "oasis_harness", "docs"):
            (self.package / name).mkdir(parents=True)
        (self.package / "seed/AGENTS.md").write_text("one\ntwo\nthree\n", encoding="utf-8")
        (self.package / "seed/.gitignore").write_text("/.oasis/local/\n", encoding="utf-8")
        (self.package / "oasis_harness/__init__.py").write_text('__version__ = "1.2.3"\n', encoding="utf-8")
        (self.package / "seed/settings.json").write_text('{"project":"", "version":1}\n', encoding="utf-8")
        (self.package / "docs/sessions.md").write_text("Inspect actual session identity.\n", encoding="utf-8")
        self.target = self.base / "space ' 한글 中文 😀"
        self.target.mkdir()
        self.state = self.base / "state"

    def tearDown(self):
        self.assertTrue(self.base.is_relative_to(Path(tempfile.gettempdir()).resolve()))
        self.assertTrue(self.base.name.startswith("oasis-install-"))
        self.temporary.cleanup()

    def apply(self, **options):
        return install.apply(install.plan(self.target, self.package, **options), state_root=self.state)

    def resolutions(self, relative, before, after):
        return {"schema_version": 1, "files": [
            {"path": relative, "before_sha256": digest(before), "after_base64": install._encode(after)}]}

    def hashes(self):
        return {p.relative_to(self.target).as_posix(): file_hash(p)
                for p in self.target.rglob("*") if p.is_file()}

    def test_empty_install_repeat_and_no_git_mutation(self):
        self.assertEqual(self.apply()["status"], "installed")
        self.assertFalse((self.target / ".git").exists())
        self.assertEqual(self.apply()["status"], "unchanged")
        self.assertEqual(install.verify(self.target)["status"], "verified")
        self.assertTrue((self.target / "tools/oasis.py").is_file())
        self.assertEqual((self.target / ".oasis/manual/sessions.md").read_text(encoding="utf-8"), "Inspect actual session identity.\n")
        self.assertEqual(read_json(self.target / install.MANIFEST)["package_version"], "1.2.3")

    def test_conflict_zero_writes_and_plan_drift(self):
        (self.target / "AGENTS.md").write_bytes(b"user-owned")
        value = install.plan(self.target, self.package)
        self.assertTrue(value["conflicts"])
        with self.assertRaises(HarnessError):
            install.apply(value, state_root=self.state)
        self.assertEqual(list(self.target.iterdir()), [self.target / "AGENTS.md"])
        (self.target / "AGENTS.md").unlink()
        value = install.plan(self.target, self.package)
        (self.target / "AGENTS.md").write_bytes(b"concurrent owner")
        with self.assertRaisesRegex(HarnessError, "changed since plan"):
            install.apply(value, state_root=self.state)
        self.assertEqual((self.target / "AGENTS.md").read_bytes(), b"concurrent owner")

    def test_initial_ignore_resolution_preserves_project_bytes_and_real_upstream_base(self):
        before = b"# Existing project rules\r\n/build/\r\n/private.env"
        incoming = (self.package / "seed/.gitignore").read_bytes()
        after = before + b"\r\n" + incoming
        (self.target / ".gitignore").write_bytes(before)
        snapshot = self.hashes()
        value = install.plan(self.target, self.package,
                             resolutions=self.resolutions(".gitignore", before, after))
        self.assertEqual(value["conflicts"], [])
        self.assertEqual(self.hashes(), snapshot)
        install.apply(value, state_root=self.state)
        self.assertEqual((self.target / ".gitignore").read_bytes(), after)
        self.assertTrue(after.startswith(before))
        record = read_json(self.target / install.MANIFEST)["managed"][".gitignore"]
        self.assertEqual(record["sha256"], digest(after))
        self.assertEqual(record["base_sha256"], digest(incoming))
        self.assertEqual((self.target / ".oasis/base" / record["base_sha256"]).read_bytes(), incoming)
        self.assertEqual(install.verify(self.target)["specialized"], [".gitignore"])
        self.assertEqual(self.apply()["status"], "unchanged")

    def test_initial_guide_resolution_remains_specialized_across_three_way_upgrade(self):
        before = b"project knowledge\n"
        incoming = (self.package / "seed/AGENTS.md").read_bytes()
        after = incoming + before
        (self.target / "AGENTS.md").write_bytes(before)
        self.apply(resolutions=self.resolutions("AGENTS.md", before, after))
        record = read_json(self.target / install.MANIFEST)["managed"]["AGENTS.md"]
        self.assertEqual(record["base_sha256"], digest(incoming))
        updated = b"new\ntwo\nthree\n"
        (self.package / "seed/AGENTS.md").write_bytes(updated)
        value = install.plan(self.target, self.package, upgrade=True)
        self.assertEqual(value["conflicts"], [])
        install.apply(value, state_root=self.state)
        self.assertEqual((self.target / "AGENTS.md").read_bytes(), updated + before)
        record = read_json(self.target / install.MANIFEST)["managed"]["AGENTS.md"]
        self.assertEqual(record["base_sha256"], digest(updated))
        self.assertEqual((self.target / ".oasis/base" / digest(updated)).read_bytes(), updated)
        self.assertEqual(install.verify(self.target)["specialized"], ["AGENTS.md"])

    def test_initial_resolution_invalid_or_unused_inputs_refuse_without_mutation(self):
        before = b"project knowledge\n"
        (self.target / "AGENTS.md").write_bytes(before)
        good = self.resolutions("AGENTS.md", before, b"one\ntwo\nthree\n" + before)
        cases = []
        def altered(**changes):
            value = json.loads(json.dumps(good))
            value["files"][0].update(changes)
            return value
        cases.extend((altered(before_sha256="0" * 64), altered(before_sha256="not-a-hash"),
                      altered(path="unknown.md"), altered(path="tools/oasis.py"),
                      altered(path=".git/config"), altered(path=".codex/config.toml"),
                      altered(path=".oasis/local/evidence.json"), altered(path="../outside"),
                      altered(after_base64=None), altered(after_base64="not base64!"),
                      altered(unrecognized="foreign field")))
        duplicate = json.loads(json.dumps(good))
        duplicate["files"].append(dict(duplicate["files"][0], path="agents.md"))
        cases.extend((duplicate, {"schema_version": 2, "files": good["files"]},
                      {"schema_version": True, "files": good["files"]},
                      {"schema_version": 1, "files": []},
                      {"schema_version": 1, "files": good["files"], "approval": True},
                      {"schema_version": 1, "files": ["AGENTS.md"]}))
        snapshot = self.hashes()
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(HarnessError):
                    install.plan(self.target, self.package, resolutions=value)
                self.assertEqual(self.hashes(), snapshot)
        (self.target / "AGENTS.md").write_bytes((self.package / "seed/AGENTS.md").read_bytes())
        snapshot = self.hashes()
        with self.assertRaisesRegex(HarnessError, "no existing collision"):
            install.plan(self.target, self.package,
                         resolutions=self.resolutions("AGENTS.md", (self.target / "AGENTS.md").read_bytes(), before))
        self.assertEqual(self.hashes(), snapshot)

    def test_initial_resolutions_refuse_installed_targets_and_upgrade_paths(self):
        before = b"project knowledge\n"
        incoming = (self.package / "seed/AGENTS.md").read_bytes()
        (self.target / "AGENTS.md").write_bytes(before)
        value = self.resolutions("AGENTS.md", before, incoming + before)
        with self.assertRaisesRegex(HarnessError, "fresh installation"):
            install.plan(self.target, self.package, upgrade=True, resolutions=value)
        self.assertEqual(self.hashes(), {"AGENTS.md": digest(before)})
        self.apply(resolutions=value)
        snapshot = self.hashes()
        for upgrade in (False, True):
            with self.subTest(upgrade=upgrade):
                with self.assertRaisesRegex(HarnessError, "fresh installation"):
                    install.plan(self.target, self.package, upgrade=upgrade, resolutions=value)
                self.assertEqual(self.hashes(), snapshot)

    def test_resolved_collision_drift_is_rechecked_before_apply_even_for_unchanged_bytes(self):
        before = b"reviewed existing guidance\n"
        (self.target / "AGENTS.md").write_bytes(before)
        # An explicit reviewed adoption may keep existing bytes as specialization.
        value = install.plan(self.target, self.package,
                             resolutions=self.resolutions("AGENTS.md", before, before))
        self.assertTrue(any(row["path"] == "AGENTS.md" for row in value["operations"]))
        (self.target / "AGENTS.md").write_bytes(b"later owner work\n")
        snapshot = self.hashes()
        with self.assertRaisesRegex(HarnessError, "changed since plan"):
            install.apply(value, state_root=self.state)
        self.assertEqual(self.hashes(), snapshot)
        self.assertFalse((self.target / install.MANIFEST).exists())

    def test_initial_resolution_cli_plan_and_audit_read_the_exact_payload(self):
        before = b"project knowledge\n"
        after = (self.package / "seed/AGENTS.md").read_bytes() + before
        (self.target / "AGENTS.md").write_bytes(before)
        payload = self.base / "reviewed-resolutions.json"
        write_json(payload, self.resolutions("AGENTS.md", before, after))
        parser = argparse.ArgumentParser()
        install.register(parser.add_subparsers(dest="command"))
        snapshot = self.hashes()
        for command in ("plan", "audit"):
            with self.subTest(command=command):
                output = self.base / (command + "-plan.json")
                args = parser.parse_args(["install", command, "--target", str(self.target),
                                          "--package", str(self.package), "--resolutions", str(payload),
                                          "--output", str(output)])
                value = args.func(args)
                self.assertEqual(value["conflicts"], [])
                op = next(row for row in value["operations"] if row["path"] == "AGENTS.md")
                self.assertEqual(install._decode(op["before"]), before)
                self.assertEqual(install._decode(op["after"]), after)
                self.assertEqual(read_json(output), value)
                self.assertEqual(self.hashes(), snapshot)

    def test_distribution_notices_install_and_upgrade_without_owning_project_license(self):
        license_bytes = b"Fixture harness license\n"
        notice_bytes = b"Fixture harness attribution\n"
        (self.package / "LICENSE").write_bytes(license_bytes)
        (self.package / "NOTICE").write_bytes(notice_bytes)
        project_license = b"Existing project license\r\n"
        (self.target / "LICENSE").write_bytes(project_license)
        before = b"/build/\r\n"
        (self.target / ".gitignore").write_bytes(before)
        merged = before + (self.package / "seed/.gitignore").read_bytes()
        self.apply(resolutions=self.resolutions(".gitignore", before, merged))
        self.assertEqual((self.target / "LICENSE").read_bytes(), project_license)
        self.assertEqual((self.target / ".oasis/manual/LICENSE").read_bytes(), license_bytes)
        self.assertEqual((self.target / ".oasis/manual/NOTICE").read_bytes(), notice_bytes)
        manifest = read_json(self.target / install.MANIFEST)
        self.assertNotIn("LICENSE", manifest["managed"])
        self.assertEqual(manifest["managed"][".oasis/manual/LICENSE"]["base_sha256"], digest(license_bytes))
        self.assertEqual(self.apply()["status"], "unchanged")
        updated = license_bytes + b"Additional retained attribution\n"
        (self.package / "LICENSE").write_bytes(updated)
        self.apply(upgrade=True)
        self.assertEqual((self.target / ".oasis/manual/LICENSE").read_bytes(), updated)
        self.assertEqual((self.target / "LICENSE").read_bytes(), project_license)
        self.assertEqual(install.verify(self.target)["status"], "verified")

    def test_distribution_notices_reject_path_collisions_and_nonfiles(self):
        (self.package / "LICENSE").write_bytes(b"Root distribution license\n")
        (self.package / "docs/license").write_bytes(b"Conflicting manual member\n")
        payload = install.package_files(self.package)
        self.assertNotIn(".oasis/manual/license", payload)
        self.assertEqual(payload[".oasis/manual/LICENSE"], b"Root distribution license\n")
        self.assertEqual(list(self.target.iterdir()), [])
        (self.package / "docs/license").unlink()
        (self.package / "NOTICE").mkdir()
        with self.assertRaisesRegex(HarnessError, "Non-file package notice"):
            install.plan(self.target, self.package)
        self.assertEqual(list(self.target.iterdir()), [])

    def test_interrupted_resume_and_user_edit_blocks_rollback(self):
        value = install.plan(self.target, self.package)
        with self.assertRaisesRegex(HarnessError, "Injected"):
            install.apply(value, state_root=self.state, interrupt_after=2)
        journal = next(self.state.glob("*/journal.json"))
        self.assertEqual(install.recover(journal)["status"], "complete")
        self.assertEqual(install.verify(self.target)["status"], "verified")
        (self.package / "seed/AGENTS.md").write_text("new\ntwo\nthree\n", encoding="utf-8")
        upgrade = install.plan(self.target, self.package, upgrade=True)
        with self.assertRaises(HarnessError):
            install.apply(upgrade, state_root=self.state, interrupt_after=1)
        pending = [path for path in self.state.glob("*/journal.json") if read_json(path)["state"] == "applying"][0]
        op = read_json(pending)["plan"]["operations"][0]
        (self.target / op["path"]).write_bytes(b"new peer edit")
        with self.assertRaisesRegex(HarnessError, "user bytes"):
            install.recover(pending, action="rollback")
        self.assertEqual((self.target / op["path"]).read_bytes(), b"new peer edit")

    def test_recovery_rechecks_each_file_after_earlier_writes(self):
        value = install.plan(self.target, self.package)
        with self.assertRaises(HarnessError):
            install.apply(value, state_root=self.state, interrupt_after=1)
        journal = next(self.state.glob("*/journal.json"))
        later = value["operations"][1]["path"]
        real_write = install._write_operation
        calls = 0
        def concurrent_write(root, operation, side):
            nonlocal calls
            real_write(root, operation, side)
            calls += 1
            if calls == 1:
                path = root / later
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"foreign-new-work")
        with mock.patch.object(install, "_write_operation", side_effect=concurrent_write):
            with self.assertRaisesRegex(HarnessError, "user bytes"):
                install.recover(journal)
        self.assertEqual((self.target / later).read_bytes(), b"foreign-new-work")

    def test_three_way_specialization_and_overlap(self):
        self.apply()
        (self.target / "AGENTS.md").write_text("one\ntwo\nproject\n", encoding="utf-8")
        (self.package / "seed/AGENTS.md").write_text("new\ntwo\nthree\n", encoding="utf-8")
        write_json(self.target / "settings.json", {"project": "mine", "version": 1})
        write_json(self.package / "seed/settings.json", {"project": "", "version": 2})
        self.apply(upgrade=True)
        self.assertEqual((self.target / "AGENTS.md").read_text(encoding="utf-8"), "new\ntwo\nproject\n")
        self.assertEqual(read_json(self.target / "settings.json"), {"project": "mine", "version": 2})
        (self.target / "AGENTS.md").write_text("mine\ntwo\nproject\n", encoding="utf-8")
        (self.package / "seed/AGENTS.md").write_text("theirs\ntwo\nthree\n", encoding="utf-8")
        self.assertTrue(install.plan(self.target, self.package, upgrade=True)["conflicts"])

    def test_case_collision_and_tampered_plan(self):
        (self.target / "agents.md").write_bytes(b"one\ntwo\nthree\n")
        self.assertTrue(install.plan(self.target, self.package)["conflicts"])
        (self.target / "agents.md").unlink()
        value = install.plan(self.target, self.package)
        value["operations"][0]["path"] = "../outside"
        with self.assertRaises(HarnessError):
            install.apply(value, state_root=self.state)

    def test_capability_activation_manifest_is_retained_on_upgrade(self):
        self.apply()
        manifest = read_json(self.target / install.MANIFEST)
        base = b"portable skill\n"
        local = b"portable skill with project learning\n"
        relative = ".agents/skills/extra/SKILL.md"
        (self.target / relative).parent.mkdir(parents=True)
        (self.target / relative).write_bytes(local)
        (self.target / ".oasis/base" / digest(base)).write_bytes(base)
        manifest["managed"][relative] = {"owner": "capability:extra", "base_sha256": digest(base), "sha256": digest(base)}
        manifest["enabled_capabilities"] = ["extra"]
        write_json(self.target / install.MANIFEST, manifest)
        value = install.plan(self.target, self.package, upgrade=True)
        manifest_op = next(op for op in value["operations"] if op["path"] == install.MANIFEST)
        updated = json.loads(install._decode(manifest_op["after"]))
        self.assertEqual(updated["enabled_capabilities"], ["extra"])
        self.assertIn(".agents/skills/extra/SKILL.md", updated["managed"])
        self.assertEqual(updated["managed"][relative]["sha256"], digest(local))
        self.assertEqual(updated["managed"][relative]["base_sha256"], digest(base))
        (self.target / relative).unlink()
        self.assertTrue(install.plan(self.target, self.package, upgrade=True)["conflicts"])

    def test_private_distribution_paths_refuse_before_target_writes(self):
        for relative in ("seed/.git/config", "seed/.codex/config.toml", "seed/.oasis/local/evidence.json",
                         "seed/.GiT/config", "seed/.Oasis/LOCAL/evidence.json",
                         "library/example/.git/config", "docs/.codex/config.toml",
                         "oasis_harness/.oasis/local/evidence.json"):
            with self.subTest(relative=relative):
                private = self.package / relative
                private.parent.mkdir(parents=True, exist_ok=True)
                private.write_bytes(b"private-fixture")
                try:
                    with self.assertRaisesRegex(HarnessError, "Protected installation path"):
                        install.plan(self.target, self.package)
                    self.assertEqual(list(self.target.iterdir()), [])
                finally:
                    private.unlink()

    def test_reparse_distribution_roots_are_rejected(self):
        real_reparse = install.is_reparse
        for folder in ("seed", "library", "docs", "oasis_harness"):
            with self.subTest(folder=folder):
                linked = self.package / folder
                # Exercises the actual folder-boundary check without requiring
                # Windows symlink privilege. Nested member checks existed already.
                with mock.patch("oasis_harness.common.is_reparse", side_effect=lambda path: Path(path) == linked or real_reparse(path)):
                    with self.assertRaisesRegex(HarnessError, "Linked path"):
                        install.package_files(self.package)
                self.assertEqual(list(self.target.iterdir()), [])

    def test_rehashed_plan_and_recovery_cannot_own_private_paths(self):
        for relative in (".git/config", ".codex/config.toml", ".oasis/local/evidence.json", ".GiT/config"):
            with self.subTest(relative=relative):
                value = install.plan(self.target, self.package)
                value["operations"].insert(0, {"path": relative, "before": None, "after": install._encode(b"foreign")})
                value["plan_sha256"] = digest({key: item for key, item in value.items() if key != "plan_sha256"})
                journal = self.state / "untrusted" / "journal.json"
                write_json(journal, {"schema_version": 1, "state": "applying", "plan": value, "completed": 0})
                with self.assertRaisesRegex(HarnessError, "Protected installation path"):
                    install.apply(value, state_root=self.state)
                with self.assertRaisesRegex(HarnessError, "Protected installation path"):
                    install.recover(journal)
                self.assertEqual(list(self.target.iterdir()), [])

    def test_private_manifest_ownership_is_rejected_without_mutation(self):
        self.apply()
        manifest_path = self.target / install.MANIFEST
        manifest = read_json(manifest_path)
        manifest["managed"][".codex/config.toml"] = dict(next(iter(manifest["managed"].values())))
        manifest_path.write_bytes(canonical(manifest) + b"\n")
        before = {p.relative_to(self.target).as_posix(): file_hash(p) for p in self.target.rglob("*") if p.is_file()}
        value = install.plan(self.target, self.package, upgrade=True)
        self.assertTrue(any("Protected installation path" in item for item in value["conflicts"]))
        with self.assertRaisesRegex(HarnessError, "Protected installation path"):
            install.verify(self.target)
        with self.assertRaises(HarnessError):
            install.apply(value, state_root=self.state)
        self.assertEqual(before, {p.relative_to(self.target).as_posix(): file_hash(p) for p in self.target.rglob("*") if p.is_file()})


if __name__ == "__main__":
    unittest.main()
