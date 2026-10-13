from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from oasis_harness.common import HarnessError, digest
from tools.source_policy import (
    NEUTRAL_PROJECT, review_policy, scan_harness_file,
    validate_harness_directory, validate_harness_distribution,
)


PACKAGE = Path(__file__).resolve().parents[1]


def fixture():
    files = {}
    for folder in ("seed", "library", "docs", "oasis_harness"):
        for path in sorted((PACKAGE / folder).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                files[path.relative_to(PACKAGE).as_posix()] = path.read_bytes()
    for name in ("README.md", "AGENTS.md", "oasis.py", ".gitignore", ".gitattributes"):
        files[name] = (PACKAGE / name).read_bytes()
    files["assets/readme-hero.png"] = (PACKAGE / "assets/readme-hero.png").read_bytes()
    # These source modules contain the reviewed scanner patterns or native
    # metadata field names. No folder-wide or hard-secret waiver is permitted.
    reviewed = {
        name: {"sha256": digest(files[name]),
               "reason": "Fixture review of bounded scanner patterns and metadata field names; no live host data."}
        for name in ("oasis_harness/knowledge.py", "oasis_harness/publication.py",
                     "oasis_harness/sessions.py", "oasis_harness/workflows.py")
    }
    return files, reviewed


class PublicSourceContracts(unittest.TestCase):
    def test_only_the_exact_owner_supplied_readme_png_is_allowed(self):
        name = "assets/readme-hero.png"
        data = (PACKAGE / name).read_bytes()
        self.assertEqual(scan_harness_file(name, data)["classification"], "readme-image")
        changed = data + b"Unreviewed metadata"
        # Even an exact-byte soft review cannot authorize changed binary data.
        with self.assertRaisesRegex(HarnessError, "README image byte hash drift"):
            scan_harness_file(name, changed, {name: {"sha256": digest(changed), "reason": "Not image authority"}})
        with self.assertRaises(HarnessError):
            scan_harness_file("assets/other.png", data)
        files, reviewed = fixture()
        del files[name]
        with self.assertRaisesRegex(HarnessError, "missing source"):
            validate_harness_distribution(files, reviewed)

    def test_complete_neutral_distribution_and_pinned_regular_inventory(self):
        files, reviewed = fixture()
        hashes = {name: digest(data) for name, data in files.items()}
        modes = {name: "100644" for name in files}
        modes["oasis.py"] = "100755"
        result = validate_harness_distribution(files, reviewed, expected_hashes=hashes, modes=modes)
        self.assertEqual((result["default_skills"], result["optional_skills"]), (10, 15))
        self.assertTrue(result["modes_verified"])
        self.assertFalse(result["authority_verified"])
        self.assertEqual(result["files"]["oasis.py"]["mode"], "100755")

    def test_review_does_not_override_real_secrets_personal_bytes_or_private_paths(self):
        payloads = [
            ("credential token", b"ghp_" + b"Ab123456789" * 4),
            ("credential URL", b"https://" + b"fixture:fixture-password@" + b"github.com/repo"),
            ("personal email", b"fixture-person" + b"@private.example.org"),
            ("personal host path", b"C:" + b"\\Users\\FixturePerson\\private-note"),
            ("private key body", b"-----BEGIN " + b"PRIVATE KEY-----\n" + b"Ab12+/=" * 12),
            ("credential literal", b"api_key" + b' = "unrecognized-private-material"'),
        ]
        for label, data in payloads:
            with self.subTest(label=label):
                reviewed = {"docs/fixture.md": {"sha256": digest(data), "reason": "Exact bytes reviewed; this cannot authorize secrets."}}
                with self.assertRaises(HarnessError) as error:
                    scan_harness_file("docs/fixture.md", data, reviewed)
                self.assertNotIn(data.decode(), str(error.exception))
        for name in (".oasis/local/note.md", ".agents/skills/oasis-calf/SKILL.md",
                     "docs/.env.example", "seed/.oasis/backup.json", "docs/credentials.json",
                     "seed/.agents/skills/oasis-unapproved/SKILL.md", "private/report.md"):
            with self.subTest(name=name), self.assertRaises(HarnessError):
                scan_harness_file(name, b"neutral", {name: {"sha256": digest(b"neutral"), "reason": "Not path authority."}})

    def test_exact_byte_review_for_scanner_literals_and_stale_review_rejection(self):
        data = b"Pattern example: " + b"/Users/[^/]+/"
        with self.assertRaises(HarnessError):
            scan_harness_file("docs/scanner.md", data)
        reviewed = {"docs/scanner.md": {"sha256": digest(data), "reason": "Only a literal rejection regex, not a concrete host path."}}
        self.assertTrue(scan_harness_file("docs/scanner.md", data, reviewed)["reviewed_exception"])
        with self.assertRaisesRegex(HarnessError, "hash drift"):
            scan_harness_file("docs/scanner.md", data + b" changed", reviewed)
        for bad in ({"sha256": digest(data), "reason": "", "nonce": "approved"},
                    {"sha256": digest(data), "reason": "Reviewed", "approved": True},
                    {"sha256": "not-a-hash", "reason": "Reviewed"}):
            with self.subTest(bad=bad), self.assertRaises(HarnessError):
                review_policy({"docs/scanner.md": bad})

    def test_only_reserved_email_examples_and_one_service_literal_are_permitted(self):
        scan_harness_file("docs/example.md", b"fixture" + b"@example.invalid")
        scan_harness_file("docs/example.md", b"publication" + b"@users.noreply.github.com")
        for address in (b"other" + b"@users.noreply.github.com", b"fixture" + b"@example.com",
                        b"fixture" + b"@evil.invalid.example.org"):
            with self.subTest(address=address), self.assertRaises(HarnessError):
                scan_harness_file("docs/example.md", address)

    def test_core_and_unbound_project_templates_cannot_be_waived(self):
        data = (PACKAGE / "seed/.oasis/core.json").read_bytes()
        core = json.loads(data)
        core["routing"]["owner_relay"] = "automatic"
        changed = json.dumps(core).encode()
        with self.assertRaisesRegex(HarnessError, "core template drift"):
            scan_harness_file("seed/.oasis/core.json", changed,
                              {"seed/.oasis/core.json": {"sha256": digest(changed), "reason": "Not core approval."}})
        for change in ({"git": {"profile": "single-main"}}, {"name": "Selected project"},
                       {"publication": {"configured": True}}, {"backup": {"configured": 0}}):
            project = {**NEUTRAL_PROJECT, **change}
            with self.subTest(change=change), self.assertRaisesRegex(HarnessError, "selected or bound"):
                scan_harness_file("seed/.oasis/project.json", json.dumps(project).encode())

    def test_duplicate_neutral_json_keys_and_hard_credential_encodings_block(self):
        neutral = json.dumps(NEUTRAL_PROJECT).encode()
        duplicate = neutral.replace(b'"name": ""', b'"name": "private selection", "name": ""')
        with self.assertRaisesRegex(HarnessError, "invalid neutral project JSON"):
            scan_harness_file("seed/.oasis/project.json", duplicate)
        for data in (b"postgresql://" + b"fixture:private-password@" + b"localhost/database",
                     b"-----BEGIN " + b"ENCRYPTED PRIVATE KEY-----\\n" + b"Ab12+/=" * 12,
                     b"AWS_SECRET_ACCESS_KEY" + b' = "private-key-material-without-standard-prefix"'):
            policy = {"docs/fixture.md": {"sha256": digest(data), "reason": "Never credential authority."}}
            with self.subTest(payload_sha256=digest(data)), self.assertRaises(HarnessError):
                scan_harness_file("docs/fixture.md", data, policy)

    def test_complete_snapshot_hashes_missing_members_and_modes_are_not_assumed(self):
        files, reviewed = fixture()
        hashes = {name: digest(data) for name, data in files.items()}
        changed = dict(files)
        changed["README.md"] += b"\nNeutral edited bytes.\n"
        with self.assertRaisesRegex(HarnessError, "byte hash drift"):
            validate_harness_distribution(changed, reviewed, expected_hashes=hashes)
        del changed["seed/.agents/skills/oasis-harness-doctor/references/workflow.md"]
        with self.assertRaises(HarnessError):
            validate_harness_distribution(changed, reviewed, expected_hashes=hashes)
        with self.assertRaisesRegex(HarnessError, "skill reference"):
            validate_harness_distribution(changed, reviewed)
        modes = {name: "100644" for name in files}
        modes["README.md"] = "120000"
        with self.assertRaisesRegex(HarnessError, "non-regular"):
            validate_harness_distribution(files, reviewed, modes=modes)
        modes["README.md"] = "100644"
        del modes["README.md"]
        with self.assertRaises(HarnessError):
            validate_harness_distribution(files, reviewed, modes=modes)
        self.assertFalse(validate_harness_distribution(files, reviewed)["modes_verified"])
        modes["README.md"] = {"mode": "100644"}
        with self.assertRaises(HarnessError):
            validate_harness_distribution(files, reviewed, modes=modes)

    def test_colliding_case_directories_file_prefixes_and_unknown_members_block(self):
        files, reviewed = fixture()
        for extra in ({"docs/Example/a.md": b"neutral", "docs/example/b.md": b"neutral"},
                      {"README.md/child.md": b"neutral"}, {"readme.md": b"neutral"},
                      {"seed/.oasis/receipts/operation.md": b"neutral"}):
            with self.subTest(extra=extra), self.assertRaises(HarnessError):
                validate_harness_distribution({**files, **extra}, reviewed)

    def test_missing_or_renamed_skill_metadata_cannot_claim_25_definitions(self):
        files, reviewed = fixture()
        for name in ("seed/.agents/skills/oasis-calf/agents/openai.yaml",
                     "library/oasis-review/capability.json"):
            changed = dict(files)
            del changed[name]
            with self.subTest(name=name), self.assertRaisesRegex(HarnessError, "required skill"):
                validate_harness_distribution(changed, reviewed)
        changed = dict(files)
        name = "library/oasis-review/SKILL.md"
        changed[name] = changed[name].replace(b"name: oasis-review", b"name: oasis-unknown")
        with self.assertRaisesRegex(HarnessError, "skill identity"):
            validate_harness_distribution(changed, reviewed)

    def test_directory_checks_include_unexpected_members_and_reparse_points(self):
        files, reviewed = fixture()
        with tempfile.TemporaryDirectory(prefix="oasis-public-source-") as temporary:
            root = Path(temporary)
            for name, data in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            validate_harness_directory(root, reviewed)
            private = root / ".oasis/local/private.md"
            private.parent.mkdir(parents=True)
            private.write_bytes(b"not ignored by snapshot checker")
            with self.assertRaises(HarnessError):
                validate_harness_directory(root, reviewed)
            with patch("tools.source_policy.is_reparse", side_effect=lambda path: Path(path) == root / "seed"):
                with self.assertRaisesRegex(HarnessError, "linked source"):
                    validate_harness_directory(root, reviewed)


if __name__ == "__main__":
    unittest.main()
