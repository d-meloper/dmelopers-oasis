"""Scoped terminal notices: no ACKs, polling turns or behavioral packets."""
from pathlib import Path
import tempfile
import unittest

from oasis_harness import workflows
from oasis_harness.common import HarnessError, read_json, run
from tests.test_sessions import NativeFixture


class DependencyContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.native = NativeFixture(self.root)
        self.native.add("producer", name="Arbitrary producer name")
        self.native.add("consumer", name="Arbitrary consumer name")

    def wait(self, **kwargs):
        return workflows.dependency_wait(self.root, "producer", "consumer", "shared parser interface", **kwargs)

    def test_wait_is_local_and_ends_turn_without_messages_or_status_queries(self):
        first = self.wait()
        second = self.wait()
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(first["end_turn"])
        self.assertEqual(first["phase"], "waiting")
        self.assertEqual(self.native.calls, [])
        self.assertTrue((self.root / ".oasis/state/tasks.md").exists())

    def test_self_dependency_and_request_conflicts_are_local_errors(self):
        with self.assertRaisesRegex(HarnessError, "different producer"):
            workflows.dependency_wait(self.root, "producer", "producer", "same-chat")
        self.wait(request_id="fixed")
        with self.assertRaisesRegex(HarnessError, "different inputs"):
            workflows.dependency_wait(self.root, "producer", "caller", "Different condition", request_id="fixed")
        self.assertEqual(self.native.calls, [])

    def test_cycle_is_an_advisory_summary_warning_without_native_queries(self):
        first = self.wait()
        second = workflows.dependency_wait(self.root, "consumer", "producer", "second partial result")
        summary = workflows.task_status(self.root, summary=True)
        warning = summary["warnings"][0]
        self.assertTrue(warning["advisory_only"])
        self.assertEqual(set(warning["dependency_ids"]), {first["id"], second["id"]})
        self.assertEqual(self.native.calls, [])

    def test_terminal_dependency_with_lost_notice_stays_in_compact_status(self):
        row = self.wait()
        self.native.lose["turn/start"] = 1
        with self.assertRaises(HarnessError):
            workflows.dependency_finish(self.root, row["id"], result="saved", factory=self.native)
        pending = workflows.task_status(self.root, summary=True)["dependencies"][0]
        self.assertEqual(pending["phase"], "completed")
        self.assertEqual(pending["terminal_notice"]["state"], "uncertain")
        self.assertEqual(pending["terminal_notice"]["resume"]["command"], "workflow dependency-finish")
        workflows.dependency_finish(self.root, row["id"], factory=self.native)
        self.assertEqual(workflows.task_status(self.root, summary=True)["dependencies"], [])

    def test_cross_project_notice_is_not_sent_and_wait_table_updates(self):
        task = workflows.assign(self.root, "caller", "Use partial interface", factory=self.native)
        row = workflows.dependency_wait(self.root, "producer", task["camel_thread_id"], "interface")
        table = self.root / ".oasis/state/tasks.md"
        self.assertIn("waiting for interface", table.read_text(encoding="utf-8"))
        self.native.threads[task["camel_thread_id"]]["projectId"] = "OTHER"
        sent = self.native.sent
        with self.assertRaisesRegex(HarnessError, "another project"):
            workflows.dependency_finish(self.root, row["id"], result="private result", factory=self.native)
        self.assertEqual(self.native.sent, sent)
        self.assertNotIn("waiting for interface", table.read_text(encoding="utf-8"))

    def test_only_scoped_terminal_notice_resumes_consumer_once(self):
        row = self.wait()
        unrelated = self.root / "ongoing-producer-work.txt"
        unrelated.write_text("still working\n", encoding="utf-8")
        actual = workflows.dependency_finish(self.root, row["id"], result="interface-commit", factory=self.native)
        repeated = workflows.dependency_finish(self.root, row["id"], result="ignored-duplicate", factory=self.native)
        self.assertEqual(actual["phase"], "completed")
        self.assertEqual(actual["delivery"]["thread_id"], "consumer")
        self.assertEqual(repeated["delivery"]["turn_id"], actual["delivery"]["turn_id"])
        self.assertEqual(self.native.sent, 1)
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "still working\n")
        content = self.native.threads["consumer"]["turns"][0]["items"][0]["content"][0]["text"]
        self.assertIn("shared parser interface", content)
        self.assertIn("interface-commit", content)
        self.assertNotIn("ACK", content)

    def test_failure_and_cancellation_are_terminal_notices(self):
        for outcome in ("failed", "cancelled"):
            row = self.wait(request_id=outcome)
            actual = workflows.dependency_finish(self.root, row["id"], outcome=outcome, result="Scoped part ended", factory=self.native)
            self.assertEqual(actual["phase"], outcome)
            self.assertEqual(actual["delivery"]["state"], "accepted")
            workflows.dependency_finish(self.root, row["id"], outcome=outcome, factory=self.native)
        self.assertEqual(self.native.sent, 2)

    def test_lost_notice_response_retains_boundary_and_recovers_without_replay(self):
        for outcome in ("completed", "failed", "cancelled"):
            row = self.wait(request_id=outcome)
            self.native.lose["turn/start"] = 1
            with self.assertRaises(HarnessError):
                workflows.dependency_finish(self.root, row["id"], outcome=outcome, result="saved-result", factory=self.native)
            retained = next(item for item in read_json(self.root / ".oasis/local/tasks/state.json")["dependencies"] if item["id"] == row["id"])
            self.assertEqual(retained["phase"], outcome)
            self.assertEqual(retained["result"], "saved-result")
            self.assertEqual(workflows.dependency_finish(self.root, row["id"], outcome=outcome, factory=self.native)["delivery"]["state"], "accepted")
            workflows.dependency_finish(self.root, row["id"], outcome=outcome, factory=self.native)
        self.assertEqual(self.native.sent, 3)

    def test_notice_format_and_names_are_unrestricted(self):
        row = workflows.dependency_wait(self.root, "producer", "caller", "필요한 인터페이스")
        actual = workflows.dependency_finish(self.root, row["id"], message="끝났습니다. 저장한 결과를 사용하세요.", factory=self.native)
        self.assertEqual(actual["delivery"]["thread_id"], "caller")
        self.assertEqual(self.native.sent, 1)

    def test_input_errors_and_removed_packet_cli(self):
        with self.assertRaises(HarnessError):
            workflows.dependency_wait(self.root, "producer", "consumer", "")
        with self.assertRaises(HarnessError):
            workflows.dependency_finish(self.root, "unknown", factory=self.native)
        import sys
        launcher = Path(__file__).resolve().parents[1] / "oasis.py"
        result = run([sys.executable, "-B", "-X", "utf8", str(launcher), "--help"])
        self.assertNotIn("packet", result.stdout)
        result = run([sys.executable, "-B", "-X", "utf8", str(launcher), "packet", "unused.json"], check=False)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
