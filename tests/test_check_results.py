"""Subset evidence never promotes a failed whole test run."""
from pathlib import Path
import os
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import patch

from oasis_harness import check_results
from oasis_harness.common import HarnessError, read_json, run, write_json


class CheckResultContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "project 한글"
        self.root.mkdir()
        (self.root / "source.txt").write_text("original", encoding="utf-8")
        (self.root / "dependency.txt").write_text("runtime bytes", encoding="utf-8")

    def record(self, *, exit_code=1, extra="", xml=None, runtime=True, **kwargs):
        xml = xml or '<testsuite tests="2" errors="0"><testcase classname="scope" name="passed"/><testcase classname="scope" name="failed"><failure>fixture</failure></testcase></testsuite>'
        command = [sys.executable, "-B", "-X", "utf8", "-c",
            "from pathlib import Path; import sys; Path(sys.argv[1]).write_text(" + repr(xml) + ",encoding='utf-8'); " + extra + "raise SystemExit(" + str(exit_code) + ")", "{report}"]
        return check_results.execute(self.root, command, inputs=["source.txt"], runtime=["dependency.txt"] if runtime else [], **kwargs)

    def test_profile_is_used_by_child_and_fingerprint_and_strict_keeps_role_input(self):
        with patch.dict(os.environ, {"CODEX_THREAD_ID": "camel", "CODEX_SESSION_ID": "synthetic-session-a", "OASIS_APP_SERVER_URL": "fixture-routing"}):
            recorded = self.record(environment_profile="role-neutral", extra="import os; assert 'CODEX_THREAD_ID' not in os.environ; assert 'CODEX_SESSION_ID' not in os.environ; assert 'OASIS_APP_SERVER_URL' not in os.environ; ")
            strict = self.record(extra="import os; assert os.environ['CODEX_THREAD_ID'] == 'camel'; assert os.environ['CODEX_SESSION_ID'] == 'synthetic-session-a'; ")
        with patch.dict(os.environ, {"CODEX_THREAD_ID": "cameleer", "CODEX_SESSION_ID": "synthetic-session-b", "OASIS_APP_SERVER_URL": "other-routing"}):
            self.assertEqual(check_results.reuse(recorded["receipt"], ["scope::passed"])["status"], "reusable")
            self.assertEqual(check_results.reuse(strict["receipt"], ["scope::passed"])["status"], "needs_check")
        with patch.dict(os.environ, {"CODEX_THREAD_ID": "camel", "CODEX_SESSION_ID": "synthetic-session-b", "OASIS_APP_SERVER_URL": "fixture-routing"}):
            strict_changed = check_results.review(strict["receipt"])
        self.assertEqual(strict_changed["fingerprint_changes"]["current"]["environment_keys"]["changed"], ["CODEX_SESSION_ID"])
        self.assertEqual(strict_changed["status"], "needs_check")
        for key in ("PATH", "PYTHONPATH", "TEST_CONSUMED_SETTING"):
            with self.subTest(key=key), patch.dict(os.environ, {key: os.environ.get(key, "") + ";changed"}):
                self.assertEqual(check_results.reuse(recorded["receipt"], ["scope::passed"])["status"], "needs_check")

    def test_unknown_and_supported_legacy_schema_never_guess_input_hashes(self):
        historical = self.root / "baseline.json"
        for value in ({"exit_code": 0}, {"schema_version": 0, "input_hashes": {}},
                      {"schema_version": 2, "phase": "recorded", "before": {}}):
            write_json(historical, value)
            with patch("oasis_harness.check_results.fingerprint", side_effect=AssertionError("No retrospective fingerprint")):
                result = check_results.review(historical, changes=True)
            self.assertEqual(result["status"], "needs_check")
            self.assertEqual(result["evidence_status"], "unknown")
            self.assertEqual(result["change_boundary"]["status"], "unknown")
        recorded = self.record()
        path = Path(recorded["receipt"])
        value = read_json(path); value["schema_version"] = 1; value.pop("environment_profile")
        write_json(path, value)
        self.assertEqual(check_results.review(path)["status"], "reusable")

    def test_original_scope_distinguishes_product_experience_and_protected_changes(self):
        (self.root / "experience.md").write_text("owned advice", encoding="utf-8")
        (self.root / "protected.txt").write_text("original contract", encoding="utf-8")
        (self.root / "unexpected.txt").write_text("unassigned", encoding="utf-8")
        recorded = self.record(scope=["source.txt", "experience.md", "protected.txt", "unexpected.txt", "new.py"],
                               product=["source.txt", "new.py"], experience=["experience.md"], protected=["protected.txt"])
        (self.root / "source.txt").write_text("implemented", encoding="utf-8")
        (self.root / "experience.md").write_text("useful lesson", encoding="utf-8")
        (self.root / "new.py").write_text("pass\n", encoding="utf-8")
        result = check_results.review(recorded["receipt"], changes=True)
        self.assertEqual(result["change_boundary"]["status"], "within_scope")
        self.assertEqual(result["change_boundary"]["changes"], {"product": ["new.py", "source.txt"], "experience": ["experience.md"], "protected": [], "unexpected": []})
        self.assertEqual(result["status"], "needs_check")  # Changed test input still invalidates baseline pass reuse.
        for name, group in (("protected.txt", "protected"), ("unexpected.txt", "unexpected")):
            (self.root / name).write_text("changed", encoding="utf-8")
            result = check_results.review(recorded["receipt"], changes=True)["change_boundary"]
            self.assertEqual(result["status"], "needs_review")
            self.assertIn(name, result["changes"][group])

    def test_invalid_change_declarations_stop_before_inventory_or_runner(self):
        command = [sys.executable, "-c", "pass", "{report}"]
        invalid = [
            ({"scope": ["tests"], "protected": [r"tests\test_case.py"]}, "--protect"),
            ({"scope": ["tests"], "protected": ["../outside"]}, "--protect"),
            ({"scope": ["tests"], "product": ["outside.py"]}, "--allow-product"),
            ({"scope": ["src"], "product": ["src"], "experience": ["src/knowledge.md"]}, "distinct ownership"),
            ({"scope": [str(self.root)]}, "--scope-input"),
        ]
        with patch("oasis_harness.check_results.fingerprint", side_effect=AssertionError("No fingerprint for an invalid declaration")), \
             patch("oasis_harness.check_results._scope_files", side_effect=AssertionError("No scope inventory")), \
             patch("oasis_harness.check_results.run", side_effect=AssertionError("No runner")):
            for declaration, message in invalid:
                with self.subTest(declaration=declaration), self.assertRaisesRegex(HarnessError, message):
                    check_results.execute(self.root, command, **declaration)
        self.assertFalse((self.root / ".oasis/local/checks").exists())

    def test_invalid_protected_path_explains_slashes_and_link_guards_remain(self):
        with self.assertRaisesRegex(HarnessError, r"--protect.*tests.*portable relative path.*'/'"):
            check_results._change_declaration(self.root, ["tests"], [], [], [r"tests\test_case.py"])
        with patch("oasis_harness.common.is_reparse", side_effect=lambda path: Path(path).name == "linked"):
            with self.assertRaisesRegex(HarnessError, r"--scope-input.*Linked"):
                check_results.execute(self.root, [sys.executable, "{report}"], scope=["linked"])

    def test_diagnostics_identify_actual_fields_and_environment_keys_without_values(self):
        with patch.dict(os.environ, {"CHECK_CONSUMED_SETTING": "private synthetic value"}):
            recorded = self.record(environment_profile="role-neutral")
            original = read_json(recorded["receipt"])
        with patch.dict(os.environ, {"CHECK_CONSUMED_SETTING": "different private value"}):
            result = check_results.review(recorded["receipt"])
        changed = result["fingerprint_changes"]["current"]
        self.assertEqual(changed["fields"], ["environment_sha256"])
        self.assertEqual(changed["environment_keys"]["changed"], ["CHECK_CONSUMED_SETTING"])
        self.assertEqual(result["status"], "needs_check")
        import json
        for data in (original, result):
            self.assertNotIn("private synthetic value", json.dumps(data))
            self.assertNotIn("different private value", json.dumps(data))
        with patch.dict(os.environ, {"CHECK_CONSUMED_SETTING": "private synthetic value"}), patch("oasis_harness.check_results.run", side_effect=AssertionError("No retry")):
            restored = check_results.review(recorded["receipt"])
        self.assertEqual(restored["status"], "reusable")
        self.assertEqual(restored["whole_run_exit_code"], 1)

    def test_legacy_environment_details_remain_unknown_without_retrospective_writes(self):
        recorded = self.record()
        path = Path(recorded["receipt"])
        value = read_json(path)
        for phase in ("before", "after"):
            value[phase].pop("environment_key_digests")
        write_json(path, value)
        original = path.read_bytes()
        self.assertEqual(check_results.review(path)["status"], "reusable")
        with patch.dict(os.environ, {"CHECK_NEW_KEY": "sensitive synthetic value"}):
            result = check_results.review(path)
        self.assertEqual(result["status"], "needs_check")
        self.assertEqual(result["fingerprint_changes"]["current"]["fields"], ["environment_sha256"])
        self.assertEqual(result["fingerprint_changes"]["current"]["environment_keys"]["status"], "unknown")
        self.assertEqual(path.read_bytes(), original)

    def test_runtime_source_and_host_changes_are_not_blended_with_environment(self):
        recorded = self.record()
        (self.root / "dependency.txt").write_text("changed dependency")
        (self.root / "source.txt").write_text("changed source")
        result = check_results.review(recorded["receipt"])
        self.assertEqual(result["fingerprint_changes"]["current"]["fields"], ["inputs", "runtime_inputs"])
        self.assertEqual(result["status"], "needs_check")
        self.assertEqual(result["fingerprint_changes"]["current"]["details"]["runtime_inputs"]["changed"], [str((self.root / "dependency.txt").resolve())])
        snapshot = read_json(recorded["receipt"])["after"]
        changed = dict(snapshot, host_runtime={**snapshot["host_runtime"], "optimize": 1})
        difference = check_results.fingerprint_changes(snapshot, changed)
        self.assertEqual(difference["fields"], ["host_runtime"])
        self.assertEqual(difference["details"]["host_runtime"]["changed"], ["optimize"])

    def test_compact_consumer_keeps_counts_nonpassing_cases_and_original_artifact_refs(self):
        recorded = self.record()
        result = check_results.summary_view(check_results.review(recorded["receipt"]))
        self.assertNotIn("cases", result)
        self.assertEqual(result["selected_case_counts"]["passed"], 1)
        self.assertEqual(result["case_counts"]["failure"], 1)
        self.assertEqual(result["whole_run_exit_code"], 1)
        self.assertEqual(result["other_nonpassing_cases"], {"scope::failed": "failure"})
        self.assertEqual(Path(result["artifacts"]["report"]["path"]).read_bytes(), (Path(recorded["receipt"]).parent / "report.xml").read_bytes())
        self.assertIn("original whole exit 1", result["summary"])

    def test_role_neutral_installed_producer_consumer_are_separate_processes(self):
        from oasis_harness import installation
        payload = installation.package_files(Path(__file__).resolve().parents[1])
        for name, data in payload.items():
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        marker = self.root / ".oasis/local/runner-count.txt"
        command = [sys.executable, "-B", "-X", "utf8", "-c",
            "import os,sys; from pathlib import Path; assert 'CODEX_THREAD_ID' not in os.environ; assert 'CODEX_SESSION_ID' not in os.environ; "
            "p=Path('.oasis/local/runner-count.txt'); p.write_text(p.read_text()+'x' if p.exists() else 'x'); "
            "Path(sys.argv[1]).write_text('<testsuite><testcase classname=\"s\" name=\"pass\"/><testcase classname=\"s\" name=\"fail\"><failure/></testcase></testsuite>'); sys.exit(1)", "{report}"]
        cli = [sys.executable, "-B", "-X", "utf8", str(self.root / "tools/oasis.py"), "check"]
        env = os.environ.copy(); env.update(CODEX_THREAD_ID="producer", CODEX_SESSION_ID="synthetic-session-a", OASIS_APP_SERVER_URL="producer-route", CHECK_CONSUMED_SETTING="configured test input")
        produced = subprocess.run([*cli, "run", "--root", str(self.root), "--input", "source.txt", "--runtime-input", "dependency.txt", "--environment-profile", "role-neutral", "--", *command],
                                  cwd=self.root, env=env, capture_output=True, timeout=15)
        self.assertEqual(produced.returncode, 1)
        receipt = next((self.root / ".oasis/local/checks").glob("*/receipt.json"))
        env.update(CODEX_THREAD_ID="consumer", CODEX_SESSION_ID="synthetic-session-b", OASIS_APP_SERVER_URL="consumer-route")
        import json
        consumer = subprocess.run([*cli, "review", "--receipt", str(receipt), "--case", "s::pass"], cwd=self.root, env=env, capture_output=True, timeout=15)
        self.assertEqual(consumer.returncode, 0, consumer.stderr)
        result = json.loads(consumer.stdout)
        self.assertEqual(result["status"], "reusable")
        self.assertEqual(result["whole_run_exit_code"], 1)
        self.assertEqual(result["other_nonpassing_cases"], {"s::fail": "failure"})
        self.assertEqual(marker.read_text(), "x")
        env["CHECK_CONSUMED_SETTING"] = "changed test input"
        changed_setting = subprocess.run([*cli, "review", "--receipt", str(receipt), "--case", "s::pass", "--summary"], cwd=self.root, env=env, capture_output=True, timeout=15)
        diagnosed = json.loads(changed_setting.stdout)
        self.assertEqual(diagnosed["status"], "needs_check")
        self.assertEqual(diagnosed["fingerprint_changes"]["current"]["environment_keys"]["changed"], ["CHECK_CONSUMED_SETTING"])
        env["CHECK_CONSUMED_SETTING"] = "configured test input"
        matched = subprocess.run([*cli, "review", "--receipt", str(receipt), "--case", "s::pass", "--summary"], cwd=self.root, env=env, capture_output=True, timeout=15)
        self.assertEqual(json.loads(matched.stdout)["status"], "reusable")
        self.assertEqual(marker.read_text(), "x")
        # The installed consumer hashes the actual runner and runtime, rather than ignoring them.
        env["PYTHONPATH"] = str(self.root / "other-imports")
        changed = subprocess.run([*cli, "review", "--receipt", str(receipt), "--case", "s::pass"], cwd=self.root, env=env, capture_output=True, timeout=15)
        self.assertEqual(json.loads(changed.stdout)["status"], "needs_check")
        self.assertEqual(marker.read_text(), "x")

    def test_protected_change_blocks_review_even_with_reusable_test_inputs(self):
        (self.root / "protected.txt").write_text("contract", encoding="utf-8")
        recorded = self.record(scope=["source.txt", "protected.txt"], product=["source.txt"], protected=["protected.txt"])
        (self.root / "protected.txt").write_text("unauthorized", encoding="utf-8")
        result = check_results.review(recorded["receipt"], changes=True)
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["check_status"], "reusable")
        self.assertEqual(result["change_boundary"]["changes"]["protected"], ["protected.txt"])

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
