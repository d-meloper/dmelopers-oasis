from pathlib import Path
import shutil
import tempfile
import unittest

from oasis_harness import installation, skills
from oasis_harness.common import HarnessError, digest, read_json
from tools.source_checks import select

PACKAGE = Path(__file__).resolve().parents[1]
GUIDE = "LocalGitWorkflow.md"


def guide_package(root, *, include_guide=True):
    """Small donor fixture for the installer's file ownership/merge boundary."""
    for name in ("seed", "library", "docs", "oasis_harness"):
        (root / name).mkdir(parents=True)
    (root / "oasis_harness/__init__.py").write_bytes(b'__version__ = "1.2.3"\n')
    if include_guide:
        (root / "seed" / GUIDE).write_bytes((PACKAGE / "seed" / GUIDE).read_bytes())
    return root


def file_bytes(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


class DistributionBoundary(unittest.TestCase):
    def test_fresh_payload_has_no_primary_repository_instructions_or_policy(self):
        payload = installation.package_files(PACKAGE)
        for marker in (b"d-meloper/", b"oasis-source-checks", b"source_delivery.py",
                       b"public-source-policy.json", b'distribution_profile: "oasis-harness"'):
            for name, data in payload.items():
                with self.subTest(marker=marker, path=name):
                    if name == ".oasis/manual/upgrade-index.json":
                        # Neutral historical filenames are data, not distributed
                        # source policy code or primary repository bindings.
                        # Permit only these exact names in release.files; scan
                        # all other fields/bytes against every binding marker.
                        import json
                        value = json.loads(data)
                        for release in value["releases"]:
                            release["files"] = [p for p in release["files"] if p not in
                                                {"tools/source_delivery.py", "tests/test_source_delivery.py",
                                                 "tools/public-source-policy.json"}]
                        data = json.dumps(value).encode("utf-8")
                    self.assertNotIn(marker, data)
        self.assertNotIn(".oasis/manual/development.md", payload)
        self.assertNotIn(".oasis/runtime/oasis_harness/public_source.py", payload)
        self.assertIn(".oasis/runtime/oasis_harness/workflows.py", payload)
        self.assertIn(".oasis/runtime/oasis_harness/notifications.py", payload)
        self.assertIn(".oasis/runtime/oasis_harness/shared_runtime.py", payload)
        self.assertIn(".oasis/runtime/oasis_harness/check_results.py", payload)
        self.assertIn(".oasis/manual/upgrade-index.json", payload)
        self.assertIn(".oasis/manual/workflows.md", payload)
        self.assertIn(".agents/skills/oasis-pioneer/SKILL.md", payload)
        self.assertNotIn(".agents/skills/oasis-calf/SKILL.md", payload)
        self.assertNotIn(".oasis/runtime/oasis_harness/packets.py", payload)
        self.assertEqual(len([name for name in payload if name.startswith(".agents/skills/") and name.endswith("/SKILL.md")]), 24)
        self.assertFalse(any(name.startswith(".oasis/library/") for name in payload))
        self.assertEqual(payload[GUIDE], (PACKAGE / "seed" / GUIDE).read_bytes())
        self.assertNotIn(".oasis/manual/" + GUIDE, payload)
        for artwork in ("assets/readme-title.svg", "assets/readme-hero.svg", "assets/readme-hero.png"):
            self.assertNotIn(artwork, payload)
        self.assertEqual(payload[".oasis/manual/CHANGELOG.md"],
                         (PACKAGE / "docs/CHANGELOG.md").read_bytes())
        for relative in installation.PROJECT_KNOWLEDGE_PATHS:
            self.assertNotIn(relative, payload)
        for name in ("adaptation-map.md", "adaptation-map.json", "migration-lessons.md"):
            self.assertNotIn(".oasis/manual/" + name, payload)
        self.assertFalse(any(name.startswith(".githooks/") for name in payload))
        self.assertEqual(read_json(PACKAGE / "seed/.oasis/core.json")["core_version"], "2.0.0")

    def test_skill_reference_links_resolve_in_source_and_installed_payload(self):
        payload = installation.package_files(PACKAGE)
        with tempfile.TemporaryDirectory(prefix="oasis-guide-links-") as tmp:
            installed = Path(tmp)
            # Materialize the real adopter payload without invoking native chats
            # or treating structural links as semantic/live adoption evidence.
            for name, data in payload.items():
                path = installed / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            for role in skills.DEFAULT_NAMES:
                for root in (PACKAGE / "seed", installed):
                    directory = root / ".agents/skills" / role
                    with self.subTest(role=role, layout="source" if root == PACKAGE / "seed" else "installed"):
                        self.assertEqual(skills.inspect_skill(directory)["name"], role)
            for role in skills.OPTIONAL_NAMES:
                self.assertEqual(skills.inspect_skill(installed / ".agents/skills" / role)["name"], role)
            source = installed / ".agents/skills/oasis-camel/SKILL.md"
            source.write_bytes(source.read_bytes() + b"\n[Missing reference](references/missing.md)\n")
            with self.assertRaisesRegex(HarnessError, "Broken installed skill resource"):
                skills.inspect_skill(source.parent)

    def test_source_reference_validation_uses_exact_candidate_heading_bytes(self):
        from tools.source_policy import _skill
        link_files = installation.package_files(PACKAGE)
        prefix = "seed/.agents/skills/oasis-camel"
        logical = ".agents/skills/oasis-camel/"
        files = {prefix + "/" + name.removeprefix(logical): data.replace(b"\r\n", b"\n")
                 for name, data in link_files.items() if name.startswith(logical)}
        files[prefix + "/references/best-practices.md"] += b"\n[Current policy](../../../../.oasis/manual/knowledge.md#project-experience)\n"
        _skill(files, prefix, "oasis-camel", link_files)
        link_files[".oasis/manual/knowledge.md"] = link_files[".oasis/manual/knowledge.md"].replace(
            b"# Project experience", b"# Candidate-only replacement")
        with self.assertRaisesRegex(HarnessError, "missing or invalid required skill reference"):
            _skill(files, prefix, "oasis-camel", link_files)
        self.assertIn(b"# Project experience", (PACKAGE / "docs/knowledge.md").read_bytes())

    def test_retired_capability_metadata_preserves_customization_and_releases_owner(self):
        for state in ("unchanged", "modified", "missing"):
            with self.subTest(state=state), tempfile.TemporaryDirectory(prefix="oasis-retired-cap-") as tmp:
                parent = Path(tmp)
                old = guide_package(parent / "old")
                new = guide_package(parent / "new")
                name = "oasis-state-integrity"
                for package in (old, new):
                    directory = package / "library" / name
                    directory.mkdir()
                    (directory / "SKILL.md").write_bytes(b"# Existing active skill\n")
                original = b'{"schema_version": 1, "name": "oasis-state-integrity", "execution": "tool-guided"}\n'
                (old / "library" / name / "capability.json").write_bytes(original)
                target = parent / "project"; target.mkdir()
                journal_root = parent / "journals"
                installation.apply(installation.plan(target, old), state_root=journal_root)
                relative = f".agents/skills/{name}/capability.json"
                metadata = target / relative
                customized = original + b"\nProject-owned supplemental notes\n"
                if state == "modified":
                    metadata.write_bytes(customized)
                elif state == "missing":
                    metadata.unlink()
                plan = installation.plan(target, new, upgrade=True)
                self.assertEqual(plan["conflicts"], [])
                if state == "modified":
                    self.assertFalse(any(row["path"] == relative for row in plan["operations"]))
                    with self.assertRaisesRegex(HarnessError, "Injected interruption"):
                        installation.apply(plan, state_root=journal_root, interrupt_after=1)
                    customized += b"Later project edit while recovery was pending\n"
                    metadata.write_bytes(customized)
                    journal = next(path for path in journal_root.glob("*/journal.json")
                                   if read_json(path)["state"] == "applying")
                    installation.recover(journal)
                else:
                    installation.apply(plan, state_root=journal_root)
                self.assertNotIn(relative, read_json(target / installation.MANIFEST)["managed"])
                if state == "modified":
                    self.assertEqual(metadata.read_bytes(), customized)
                else:
                    self.assertFalse(metadata.exists())
                repeated = installation.plan(target, new, upgrade=True)
                self.assertFalse(any(row["path"] == relative for row in repeated["operations"]))
                installation.apply(repeated, state_root=journal_root)
                if state == "modified":
                    self.assertEqual(metadata.read_bytes(), customized)

    def test_fresh_install_refuses_existing_same_name_guide_without_writes(self):
        with tempfile.TemporaryDirectory(prefix="oasis-guide-collision-") as tmp:
            parent = Path(tmp)
            target = parent / "project"; target.mkdir()
            (target / GUIDE).write_bytes(b"Owner's existing Git workflow\r\n")
            before = file_bytes(target)
            value = installation.plan(target, PACKAGE, mode="oasis")
            self.assertTrue(any("Existing file differs: " + GUIDE in conflict for conflict in value["conflicts"]))
            self.assertEqual(file_bytes(target), before)
            with self.assertRaisesRegex(HarnessError, "unresolved conflicts"):
                installation.apply(value, state_root=parent / "journals")
            self.assertEqual(file_bytes(target), before)
            self.assertFalse((target / installation.MANIFEST).exists())
            self.assertFalse((parent / "journals").exists())

    def test_new_guide_upgrade_refuses_preexisting_unmanaged_owner_file(self):
        with tempfile.TemporaryDirectory(prefix="oasis-guide-upgrade-collision-") as tmp:
            parent = Path(tmp)
            old = guide_package(parent / "old", include_guide=False)
            incoming = guide_package(parent / "incoming")
            target = parent / "project"; target.mkdir()
            state = parent / "journals"
            installation.apply(installation.plan(target, old), state_root=state)
            self.assertNotIn(GUIDE, read_json(target / installation.MANIFEST)["managed"])
            (target / GUIDE).write_bytes(b"Owner introduced this guide before the harness update.\n")
            before, journals = file_bytes(target), file_bytes(state)
            value = installation.plan(target, incoming, upgrade=True)
            self.assertTrue(any("Existing file differs: " + GUIDE in conflict for conflict in value["conflicts"]))
            with self.assertRaisesRegex(HarnessError, "unresolved conflicts"):
                installation.apply(value, state_root=state)
            self.assertEqual(file_bytes(target), before)
            self.assertEqual(file_bytes(state), journals)

    def test_owned_guide_update_preserves_local_edit_and_original_upstream_bases(self):
        with tempfile.TemporaryDirectory(prefix="oasis-guide-upgrade-merge-") as tmp:
            parent = Path(tmp)
            donor = guide_package(parent / "package")
            target = parent / "project"; target.mkdir()
            state = parent / "journals"
            original = (donor / "seed" / GUIDE).read_bytes()
            installation.apply(installation.plan(target, donor), state_root=state)
            local_addition = b"\nOwner's project-specific checkout rule.\n"
            (target / GUIDE).write_bytes(original + local_addition)
            updated = original.replace(b"# Local Git workflow", b"# Updated local Git workflow", 1)
            self.assertNotEqual(updated, original)
            (donor / "seed" / GUIDE).write_bytes(updated)
            value = installation.plan(target, donor, upgrade=True)
            self.assertEqual(value["conflicts"], [])
            self.assertEqual((target / GUIDE).read_bytes(), original + local_addition)
            installation.apply(value, state_root=state)
            self.assertEqual((target / GUIDE).read_bytes(), updated + local_addition)
            record = read_json(target / installation.MANIFEST)["managed"][GUIDE]
            self.assertEqual(record["sha256"], digest(updated + local_addition))
            self.assertEqual(record["base_sha256"], digest(updated))
            for upstream in (original, updated):
                self.assertEqual((target / ".oasis/base" / digest(upstream)).read_bytes(), upstream)
            self.assertEqual(installation.verify(target)["specialized"], [GUIDE])
            self.assertEqual(installation.apply(installation.plan(target, donor, upgrade=True),
                                               state_root=state)["status"], "unchanged")

    def test_upgrade_removes_old_owned_source_files_and_keeps_local_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            old = parent / "old"
            old.mkdir()
            for name in ("seed", "library", "docs", "oasis_harness"):
                shutil.copytree(PACKAGE / name, old / name, ignore=shutil.ignore_patterns("__pycache__"))
            for name in ("LICENSE", "NOTICE"):
                shutil.copyfile(PACKAGE / name, old / name)
            # Reproduce the old installer intake while retaining current core.
            (old / "docs/development.md").write_bytes(b"Old source-only instructions\n")
            (old / "oasis_harness/public_source.py").write_bytes(b"# Old source-only scanner\n")
            historical = {
                "adaptation-map.md": b"Original historical adaptation note\n",
                "adaptation-map.json": b'{"historical_inventory": true}\n',
                "migration-lessons.md": b"Original historical experience\n",
            }
            for name, content in historical.items():
                (old / "docs" / name).write_bytes(content)
            target = parent / "project"; target.mkdir()
            from unittest.mock import patch
            with patch.object(installation, "ADOPTER_MANUALS", installation.ADOPTER_MANUALS | {"development.md", *historical}), \
                 patch.object(installation, "ADOPTER_MODULES", installation.ADOPTER_MODULES | {"public_source.py"}):
                installation.apply(installation.plan(target, old), state_root=parent / "journals")
            stale = target / ".oasis/manual/development.md"
            stale.write_bytes(b"Owner specialization\n")
            learned = target / ".oasis/manual/migration-lessons.md"
            learned.write_bytes(b"Project's retained historical observation\n")
            upgrade = installation.plan(target, PACKAGE, upgrade=True)
            self.assertFalse(upgrade["conflicts"])
            self.assertIn(".oasis/manual/development.md", upgrade["retained"])
            self.assertIn(".oasis/manual/migration-lessons.md", upgrade["retained"])
            installation.apply(upgrade, state_root=parent / "journals")
            self.assertEqual(stale.read_bytes(), b"Owner specialization\n")
            self.assertEqual(learned.read_bytes(), b"Project's retained historical observation\n")
            self.assertFalse((target / ".oasis/manual/adaptation-map.md").exists())
            self.assertFalse((target / ".oasis/manual/adaptation-map.json").exists())
            self.assertFalse((target / ".oasis/runtime/oasis_harness/public_source.py").exists())
            self.assertNotIn(".oasis/manual/development.md", read_json(target / installation.MANIFEST)["managed"])
            self.assertNotIn(".oasis/manual/migration-lessons.md", read_json(target / installation.MANIFEST)["managed"])
            self.assertEqual((target / ".oasis/manual/CHANGELOG.md").read_bytes(),
                             (PACKAGE / "docs/CHANGELOG.md").read_bytes())

    def test_impact_selection_keeps_expensive_suites_scoped_and_unknowns_full(self):
        docs = select(["docs/development.md", "oasis_harness/__init__.py"], version_literal_only=True)
        self.assertFalse(docs["full"])
        self.assertTrue(select(["oasis_harness/__init__.py"])["full"])
        self.assertNotIn("tests.test_backup", docs["modules"])
        self.assertIn("tests.test_installation", select(["oasis_harness/installation.py"])["modules"])
        self.assertIn("tests.test_rpc_efficiency", select(["oasis_harness/installation.py"])["modules"])
        self.assertIn("tests.test_backup", select(["oasis_harness/backup.py"])["modules"])
        # test_build owns the original-path export guard and source-only
        # prepare/execute integration, even when only the publisher changes.
        self.assertIn("tests.test_build", select(["oasis_harness/publication.py"])["modules"])
        for module in ("sessions", "shared_runtime", "notifications", "workflows"):
            selected = select([f"oasis_harness/{module}.py"])
            self.assertFalse(selected["full"])
            for consumer in ("shared_runtime", "rpc_efficiency", "notifications", "waiting", "deadlines"):
                self.assertIn("tests.test_" + consumer, selected["modules"])
        for name in ("oasis_harness/common.py", "oasis_harness/cli.py", "oasis_harness/new.py", "tools/new.py"):
            self.assertTrue(select([name])["full"])
        self.assertTrue(select([], full=True)["full"])


if __name__ == "__main__":
    unittest.main()
