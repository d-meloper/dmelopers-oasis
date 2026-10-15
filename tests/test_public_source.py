from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from oasis_harness.common import HarnessError, digest, run
from tools import check_public_source
from tools.source_policy import (
    NEUTRAL_PROJECT, README_SVGS, review_policy, scan_harness_file,
    validate_harness_directory, validate_harness_distribution,
)


PACKAGE = Path(__file__).resolve().parents[1]


def fixture():
    files = {}
    for folder in ("seed", "library", "docs", "oasis_harness"):
        for path in sorted((PACKAGE / folder).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                # This fixture represents the public Git projection. The source
                # text attributes export LF even when unchanged Windows working
                # files contain CRLF; the pinned binary/-text artwork is read below.
                files[path.relative_to(PACKAGE).as_posix()] = path.read_bytes().replace(b"\r\n", b"\n")
    for name in ("README.md", "AGENTS.md", "oasis.py", ".gitignore", ".gitattributes"):
        files[name] = (PACKAGE / name).read_bytes()
    files["assets/readme-hero.png"] = (PACKAGE / "assets/readme-hero.png").read_bytes()
    for name in README_SVGS:
        files[name] = (PACKAGE / name).read_bytes()
    # These source modules contain the reviewed scanner patterns or native
    # metadata field names. No folder-wide or hard-secret waiver is permitted.
    reviewed = {
        name: {"sha256": digest(files[name]),
               "reason": "Fixture review of bounded scanner patterns and metadata field names; no live host data."}
        for name in ("oasis_harness/check_results.py", "oasis_harness/knowledge.py", "oasis_harness/publication.py",
                     "oasis_harness/sessions.py", "oasis_harness/workflows.py")
    }
    return files, reviewed


class PublicSourceContracts(unittest.TestCase):
    def test_index_candidate_batch_preserves_binary_unicode_and_empty_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run(["git", "-C", str(root), "init", "--quiet"])
            payload = {".gitattributes": b"* -text\n", "empty.txt": b"",
                       "sample.bin": bytes(range(256)), "메모 😶.txt": "한글\r\n".encode("utf-8")}
            for name, data in payload.items():
                (root / name).write_bytes(data)
            run(["git", "-C", str(root), "add", "--", *payload])
            import subprocess
            with patch("subprocess.run", wraps=subprocess.run) as invoked:
                files, modes = check_public_source.candidate(root, index=True)
            self.assertEqual(files, payload)
            self.assertEqual(set(modes.values()), {"100644"})
            object_reads = [call for call in invoked.call_args_list if "cat-file" in call.args[0]]
            self.assertLess(len(object_reads), len(payload))

    def scan_pinned_svg_fixture(self, data, *, reviewed=None):
        name = "assets/readme-title.svg"
        with patch.dict("tools.source_policy.README_SVGS", {name: digest(data)}):
            return scan_harness_file(name, data, reviewed)

    def test_only_two_exact_source_svg_assets_are_permitted(self):
        self.assertEqual(set(README_SVGS), {"assets/readme-title.svg", "assets/readme-hero.svg"})
        for name in README_SVGS:
            data = (PACKAGE / name).read_bytes()
            with self.subTest(name=name):
                result = scan_harness_file(name, data)
                self.assertEqual(result["classification"], "readme-svg")
                self.assertFalse(result["authority_verified"])
                changed = data + b"\n<!-- Unreviewed bytes -->\n"
                with self.assertRaisesRegex(HarnessError, "SVG byte hash drift"):
                    scan_harness_file(name, changed, {name: {"sha256": digest(changed), "reason": "Not artwork authority"}})
                with self.assertRaises(HarnessError):
                    scan_harness_file("assets/unapproved.svg", data)

    def test_svg_xml_safety_is_checked_beyond_the_pin(self):
        start = b'<svg xmlns="http://www.w3.org/2000/svg"'
        payloads = {
            "script": start + b'><script>alert(1)</script></svg>',
            "event": start + b' onload="alert(1)"></svg>',
            "foreign-object": start + b'><foreignObject><div>HTML</div></foreignObject></svg>',
            "external-image": start + b'><image href="https://fixture.invalid/image.png"/></svg>',
            "external-stroke": start + b'><path stroke="url(https://fixture.invalid/paint)" d="M0 0H1"/></svg>',
            "dynamic-stroke": start + b'><path stroke="var(--paint)" d="M0 0H1"/></svg>',
            "dynamic-stroke-width": start + b'><path stroke-width="calc(1 + 2)" d="M0 0H1"/></svg>',
            "negative-stroke-width": start + b'><path stroke-width="-1" d="M0 0H1"/></svg>',
            "invalid-stroke-join": start + b'><path stroke-linejoin="url(#paint)" d="M0 0H1"/></svg>',
            "external-clip": start + b'><g clip-path="url(https://fixture.invalid/clip)"/></svg>',
            "relative-clip": start + b'><g clip-path="url(other.svg#clip)"/></svg>',
            "encoded-external-clip": start + b'><g clip-path="url(&#104;ttps://fixture.invalid/clip)"/></svg>',
            "xml-base": start + b' xml:base="https://fixture.invalid/"></svg>',
            "import-css": start + b'><style>@import "https://fixture.invalid/style.css";</style></svg>',
            "url-css": start + b'><style>.title { fill: url(https://fixture.invalid/fill); }</style></svg>',
            "escaped-css": start + b'><style>.title { fill: u\\72l(https://fixture.invalid/fill); }</style></svg>',
            "animation": start + b'><animate attributeName="fill"/></svg>',
            "malformed-xml": start + b'><g></svg>',
            "not-svg-root": b'<html xmlns="http://www.w3.org/2000/svg"/>',
            "foreign-namespace": start + b'><g xmlns="https://fixture.invalid/foreign"/></svg>',
            "invalid-encoding": start + b'><title>\xff</title></svg>',
            "non-utf8-declaration": b'<?xml version="1.0" encoding="ISO-8859-1"?>' + start + b'/>',
            "stylesheet-instruction": b'<?xml-stylesheet href="https://fixture.invalid/style.css"?>' + start + b'/>',
            "dtd": b'<!DOCTYPE svg [<!ENTITY text "expanded">]>' + start + b'><text>&text;</text></svg>',
            "duplicate-id": start + b'><title id="same"/><desc id="same"/></svg>',
            "missing-clip": start + b'><g clip-path="url(#missing)"/></svg>',
        }
        name = "assets/readme-title.svg"
        for label, data in payloads.items():
            policy = {name: {"sha256": digest(data), "reason": "Synthetic negative case; cannot waive XML safety"}}
            with self.subTest(label=label), self.assertRaises(HarnessError):
                self.scan_pinned_svg_fixture(data, reviewed=policy)

    def test_svg_static_media_css_and_resolved_internal_clip_are_supported(self):
        data = b'''<svg xmlns="http://www.w3.org/2000/svg" aria-labelledby="title">
<title id="title">Static fixture</title><defs><clipPath id="clip"><path d="M0 0H10V10Z"/></clipPath></defs>
<style>.title { fill: #fff; } @media (prefers-color-scheme: dark) { .title { fill: #000; } }</style>
<g clip-path="url(#clip)"><text class="title" x="1" y="1">Plain text</text></g></svg>'''
        self.assertEqual(self.scan_pinned_svg_fixture(data)["classification"], "readme-svg")

    def test_new_root_guide_is_an_exact_mandatory_source_member(self):
        files, reviewed = fixture()
        name = "seed/LocalGitWorkflow.md"
        self.assertEqual(scan_harness_file(name, files[name])["classification"], "seed-guidance")
        for required in {name, *README_SVGS}:
            changed = dict(files)
            del changed[required]
            with self.subTest(required=required), self.assertRaisesRegex(HarnessError, "missing source"):
                validate_harness_distribution(changed, reviewed)
        with self.assertRaises(HarnessError):
            scan_harness_file("seed/OtherGitGuide.md", b"Unapproved guidance")

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
        self.assertEqual((result["default_skills"], result["optional_skills"]), (9, 15))
        self.assertEqual(result["core_version"], "2.0.0")
        self.assertEqual(result["active_skills"], 24)
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

    def test_core_metadata_is_not_sealed_and_project_template_stays_unbound(self):
        data = (PACKAGE / "seed/.oasis/core.json").read_bytes()
        core = json.loads(data)
        core["project_note"] = "Useful local role description"
        changed = json.dumps(core).encode()
        self.assertEqual(scan_harness_file("seed/.oasis/core.json", changed)["classification"],
                         "neutral-core-template")
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

    def test_missing_or_renamed_skill_metadata_cannot_claim_24_definitions(self):
        files, reviewed = fixture()
        validate_harness_distribution(files, reviewed)
        for name in ("seed/.agents/skills/oasis-camel/agents/openai.yaml",
                     "library/oasis-review/agents/openai.yaml"):
            changed = dict(files)
            del changed[name]
            with self.subTest(name=name), self.assertRaisesRegex(HarnessError, "skill"):
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
