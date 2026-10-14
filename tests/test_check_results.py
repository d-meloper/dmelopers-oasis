"""Subset evidence never promotes a failed whole test run."""
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from oasis_harness import check_results
from oasis_harness.common import HarnessError, read_json, run


class CheckResultContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "project 한글"
        self.root.mkdir()
        (self.root / "source.txt").write_text("original", encoding="utf-8")
        (self.root / "dependency.txt").write_text("runtime bytes", encoding="utf-8")

    def record(self, *, exit_code=1, extra="", xml=None, runtime=True):
        xml = xml or '<testsuite tests="2" errors="0"><testcase classname="scope" name="passed"/><testcase classname="scope" name="failed"><failure>fixture</failure></testcase></testsuite>'
        command = [sys.executable, "-B", "-X", "utf8", "-c",
            "from pathlib import Path; import sys; Path(sys.argv[1]).write_text(" + repr(xml) + ",encoding='utf-8'); " + extra + "raise SystemExit(" + str(exit_code) + ")", "{report}"]
        return check_results.execute(self.root, command, inputs=["source.txt"], runtime=["dependency.txt"] if runtime else [])

    def test_passed_subset_reuses_failed_full_without_running_any_command(self):
        recorded = self.record()
        self.assertFalse(recorded["whole_run_passed"])
        self.assertEqual(recorded["exit_code"], 1)
        with patch("oasis_harness.check_results.run", side_effect=AssertionError("A reuse decision executes no tests")):
            result = check_results.reuse(recorded["receipt"], ["scope::passed"])
        self.assertEqual(result["status"], "reusable")
        self.assertEqual(result["whole_run_exit_code"], 1)
        self.assertEqual(result["other_nonpassing_cases"], {"scope::failed": "failure"})
        self.assertEqual(read_json(recorded["receipt"])["exit_code"], 1)

    def test_failure_skip_missing_and_infrastructure_are_not_reused(self):
        recorded = self.record()
        for name in ("scope::failed", "scope::missing"):
            self.assertEqual(check_results.reuse(recorded["receipt"], [name])["status"], "needs_check")
        xml = '<testsuite errors="1"><testcase classname="scope" name="passed"/><testcase classname="scope" name="skip"><skipped/></testcase><testcase classname="scope" name="setup"><error/></testcase></testsuite>'
        result = self.record(xml=xml)
        for name in ("scope::passed", "scope::skip"):
            self.assertEqual(check_results.reuse(result["receipt"], [name])["status"], "needs_check")

    def test_source_runtime_environment_and_purpose_invalidate_reuse(self):
        for name in ("source.txt", "dependency.txt"):
            recorded = self.record()
            path = self.root / name
            before = path.read_bytes(); path.write_bytes(before + b"changed")
            self.assertEqual(check_results.reuse(recorded["receipt"], ["scope::passed"])["status"], "needs_check")
            path.write_bytes(before)
        recorded = self.record()
        with patch.dict(os.environ, {"OASIS_CHECK_INPUT": "changed"}):
            self.assertEqual(check_results.reuse(recorded["receipt"], ["scope::passed"])["status"], "needs_check")
        self.assertEqual(check_results.reuse(recorded["receipt"], ["scope::passed"], purpose="independent review")["status"], "needs_check")

    def test_unknown_runtime_abnormal_exit_and_original_input_mutation_are_not_reused(self):
        for result in (self.record(runtime=False), self.record(exit_code=2),
                       self.record(extra="Path('source.txt').write_text('changed'); ")):
            self.assertEqual(check_results.reuse(result["receipt"], ["scope::passed"])["status"], "needs_check")

    def test_report_and_log_drift_are_rejected(self):
        for name in ("report.xml", "command.log"):
            result = self.record()
            path = Path(result["receipt"]).parent / name
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaisesRegex(HarnessError, "drift"):
                check_results.reuse(result["receipt"], ["scope::passed"])

    def test_unexplained_nonzero_exit_and_false_success_are_not_coverage(self):
        passed = '<testsuite><testcase classname="scope" name="passed"/></testsuite>'
        for result in (self.record(xml=passed), self.record(exit_code=0)):
            self.assertEqual(check_results.reuse(result["receipt"], ["scope::passed"])["status"], "needs_check")

    def test_duplicate_cases_and_entity_input_are_rejected(self):
        path = self.root / "bad.xml"
        for xml in ('<testsuite><testcase classname="s" name="x"/><testcase classname="s" name="x"/></testsuite>',
                    '<!DOCTYPE testsuite><testsuite/>'):
            path.write_text(xml, encoding="utf-8")
            with self.assertRaises(HarnessError):
                check_results.junit_cases(path)

    def test_cli_preserves_failed_test_status_and_unique_evidence(self):
        from oasis_harness.cli import main
        from unittest.mock import patch
        result = self.record()
        with patch('oasis_harness.check_results.execute', return_value=result):
            self.assertEqual(main(["check", "run", "--root", str(self.root), "--", "fixture", "{report}"]), 1)
        second = self.record()
        self.assertNotEqual(result["receipt"], second["receipt"])


if __name__ == "__main__":
    unittest.main()
