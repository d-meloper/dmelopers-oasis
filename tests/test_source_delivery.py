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
