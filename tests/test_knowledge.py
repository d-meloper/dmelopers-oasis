import copy
from pathlib import Path
import shutil
import tempfile
import unittest

from oasis_harness.common import HarnessError, digest, read_json, write_json
from oasis_harness import knowledge

PACKAGE = Path(__file__).resolve().parents[1]


def example():
    return {"schema_version": 1, "id": "unicode-receipt", "classification": "windows",
            "problem": "A receipt path was decoded differently across supported hosts.",
            "observed": ["The legacy host rejected the decoded path."],
            "hypotheses": ["An implicit decoding default caused the difference."],
            "evidence": [{"label": "isolated-reproduction", "sha256": "a" * 64, "scope": "fixture on declared hosts"}],
            "delta": "Specify UTF-8 when reading the receipt and repeat the host fixture.",
            "conditions": "Supported Windows shells reading UTF-8 receipts.",
            "impact": "Existing receipt schema and ownership are preserved.",
            "tests": [{"case": "unicode-roundtrip", "outcome": "pass", "boundary": "fixture", "evidence_sha256": "b" * 64}],
            "canonical_rule": "BestPractice/Encoding.md", "change_kind": "knowledge",
            "status": "evaluated", "limits": ["Actual application adoption was not observed."]}


class KnowledgeContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="oasis-knowledge-")
        self.root = Path(self.temp.name) / "project"
        shutil.copytree(PACKAGE / "seed", self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_capture_is_immutable_and_does_not_adopt_rule(self):
        result = knowledge.capture(self.root, example())
        self.assertFalse(result["adopted_rule"])
        self.assertFalse((self.root / "BestPractice/Encoding.md").exists())
        path = self.root / "BestPractice/history/unicode-receipt.json"
        before = path.read_bytes()
        with self.assertRaisesRegex(HarnessError, "already exists"):
            knowledge.capture(self.root, example())
        self.assertEqual(path.read_bytes(), before)

    def test_hypothesis_alone_and_fake_performed_proof_rejected(self):
        case = example()
        case["observed"] = []
        with self.assertRaises(HarnessError):
            knowledge.validate_case(case)
        case = example()
        case["tests"][0]["evidence_sha256"] = None
        with self.assertRaisesRegex(HarnessError, "evidence digest"):
            knowledge.validate_case(case)

    def test_static_pass_is_not_adoption(self):
        case = example()
        case["status"] = "adopted"
        with self.assertRaisesRegex(HarnessError, "do not establish adoption"):
            knowledge.validate_case(case)
        case["tests"][0]["boundary"] = "semantic"
        self.assertEqual(knowledge.validate_case(case)["semantic_authority_review"], "required")

    def test_private_material_blocked_without_echo(self):
        for private in ("C:" + r"\Users\person\private.log", "person@example.invalid", "token=synthetic-test-value", "Bearer fixture-key", "https://example.invalid/private", "12345678-1234-1234-1234-123456789abc"):
            case = example()
            case["observed"] = [private]
            with self.assertRaises(HarnessError) as raised:
                knowledge.validate_case(case)
            self.assertNotIn(private, str(raised.exception))

    def test_core_intrusion_requires_decision_and_cannot_self_adopt(self):
        case = example()
        case["delta"] = "Calf may send directly to Cameleer after finishing."
        self.assertTrue(knowledge.validate_case(case)["requires_owner_decision"])
        case["status"] = "adopted"
        case["tests"][0]["boundary"] = "semantic"
        with self.assertRaisesRegex(HarnessError, "cannot self-declare"):
            knowledge.validate_case(case)
        case = example()
        case["change_kind"] = "new-skill"
        self.assertTrue(knowledge.validate_case(case)["requires_owner_decision"])

    def test_export_requires_owner_request_and_is_local_only(self):
        output = Path(self.temp.name) / "handoff.json"
        with self.assertRaisesRegex(HarnessError, "explicit owner request"):
            knowledge.prepare_export(self.root, example(), output)
        self.assertFalse(output.exists())
        result = knowledge.prepare_export(self.root, example(), output, owner_requested=True)
        self.assertFalse(result["sent"])
        self.assertFalse(result["imported"])
        self.assertEqual(read_json(output)["state"], "prepared-local-not-sent-not-imported")
        before = output.read_bytes()
        with self.assertRaisesRegex(HarnessError, "destination exists"):
            knowledge.prepare_export(self.root, example(), output, owner_requested=True)
        self.assertEqual(output.read_bytes(), before)

    def test_project_specific_export_and_project_name_contamination(self):
        case = example()
        case["classification"] = "project"
        with self.assertRaisesRegex(HarnessError, "Project-specific"):
            knowledge.prepare_export(self.root, case, Path(self.temp.name) / "a.json", True)
        value = read_json(self.root / ".oasis/project.json")
        value["name"] = "Private Project Fixture"
        write_json(self.root / ".oasis/project.json", value)
        case = example()
        case["problem"] += " Private Project Fixture failed."
        with self.assertRaisesRegex(HarnessError, "contamination"):
            knowledge.prepare_export(self.root, case, Path(self.temp.name) / "b.json", True)

    def test_unknown_and_failed_cases_remain_raw(self):
        case = example()
        case["tests"].append({"case": "live-observation", "outcome": "not-run", "boundary": "live", "evidence_sha256": None})
        case["tests"][0]["outcome"] = "fail"
        original = copy.deepcopy(case)
        knowledge.validate_case(case)
        self.assertEqual(case, original)
        self.assertIn("not independently verified", knowledge.validate_case(case)["proof"])

    def test_extra_approval_fields_cannot_create_authority(self):
        case = example()
        case["approved"] = True
        with self.assertRaisesRegex(HarnessError, "unknown/missing fields"):
            knowledge.validate_case(case)


if __name__ == "__main__":
    unittest.main()
