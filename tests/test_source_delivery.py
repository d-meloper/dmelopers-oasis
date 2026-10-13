import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from oasis_harness import build
from oasis_harness.common import HarnessError, digest, git, read_json, write_json, file_hash
from tests.test_publication import GitHubFixture, fixture_candidate
from types import SimpleNamespace


spec = importlib.util.spec_from_file_location("tested_source_delivery", Path(__file__).resolve().parents[1] / "tools/source_delivery.py")
delivery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delivery)


class SourceDeliveryContracts(unittest.TestCase):
    def reuse_fixture(self, parent, *, full=True, initial_files=None):
        source = parent / "source"
        source.mkdir()
        git(source, "init", "--initial-branch=main")
        git(source, "config", "user.name", "Fixture")
        git(source, "config", "user.email", "fixture@example.invalid")
        for folder in ("tools", "tests", "oasis_harness", "docs"):
            (source / folder).mkdir()
        runner = Path(__file__).resolve().parents[1] / "tools/source_checks.py"
        (source / "tools/source_checks.py").write_bytes(runner.read_bytes())
        # This disposable scanner establishes command/log retention only.
        # It makes no claim about the primary source's privacy policy.
        (source / "tools/check_public_source.py").write_text("print('fresh fixture scan')\n", encoding="utf-8")
        (source / "oasis_harness/__init__.py").write_text('__version__ = "1.2.0"\n', encoding="utf-8")
        (source / "oasis_harness/cli.py").write_text("value = 1\n", encoding="utf-8")
        (source / "oasis_harness/sessions.py").write_text("value = 1\n", encoding="utf-8")
        (source / "tests/__init__.py").write_text("", encoding="utf-8")
        for name in ("public_source", "source_delivery", "distribution", "sessions", "session_transport", "workflows", "dependencies", "backup"):
            (source / f"tests/test_{name}.py").write_text(
                "import unittest\nclass Fixture(unittest.TestCase):\n    def test_pass(self):\n        self.assertTrue(True)\n", encoding="utf-8")
        (source / "docs/guide.md").write_text("Original guide\n", encoding="utf-8")
        for name, text in (initial_files or {}).items():
            (source / name).write_text(text, encoding="utf-8")
        git(source, "add", ".")
        git(source, "commit", "-m", "fixture baseline")
        baseline = Path(build.execute(source, "HEAD", delivery.source_adapter(full=full), parent / "baseline", "1.2.0")["receipt"])
        return source, baseline

    def run_reused_fixture(self, source, baseline, destination):
        head = git(source, "rev-parse", "HEAD")
        with patch.object(delivery, "ROOT", source):
            proof = delivery.verification_plan(head, ["oasis_harness/cli.py"], reuse_build_receipt=baseline)
            adapter = delivery.verification_adapter(proof)
            current = Path(build.execute(source, head, adapter, destination, "1.2.0")["receipt"])
            receipt = read_json(current)
            receipt["source_verification"] = proof
            write_json(current, receipt)
            _, covered = delivery._checked_receipt(current)
        return proof, current, covered

    def changed_shared_input(self, name):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            backup = ("import os, unittest\nimport oasis_harness\nclass Fixture(unittest.TestCase):\n"
                      "    def test_environment(self):\n        self.assertEqual(os.environ.get('OASIS_REUSE_FIXTURE_MODE', 'original'), 'original')\n")
            source, baseline = self.reuse_fixture(parent, initial_files={"tests/test_backup.py": backup})
            path = source / name
            setup = "import os\nos.environ['OASIS_REUSE_FIXTURE_MODE'] = 'changed'\n"
            if name == "tools/source_checks.py":
                path.write_text(path.read_text(encoding="utf-8").replace('if __name__ == "__main__":', setup + '\nif __name__ == "__main__":'), encoding="utf-8")
            else:
                path.write_text(path.read_text(encoding="utf-8") + setup, encoding="utf-8")
            git(source, "add", name)
            git(source, "commit", "-m", "fixture shared input")
            with patch.object(delivery, "ROOT", source):
                proof = delivery.verification_plan("HEAD", [name], reuse_build_receipt=baseline)
                self.assertTrue(proof["runner_full"])
                self.assertTrue(proof["executed"]["full"])
                self.assertEqual(proof["reused_modules"], [])
                self.assertEqual(proof["additional_modules"], [])
                adapter = delivery.verification_adapter(proof)
                self.assertIn("--full", adapter["checks"][1])
                with self.assertRaisesRegex(HarnessError, "failed with exit code"):
                    build.execute(source, "HEAD", adapter, parent / "changed", "1.2.0")
                failed = parent / "changed/build.json"
                self.assertEqual(read_json(failed)["phase"], "failed")
                with self.assertRaises(HarnessError):
                    delivery._checked_receipt(failed)
                log = (failed.parent / "command-2.log").read_text(encoding="utf-8")
                self.assertIn("Source coverage: full suite", log)
                self.assertIn("tests.test_backup", log)
                self.assertIn("FAIL", log)

    def test_changed_source_runner_invalidates_previous_modules_in_the_real_runner(self):
        self.changed_shared_input("tools/source_checks.py")

    def test_changed_test_initializer_invalidates_previous_modules_in_the_real_runner(self):
        self.changed_shared_input("tests/__init__.py")

    def test_runtime_initializer_behavior_is_distinct_from_version_metadata(self):
        self.changed_shared_input("oasis_harness/__init__.py")

    def test_fixture_import_consumers_are_invalidated_transitively(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            check = "import unittest\nclass Fixture(unittest.TestCase):\n    def test_token(self):\n        self.assertEqual(TOKEN, 1)\n"
            helper_check = "import unittest\nclass Fixture(unittest.TestCase):\n    def test_helper(self):\n        self.assertTrue(True)\n"
            source, baseline = self.reuse_fixture(parent, initial_files={
                "tests/test_sessions.py": "TOKEN = 1\n" + helper_check,
                "tests/test_backup.py": "from tests.test_sessions import TOKEN\n" + check,
                "tests/test_workflows.py": "from tests import test_backup\nTOKEN = test_backup.TOKEN\n" + check,
                "tests/test_dependencies.py": "from .test_workflows import TOKEN\n" + check})
            (source / "tests/test_sessions.py").write_text("TOKEN = 2\n" + helper_check, encoding="utf-8")
            git(source, "add", "tests/test_sessions.py")
            git(source, "commit", "-m", "fixture shared token")
            with patch.object(delivery, "ROOT", source):
                proof = delivery.verification_plan("HEAD", ["tests/test_sessions.py"], reuse_build_receipt=baseline)
                self.assertFalse(proof["runner_full"])
                self.assertEqual(proof["additional_modules"], ["tests.test_backup", "tests.test_dependencies", "tests.test_workflows"])
                for module in proof["additional_modules"]:
                    self.assertNotIn(module, proof["reused_modules"])
                with self.assertRaisesRegex(HarnessError, "failed with exit code"):
                    build.execute(source, "HEAD", delivery.verification_adapter(proof), parent / "changed", "1.2.0")
                log = (parent / "changed/command-3.log").read_text(encoding="utf-8")
                for module in proof["additional_modules"]:
                    self.assertIn(module, log)
                self.assertIn("FAIL", log)

    def test_verified_suite_is_reused_after_only_document_and_version_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            source, baseline = self.reuse_fixture(parent)
            (source / "docs/guide.md").write_text("Revised guide\n", encoding="utf-8")
            (source / "oasis_harness/__init__.py").write_text('__version__ = "1.2.1"\n', encoding="utf-8")
            git(source, "add", ".")
            git(source, "commit", "-m", "fixture metadata")
            proof, current, covered = self.run_reused_fixture(source, baseline, parent / "incremental")
            self.assertFalse(proof["executed"]["full"])
            self.assertIn("tests.test_backup", proof["reused_modules"])
            self.assertEqual(proof["additional_modules"], [])
            self.assertIn("tests.test_backup", covered)
            self.assertEqual(proof["reuse"]["sha256"], file_hash(baseline))
            self.assertIn("fresh fixture scan", (current.parent / "command-1.log").read_text(encoding="utf-8"))
            self.assertNotIn("tests.test_backup", (current.parent / "command-2.log").read_text(encoding="utf-8"))
            self.assertNotIn("--full", read_json(current)["commands"][1]["argv"])

    def test_runtime_inputs_and_new_tests_run_only_their_affected_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            source, baseline = self.reuse_fixture(parent)
            (source / "oasis_harness/sessions.py").write_text("value = 2\n", encoding="utf-8")
            (source / "tests/test_new_input.py").write_text(
                "import unittest\nclass Fixture(unittest.TestCase):\n    def test_new(self):\n        self.assertEqual(2, 2)\n", encoding="utf-8")
            git(source, "add", ".")
            git(source, "commit", "-m", "fixture affected input")
            proof, current, _ = self.run_reused_fixture(source, baseline, parent / "incremental")
            self.assertFalse(proof["executed"]["full"])
            self.assertIn("tests.test_backup", proof["reused_modules"])
            for name in ("sessions", "session_transport", "workflows", "dependencies", "new_input"):
                self.assertIn("tests.test_" + name, proof["executed"]["modules"])
                self.assertNotIn("tests.test_" + name, proof["reused_modules"])
            log = (current.parent / "command-2.log").read_text(encoding="utf-8")
            self.assertIn("tests.test_new_input", log)
            self.assertNotIn("tests.test_backup", log)

    def test_partial_baseline_adds_missing_modules_and_damaged_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            source, baseline = self.reuse_fixture(parent, full=False)
            proof, current, covered = self.run_reused_fixture(source, baseline, parent / "incremental")
            self.assertIn("tests.test_backup", proof["additional_modules"])
            self.assertEqual(proof["reused_modules"], [])
            self.assertIn("tests.test_backup", covered)
            self.assertIn("tests.test_backup", (current.parent / "command-3.log").read_text(encoding="utf-8"))
            original = baseline.read_bytes()
            with patch.object(delivery, "ROOT", source):
                for phase in ("running", "failed"):
                    value = read_json(baseline)
                    value["phase"] = phase
                    write_json(baseline, value)
                    with self.subTest(phase=phase), self.assertRaises(HarnessError):
                        delivery.verification_plan("HEAD", [], reuse_build_receipt=baseline)
                    baseline.write_bytes(original)
                with self.assertRaisesRegex(HarnessError, "Explicit --full"):
                    delivery.verification_plan("HEAD", [], full=True, reuse_build_receipt=baseline)
                log = baseline.parent / "command-2.log"
                log.write_text("invented pass\n", encoding="utf-8")
                with self.assertRaisesRegex(HarnessError, "Build log drift"):
                    delivery.verification_plan("HEAD", [], reuse_build_receipt=baseline)

    def test_custom_policy_cannot_execute_through_the_generic_publisher(self):
        from oasis_harness import publication
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "candidate"; fixture_candidate(root)
            value = read_json(root / "candidate.json")
            value["config"]["source_policy"] = "fixture-policy"
            sha = digest(value)
            write_json(root / "candidate.json", value)
            write_json(root / "state.json", {"candidate_id": sha, "phase": "prepared", "events": []})
            provider = GitHubFixture()
            for policy in (None, SimpleNamespace(name="other-policy")):
                with self.subTest(policy=policy), self.assertRaisesRegex(HarnessError, "explicitly supplied"):
                    publication.Publisher(root, sha, provider, policy=policy)
            self.assertFalse(provider.mutations)

    def test_parallel_readback_rejects_one_changed_or_unavailable_blob(self):
        from oasis_harness.publication import blob_sha
        publisher = object.__new__(delivery.SourcePublisher)
        publisher.slug = "fixture/public"
        publisher.policy = SimpleNamespace(scan_file=lambda name, data: None)
        publisher.spec = {"projection": {name: {"sha": blob_sha(data)} for name, data in
                                         {"docs/a.md": b"a", "docs/b.md": b"b"}.items()}}
        publisher.provider = SimpleNamespace(download_source=lambda slug, commit, name: b"a" if name == "docs/a.md" else b"b")
        publisher.verify_source("a" * 40)
        publisher.provider.download_source = lambda slug, commit, name: b"a"
        with self.assertRaisesRegex(HarnessError, "Anonymous public source"):
            publisher.verify_source("a" * 40)
        def missing(slug, commit, name):
            raise OSError("Unavailable fixture")
        publisher.provider.download_source = missing
        with self.assertRaises(OSError):
            publisher.verify_source("a" * 40)

    def test_successful_generic_checks_cannot_attest_the_primary_source_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp); source = parent / "source"; source.mkdir()
            git(source, "init", "--initial-branch=main"); git(source, "config", "user.name", "Fixture"); git(source, "config", "user.email", "fixture@example.invalid")
            (source / "input.txt").write_bytes(b"neutral fixture")
            git(source, "add", "input.txt"); git(source, "commit", "-m", "fixture")
            adapter = {"schema_version": 1, "purpose": "source", "build": [], "artifacts": [], "checks": [[sys.executable, "-c", "pass"]]}
            receipt_path = Path(build.execute(source, "HEAD", adapter, parent / "build", "1")["receipt"])
            receipt = read_json(receipt_path)
            candidate = parent / "candidate"; fixture_candidate(candidate)
            value = read_json(candidate / "candidate.json")
            value["config"].update(operation="source", tag=None, make_latest=False, channel="stable", source_policy="fixture-policy")
            value["private_producer"] = receipt["source"]
            value["build_receipt_sha256"] = file_hash(receipt_path)
            selected = {key: value["config"][key] for key in ("repository", "repository_id", "base_branch", "operation", "channel", "required_checks")}
            selected["account_id"] = 7
            expected = digest(value)
            write_json(candidate / "candidate.json", value)
            write_json(candidate / "state.json", {"candidate_id": expected, "phase": "prepared", "events": []})
            write_json(parent / "coverage.json", {**delivery.select([]), "base_commit": value["base_commit"], "explicit_full": False})
            provider = GitHubFixture()
            with patch.object(delivery, "ROOT", source), patch.object(delivery, "source_config", return_value=selected), patch.object(delivery.backup, "status", return_value={"source_main_match": True}), patch.object(delivery, "current_policy", return_value=SimpleNamespace(name="fixture-policy")), patch.object(delivery, "changes_from_public", return_value=(value["base_commit"], [])):
                with self.assertRaisesRegex(HarnessError, "actual retained privacy"):
                    delivery.attest(candidate, expected, receipt_path, "fixture request", provider)
                git(source, "checkout", "-b", "feature")
                for detached in (False, True):
                    if detached:
                        git(source, "checkout", "--detach", "HEAD")
                    with self.subTest(detached=detached):
                        with self.assertRaisesRegex(HarnessError, "actual main checkout"):
                            delivery.prepare(parent / "not-created", "fixture", parent / "absent-notes", provider)
                        with self.assertRaisesRegex(HarnessError, "actual main checkout"):
                            delivery.attest(candidate, expected, receipt_path, "fixture request", provider)
                    self.assertFalse((parent / "not-created").exists())
            self.assertEqual(provider.mutations, [])

    def test_candidate_binding_cannot_redirect_primary_source_attestation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "candidate"; expected = fixture_candidate(root)
            value = read_json(root / "candidate.json")
            value["config"]["source_policy"] = delivery.current_policy().name
            expected = digest(value)
            write_json(root / "candidate.json", value)
            write_json(root / "state.json", {"candidate_id": expected, "phase": "prepared", "events": []})
            provider = GitHubFixture()
            with patch.object(delivery, "source_config", return_value={"repository": "different/public", "repository_id": 2, "account_id": 7}):
                with self.assertRaisesRegex(HarnessError, "selected binding"):
                    delivery.attest(root, expected, Path(tmp) / "absent-receipt", "fixture request", provider)
            self.assertEqual(provider.mutations, [])


if __name__ == "__main__":
    unittest.main()
