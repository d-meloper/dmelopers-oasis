from pathlib import Path
import shutil
import tempfile
import unittest

from oasis_harness import installation
from oasis_harness.common import HarnessError, digest, read_json
from tools.source_checks import select

PACKAGE = Path(__file__).resolve().parents[1]


class DistributionBoundary(unittest.TestCase):
    def test_fresh_payload_has_no_primary_repository_instructions_or_policy(self):
        payload = installation.package_files(PACKAGE)
        for marker in (b"d-meloper/", b"oasis-source-checks", b"source_delivery.py",
                       b"public-source-policy.json", b'distribution_profile: "oasis-harness"'):
            for name, data in payload.items():
                with self.subTest(marker=marker, path=name):
                    self.assertNotIn(marker, data)
        self.assertNotIn(".oasis/manual/development.md", payload)
        self.assertNotIn(".oasis/runtime/oasis_harness/public_source.py", payload)
        self.assertIn(".oasis/runtime/oasis_harness/workflows.py", payload)
        self.assertIn(".oasis/manual/workflows.md", payload)
        self.assertIn(".agents/skills/oasis-pioneer/SKILL.md", payload)
        self.assertEqual(payload[".oasis/manual/adaptation-map.json"],
                         (PACKAGE / "docs/adaptation-map.json").read_bytes())
        self.assertFalse(any(name.startswith(".githooks/") for name in payload))
        self.assertEqual(digest(read_json(PACKAGE / "seed/.oasis/core.json")),
                         "1ddc968c0c19c1e2f89c56158cf40036c41838f7d97d33799cbf7cf3d6d1b07f")

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
            target = parent / "project"; target.mkdir()
            from unittest.mock import patch
            with patch.object(installation, "ADOPTER_MANUALS", installation.ADOPTER_MANUALS | {"development.md"}), \
                 patch.object(installation, "ADOPTER_MODULES", installation.ADOPTER_MODULES | {"public_source.py"}):
                installation.apply(installation.plan(target, old), state_root=parent / "journals")
            stale = target / ".oasis/manual/development.md"
            stale.write_bytes(b"Owner specialization\n")
            upgrade = installation.plan(target, PACKAGE, upgrade=True)
            self.assertFalse(upgrade["conflicts"])
            self.assertIn(".oasis/manual/development.md", upgrade["retained"])
            installation.apply(upgrade, state_root=parent / "journals")
            self.assertEqual(stale.read_bytes(), b"Owner specialization\n")
            self.assertFalse((target / ".oasis/runtime/oasis_harness/public_source.py").exists())
            self.assertNotIn(".oasis/manual/development.md", read_json(target / installation.MANIFEST)["managed"])
            self.assertEqual((target / ".oasis/manual/adaptation-map.json").read_bytes(),
                             (PACKAGE / "docs/adaptation-map.json").read_bytes())

    def test_impact_selection_keeps_expensive_suites_scoped_and_unknowns_full(self):
        docs = select(["docs/development.md", "oasis_harness/__init__.py"])
        self.assertFalse(docs["full"])
        self.assertNotIn("tests.test_backup", docs["modules"])
        self.assertIn("tests.test_installation", select(["oasis_harness/installation.py"])["modules"])
        self.assertIn("tests.test_backup", select(["oasis_harness/backup.py"])["modules"])
        # Packet route/wait behavior is owned by tests.test_common, rather than
        # by a test module named after the runtime. Retain that direct coverage.
        self.assertIn("tests.test_common", select(["oasis_harness/packets.py"])["modules"])
        # test_build owns the original-path export guard and source-only
        # prepare/execute integration, even when only the publisher changes.
        self.assertIn("tests.test_build", select(["oasis_harness/publication.py"])["modules"])
        for name in ("oasis_harness/common.py", "oasis_harness/cli.py", "oasis_harness/new.py", "tools/new.py"):
            self.assertTrue(select([name])["full"])
        self.assertTrue(select([], full=True)["full"])


if __name__ == "__main__":
    unittest.main()
