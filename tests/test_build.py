from pathlib import Path
import sys
import tempfile
import unittest
from oasis_harness.build import execute, verify_evidence
from oasis_harness.common import HarnessError, git, run, write_json, read_json


class BuildContracts(unittest.TestCase):
    def test_timeout_retains_partial_log_and_failed_receipt(self):
        from unittest.mock import patch
        from oasis_harness.common import ProcessTimeout
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            def snapshot(root, revision, destination):
                destination.mkdir(parents=True)
                return {"commit": "a" * 40, "tree": "b" * 40, "files": {}, "modes": {}, "object_format": "sha1", "state": "committed"}
            adapter = {"schema_version": 1, "purpose": "source", "build": [], "checks": [["fixture-check"]], "artifacts": []}
            with patch("oasis_harness.build.committed_snapshot", side_effect=snapshot), patch("oasis_harness.build.execution_environment", return_value={}), patch("oasis_harness.build.run", side_effect=ProcessTimeout(1, b"partial compiler output", b"private fixture diagnostic")):
                with self.assertRaises(HarnessError):
                    execute(parent, "HEAD", adapter, parent / "timeout", "1")
            receipt = read_json(parent / "timeout/build.json")
            self.assertEqual(receipt["phase"], "failed")
            self.assertTrue(receipt["commands"][0]["timed_out"])
            self.assertIn("partial compiler output", (parent / "timeout/command-1.log").read_text(encoding="utf-8"))
            self.assertNotIn("private fixture diagnostic", receipt["error"])
            with self.assertRaises(HarnessError):
                verify_evidence(parent / "timeout/build.json")

    def test_receipt_and_adapter_consumed_shapes_fail_before_io(self):
        from unittest.mock import patch
        for invalid in (None, [], "text"):
            with self.subTest(invalid=invalid), patch("oasis_harness.build.read_json", return_value=invalid):
                with self.assertRaises(HarnessError):
                    verify_evidence("virtual.json")
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "not-created"
            with self.assertRaises(HarnessError):
                execute(tmp, "HEAD", [], destination, "1")
            self.assertFalse(destination.exists())

    def test_fingerprint_tracks_only_minimal_declared_inputs(self):
        from unittest.mock import patch
        from oasis_harness.build import execution_environment
        with patch("oasis_harness.build.git", return_value="git version fixture"), patch.dict("os.environ", {"OASIS_FIXTURE_INPUT": "private-fixture-value", "UNRELATED_FIXTURE_INPUT": "other"}):
            first = execution_environment("fixture", ["OASIS_FIXTURE_INPUT"])
            with patch.dict("os.environ", {"UNRELATED_FIXTURE_INPUT": "changed"}):
                self.assertEqual(first, execution_environment("fixture", ["OASIS_FIXTURE_INPUT"]))
        self.assertNotIn("private-fixture-value", str(first))
        self.assertEqual(set(first["env"]), {"OASIS_FIXTURE_INPUT"})

    def test_private_source_cannot_be_renamed_into_public_export(self):
        from oasis_harness.publication import prepare
        from tests.test_publication import GitHubFixture
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp); root = parent / "source"; root.mkdir()
            git(root, "init"); git(root, "config", "user.name", "Fixture"); git(root, "config", "user.email", "fixture@example.invalid")
            (root / ".oasis/local").mkdir(parents=True)
            (root / ".oasis/local/note.txt").write_bytes(b"fixture data")
            git(root, "add", ".oasis/local/note.txt"); git(root, "commit", "-m", "fixture")
            adapter = {"schema_version": 1, "purpose": "source", "build": [], "artifacts": [], "checks": [[sys.executable, "-c", "assert True"]]}
            receipt = execute(root, "HEAD", adapter, parent / "build", "1")["receipt"]
            config = {"schema_version": 1, "repository": "fixture/public", "repository_id": 1, "base_branch": "main", "channel": "stable", "mode": "source-and-artifacts", "operation": "source", "version": "1", "tag": None, "title": "Fixture", "make_latest": False, "exports": {".oasis/local/note.txt": "docs/note.txt"}, "required_checks": []}
            write_json(parent / "config.json", config); (parent / "notes.md").write_bytes(b"Fixture notes")
            provider = GitHubFixture()
            with self.assertRaisesRegex(HarnessError, "Private operational path"):
                prepare(parent / "config.json", receipt, parent / "notes.md", parent / "candidate", provider)
            self.assertEqual(provider.mutations, [])
            self.assertFalse((parent / "candidate").exists())

    def test_source_only_tag_latest_and_executable_mode(self):
        from oasis_harness.publication import prepare
        from tests.test_publication import GitHubFixture
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp); root = parent / "source"; root.mkdir()
            git(root, "init"); git(root, "config", "user.name", "Fixture"); git(root, "config", "user.email", "fixture@example.invalid")
            (root / "script.sh").write_bytes(b"#!/bin/sh\nexit 0\n")
            git(root, "add", "script.sh"); git(root, "update-index", "--chmod=+x", "script.sh"); git(root, "commit", "-m", "fixture")
            adapter = {"schema_version": 1, "purpose": "source", "build": [], "artifacts": [], "checks": [[sys.executable, "-c", "assert True"]]}
            receipt = execute(root, "HEAD", adapter, parent / "build", "1")["receipt"]
            config = {"schema_version": 1, "repository": "fixture/public", "repository_id": 1, "base_branch": "main", "channel": "stable", "mode": "source-and-artifacts", "operation": "source", "version": "1", "tag": None, "title": "Fixture", "make_latest": False, "exports": {"script.sh": "script.sh"}, "required_checks": []}
            (parent / "notes.md").write_bytes(b"Fixture notes")
            for field, value in (("tag", "v1"), ("make_latest", True)):
                invalid = dict(config, **{field: value}); write_json(parent / "config.json", invalid)
                with self.assertRaisesRegex(HarnessError, "tag null"):
                    prepare(parent / "config.json", receipt, parent / "notes.md", parent / "rejected", GitHubFixture())
            write_json(parent / "config.json", config)
            prepare(parent / "config.json", receipt, parent / "notes.md", parent / "candidate", GitHubFixture())
            spec = read_json(parent / "candidate/candidate.json")
            self.assertEqual(spec["public_files"]["script.sh"]["mode"], "100755")

    def test_source_only_and_artifacts_only_candidate_projections(self):
        from oasis_harness.publication import prepare, Publisher
        from tests.test_publication import GitHubFixture
        for purpose in ("source","release"):
            with self.subTest(purpose=purpose), tempfile.TemporaryDirectory() as tmp:
                parent=Path(tmp);root=parent/"source";root.mkdir();git(root,"init");git(root,"config","user.name","Fixture");git(root,"config","user.email","fixture@example.invalid")
                (root/"input.txt").write_bytes(b"public fixture\n");git(root,"add","input.txt");git(root,"commit","-m","fixture")
                adapter={"schema_version":1,"purpose":purpose,"build":[] if purpose=="source" else [[sys.executable,"-c","from pathlib import Path; Path(r'{output}/fixture.txt').write_bytes(b'public artifact')"]],"checks":[[sys.executable,"-c","from pathlib import Path; assert Path('input.txt').read_bytes()==b'public fixture\\n'"]],"artifacts":[] if purpose=="source" else ["fixture.txt"]}
                result=execute(root,"HEAD",adapter,parent/"build","1")
                config={"schema_version":1,"repository":"fixture/public","repository_id":1,"base_branch":"main","channel":"stable","mode":"source-and-artifacts" if purpose=="source" else "artifacts-only","operation":purpose,"version":"1","tag":None if purpose=="source" else "v1","title":"Fixture","make_latest":purpose=="release","exports":{"input.txt":"public.txt"} if purpose=="source" else {},"required_checks":[]}
                write_json(parent/"config.json",config);(parent/"notes.md").write_bytes(b"Fixture notes\n");provider=GitHubFixture()
                candidate=prepare(parent/"config.json",result["receipt"],parent/"notes.md",parent/"candidate",provider)
                spec=read_json(parent/"candidate/candidate.json")
                self.assertEqual("public.txt" in spec["public_files"],purpose=="source")
                public_metadata=read_json(parent/"candidate/public/oasis-release.json")
                self.assertNotIn("private_producer",public_metadata)
                self.assertNotIn("source_root",public_metadata)
                self.assertEqual(Publisher(parent/"candidate",candidate["sha256"],provider).execute("fixture approval")["phase"],"source_verified" if purpose=="source" else "verified")

    def test_real_unicode_snapshot_adapter_and_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source 한글"; root.mkdir()
            git(root,"init"); git(root,"config","user.name","Fixture"); git(root,"config","user.email","fixture@example.invalid")
            (root / "input.txt").write_text("fixture input",encoding="utf-8")
            git(root,"add","input.txt"); git(root,"commit","-m","fixture")
            (root / "input.txt").write_text("dirty retained",encoding="utf-8")
            adapter = {"schema_version": 1, "build": [[sys.executable,"-c","from pathlib import Path; Path(r'{output}/fixture.txt').write_bytes(Path('input.txt').read_bytes())"]], "checks": [[sys.executable,"-c","from pathlib import Path; assert Path(r'{output}/fixture.txt').read_text()=='fixture input'"]], "artifacts": ["fixture.txt"]}
            result = execute(root,"HEAD",adapter,Path(tmp)/"build","1")
            proof = verify_evidence(result["receipt"])
            self.assertEqual(proof["phase"],"verified")
            self.assertEqual((root/"input.txt").read_text(),"dirty retained")
            (Path(tmp)/"build/output/fixture.txt").write_text("changed")
            with self.assertRaises(HarnessError): verify_evidence(result["receipt"])

    def test_failed_adapter_keeps_failure_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"source";root.mkdir();git(root,"init");git(root,"config","user.name","Fixture");git(root,"config","user.email","fixture@example.invalid");(root/"a").write_text("x");git(root,"add","a");git(root,"commit","-m","fixture")
            adapter={"schema_version":1,"build":[[sys.executable,"-c","raise SystemExit(7)"]],"checks":[[sys.executable,"-c","pass"]],"artifacts":["x"]}
            with self.assertRaises(HarnessError):execute(root,"HEAD",adapter,Path(tmp)/"failed","1")
            self.assertTrue((Path(tmp)/"failed/build.json").exists())
            with self.assertRaises(HarnessError):verify_evidence(Path(tmp)/"failed/build.json")
