"""Bounded checks for an exact, neutral Harness source projection.

This helper handles distribution templates which the generic product-export
scanner deliberately refuses. It does not select a repository, authorize a
write, fetch a remote, inspect arbitrary archives or certify prose semantics.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import xml.etree.ElementTree as ET

from oasis_harness.common import HarnessError, digest, is_reparse, safe_relative
from oasis_harness.skills import DEFAULT_NAMES, OPTIONAL_NAMES


NEUTRAL_PROJECT = {
    "schema_version": 1, "name": "", "git": {"profile": "unmanaged"},
    "capabilities": list(OPTIONAL_NAMES), "publication": {"configured": False},
    "backup": {"configured": False}, "adapters": {}, "extensions": {},
}
SEED_FILES = {
    "seed/AGENTS.md", "seed/ProjectGuide.md", "seed/LocalGitWorkflow.md", "seed/.gitattributes",
    "seed/.gitignore",
}
NEUTRAL_OASIS = {
    "seed/.oasis/core.json", "seed/.oasis/project.json", "seed/.oasis/.gitignore",
    "seed/.oasis/docs/identity.md", "seed/.oasis/docs/communication.md",
}
ROOT_FILES = {
    "README.md", "AGENTS.md", "oasis.py", ".gitignore", ".gitattributes",
    "LICENSE", "LICENSE.txt", "NOTICE", "NOTICE.md", "SECURITY.md",
    "oasis-release.json",
    "tools/source-publication.json", "tools/public-source-policy.json",
}
# Owner-supplied README artwork only. The exact inspected PNG had no text/EXIF
# chunks; this pin does not permit other images or binary export exceptions.
README_IMAGES = {
    "assets/readme-hero.png": "b17fb375819b95852b9c64cb516bbc5adff341c786e6028b82301ab32bb8888f",
}
# These two owner-approved UTF-8 vectors are source-only artwork. Exact pins
# accompany, rather than replace, the XML/static-content checks below.
README_SVGS = {
    "assets/readme-title.svg": "258c59854bd9eb32aaa1c05c5496888fc9579d021232d6fa1de85e26200510a7",
    "assets/readme-hero.svg": "16e65d08e57fa4c1c4774aff6c1d42f7a4877d709dcd3485a0eb8708f35f6966",
}
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
_SERVICE_EMAIL = "publication" + "@users.noreply.github.com"
_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_TOKEN = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}|(?:AKIA|ASIA)[A-Z0-9]{16}|"
    r"AIza[A-Za-z0-9_-]{30,}|xox[baprs]-[A-Za-z0-9-]{20,}|"
    r"(?:sk|rk)_live_[A-Za-z0-9]{16,})\b"
)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}\b")
_USERINFO = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/@]+@[^\s/]+")
_KEY_BODY = re.compile(
    r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----"
    r"(?:\s|\\[rn])+[A-Za-z0-9+/=\\rn\r\n]{32,}"
)
# Require a concrete user segment, rather than matching the scanner's own
# /Users/[^/]+/ and /home/[^/]+/ regular-expression spellings.
_USER_SEGMENT = r"[^\\/\r\n\"'<>|:?*\[\]{}()+^$]+"
_USER_PATH = re.compile(
    rf"(?i)(?:\b[a-z]:[\\/]+(?:users|documents and settings)[\\/]+|/Users/|/home/)"
    rf"{_USER_SEGMENT}(?=[\\/\r\n\"']|$)"
)
_SECRET_LITERAL = re.compile(
    r"(?i)\b(?:password|passwd|client_secret|api_key|access_token|oauth_token|secret_key|"
    r"AWS_SECRET_ACCESS_KEY|AZURE_CLIENT_SECRET|GH_TOKEN|GITHUB_TOKEN|OPENAI_API_KEY|GOOGLE_API_KEY|SLACK_BOT_TOKEN)"
    r"[\"']?\s*[:=]\s*[\"']([^\"'\r\n]{8,})[\"']"
)
_BLOCKED_PARTS = {
    ".git", ".codex", ".ssh", ".aws", ".azure", "approvals", "receipts",
    "credentials", "secrets", ".netrc", ".npmrc", ".pypirc",
}
_BLOCKED_FILES = {
    "credentials.json", "credentials.yml", "credentials.yaml", "secrets.json",
    "secrets.yml", "secrets.yaml", "token.json", "auth.json", "hosts.yml",
    "config.toml", "install-manifest.json", "candidate.json", "state.json",
    "build.json", "approval.json", "backup.json",
}


def _fail(rule):
    # Neither matched values nor a potentially private original filename escapes.
    raise HarnessError("Harness public-source check blocked: " + rule)


def review_policy(reviewed=None):
    """Validate exact-byte exceptions; a reason/nonce is never human authority."""
    if reviewed is None:
        return {}
    if not isinstance(reviewed, dict):
        _fail("review policy must be an exact path-to-review mapping")
    normalized = {}
    for name, row in reviewed.items():
        _classify(name)
        if (not isinstance(row, dict) or set(row) != {"sha256", "reason"}
                or not isinstance(row["sha256"], str) or not _SHA256.fullmatch(row["sha256"])
                or not isinstance(row["reason"], str) or not row["reason"].strip()):
            _fail("review entry needs only exact sha256 and substantive reason")
        normalized[name] = {"sha256": row["sha256"], "reason": row["reason"]}
    return normalized


def _classify(name):
    try:
        safe_relative(name)
    except HarnessError:
        _fail("unsafe source path")
    parts = name.split("/")
    folded = [part.casefold() for part in parts]
    if (set(folded) & _BLOCKED_PARTS or any(part.startswith(".env") for part in folded)
            or folded[-1] in _BLOCKED_FILES
            or PurePosixPath(name).suffix.casefold() in {".key", ".pem", ".pfx", ".p12", ".jks", ".keystore"}):
        _fail("private operational or credential path")
    if name in ROOT_FILES:
        return "source-entry"
    if name in README_IMAGES:
        return "readme-image"
    if name in README_SVGS:
        return "readme-svg"
    if name in SEED_FILES:
        return "seed-guidance"
    if name in NEUTRAL_OASIS:
        return "neutral-core-template"
    if len(parts) >= 5 and parts[:3] == ["seed", ".agents", "skills"] and parts[3] in DEFAULT_NAMES:
        tail = "/".join(parts[4:])
        if tail == "SKILL.md" or tail == "agents/openai.yaml" or (tail.startswith("references/") and name.endswith(".md")):
            return "default-skill-template"
    if len(parts) >= 3 and parts[0] == "library" and parts[1] in OPTIONAL_NAMES:
        tail = "/".join(parts[2:])
        if tail in {"SKILL.md", "agents/openai.yaml", "capability.json"} or (tail.startswith("references/") and name.endswith(".md")):
            return "optional-skill-template"
    if any(part in {".oasis", ".agents"} for part in folded):
        _fail("active or unknown template namespace")
    if len(parts) == 2 and parts[0] in {"oasis_harness", "tests", "tools"} and name.endswith(".py"):
        return "python-source"
    if len(parts) >= 2 and parts[0] == "docs" and PurePosixPath(name).suffix in {".md", ".json"}:
        return "source-documentation"
    if len(parts) == 2 and parts[0] == ".githooks" and parts[1] in {"pre-commit", "pre-push"}:
        return "development-hook"
    _fail("unclassified Harness source member")


def _json(data, rule):
    def unique(pairs):
        value = {}
        for key, child in pairs:
            if key in value:
                raise ValueError("duplicate key")
            value[key] = child
        return value
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=unique)
    except (ValueError, UnicodeError):
        _fail(rule)


def _hard_scan(text):
    for rule, pattern in (("credential token", _TOKEN), ("credential JWT", _JWT),
                          ("credential URL", _USERINFO), ("private key body", _KEY_BODY),
                          ("personal host path", _USER_PATH), ("credential literal", _SECRET_LITERAL)):
        if pattern.search(text):
            _fail(rule)
    for match in _EMAIL.finditer(text):
        email = match.group(0)
        if email == _SERVICE_EMAIL or email.casefold().rsplit("@", 1)[1].endswith(".invalid"):
            continue
        _fail("personal email in public bytes")


def _static_svg(text):
    """Closed static drawing subset for the two pinned README vectors only."""
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b|<\?\s*(?!xml\s)", text, re.I):
        _fail("SVG declarations or processing instructions")
    declaration = re.match(r"\A\ufeff?\s*<\?xml\s+(.*?)\?>", text, re.S | re.I)
    if declaration:
        encoding = re.search(r"\bencoding\s*=\s*['\"]([^'\"]+)['\"]", declaration[1], re.I)
        if encoding and encoding[1].casefold() not in {"utf-8", "utf8"}:
            _fail("unsupported SVG XML encoding")
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        _fail("invalid SVG XML")
    namespace = "{http://www.w3.org/2000/svg}"
    if root.tag != namespace + "svg":
        _fail("invalid SVG root namespace")
    tags = {"svg", "title", "desc", "defs", "clipPath", "path", "g", "style", "text"}
    attributes = {"width", "height", "viewBox", "role", "aria-labelledby", "id", "class", "x", "y",
                  "text-anchor", "font-family", "font-size", "font-weight", "fill", "d", "clip-path",
                  "stroke", "stroke-width", "stroke-linejoin"}
    identifiers, references = set(), []
    identifier = re.compile(r"\A[A-Za-z_][A-Za-z0-9_.:-]*\Z")
    color = r"(?:[0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})"
    rule = rf"\.[A-Za-z_][A-Za-z0-9_-]*\s*\{{\s*fill\s*:\s*#{color}\s*;\s*\}}\s*"
    media = rf"@media\s*\(\s*prefers-color-scheme\s*:\s*(?:dark|light)\s*\)\s*\{{\s*(?:{rule})+\}}\s*"
    css = re.compile(rf"\A\s*(?:{rule}|{media})+\Z", re.I)
    for element in root.iter():
        if element.tag not in {namespace + tag for tag in tags}:
            _fail("unsupported or executable SVG element")
        for name, value in element.attrib.items():
            if name.casefold().startswith("on"):
                _fail("executable SVG event attribute")
            if name not in attributes:
                _fail("unsupported or external SVG attribute")
            if re.search(r"(?i)(?:https?:|data:|javascript:|file:|//)", value):
                _fail("external SVG reference")
            if name == "id":
                if not identifier.fullmatch(value) or value in identifiers:
                    _fail("invalid or duplicate SVG identifier")
                identifiers.add(value)
            if name == "aria-labelledby":
                references += value.split()
            if name == "clip-path":
                match = re.fullmatch(r"url\(\s*#([A-Za-z_][A-Za-z0-9_.:-]*)\s*\)", value, re.I)
                if not match:
                    _fail("external or invalid SVG clip reference")
                references.append(match[1])
            elif re.search(r"(?i)url\s*\(", value):
                _fail("unsupported SVG URL reference")
            if name == "stroke" and not re.fullmatch(rf"#{color}", value, re.I):
                _fail("unsupported SVG stroke color")
            if name == "stroke-width" and not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
                _fail("unsupported SVG stroke width")
            if name == "stroke-linejoin" and value not in {"miter", "round", "bevel"}:
                _fail("unsupported SVG stroke join")
        if element.tag == namespace + "style":
            if len(element) or not css.fullmatch(element.text or ""):
                _fail("unsupported SVG CSS; only static fills and color-preference media rules")
    if any(reference not in identifiers for reference in references):
        _fail("unresolved SVG internal reference")


def scan_harness_file(name, data, reviewed=None):
    """Scan one classified regular template/source file; no authority is inferred."""
    classification = _classify(name)
    if not isinstance(data, bytes) or len(data) > MAX_FILE_BYTES:
        _fail("non-byte or oversized source bytes")
    policy = review_policy(reviewed)
    sha = digest(data)
    exception = policy.get(name)
    if exception is not None and exception["sha256"] != sha:
        _fail("reviewed byte hash drift")
    if classification == "readme-image":
        if sha != README_IMAGES[name] or not data.startswith(b"\x89PNG\r\n\x1a\n"):
            _fail("approved README image byte hash drift")
        return {"path": name, "classification": classification, "sha256": sha,
                "reviewed_exception": False, "reviewed_policy_sha256": digest(policy),
                "authority_verified": False}
    if classification == "readme-svg" and sha != README_SVGS[name]:
        _fail("approved README SVG byte hash drift")
    if b"\0" in data:
        _fail("non-text source bytes")
    try:
        text = data.decode("utf-8")
    except UnicodeError:
        _fail("unsupported source encoding")
    _hard_scan(text)
    if classification == "readme-svg":
        _static_svg(text)
    if name == "seed/.oasis/core.json":
        core = _json(data, "invalid core metadata JSON")
        if not isinstance(core, dict) or not isinstance(core.get("core_version"), str):
            _fail("invalid core metadata version")
    if name == "seed/.oasis/project.json" and digest(_json(data, "invalid neutral project JSON")) != digest(NEUTRAL_PROJECT):
        _fail("project template contains selected or bound state")
    if name == "oasis-release.json":
        manifest = _json(data, "invalid public release manifest")
        if (not isinstance(manifest, dict) or set(manifest) != {"schema_version", "version", "channel", "mode", "files", "assets"}
                or manifest["schema_version"] != 1 or not isinstance(manifest["files"], list)
                or not isinstance(manifest["assets"], dict)):
            _fail("private or unsupported release manifest fields")
    # The generic scanner keeps its strict active-state path rule. Namespace
    # acceptance above substitutes only the path, never the content check.
    from oasis_harness.publication import public_scan
    used = False
    try:
        # This single synthetic service identity is allowed by the source
        # policy, without relaxing generic publication's personal-email rule.
        generic_bytes = data.replace(_SERVICE_EMAIL.encode(), b"publication@example.invalid")
        public_scan("docs/harness-source-content.txt", generic_bytes)
    except HarnessError:
        if exception is None:
            _fail("bounded content finding needs exact-byte review")
        used = True
    return {"path": name, "classification": classification, "sha256": sha,
            "reviewed_exception": used, "reviewed_policy_sha256": digest(policy),
            "authority_verified": False}


def _inventory(paths):
    files, directories = {}, {}
    for name in paths:
        try:
            safe_relative(name)
        except HarnessError:
            _fail("unsafe inventory path")
        folded = name.casefold()
        if folded in files:
            _fail("case-colliding source files")
        files[folded] = name
        for parent in PurePosixPath(name).parents:
            prefix = parent.as_posix()
            if prefix == ".":
                continue
            key = prefix.casefold()
            if key in directories and directories[key] != prefix:
                _fail("case-colliding source directories")
            directories[key] = prefix
    if set(files) & set(directories):
        _fail("file occupies a source directory prefix")


def _skill(files, prefix, name, optional):
    required = [prefix + "/SKILL.md", prefix + "/agents/openai.yaml"]
    if optional:
        required += [prefix + "/capability.json"]
    if any(path not in files for path in required):
        _fail("missing required skill entry or metadata")
    text = files[required[0]].decode("utf-8")
    match = re.match(r"\A---\nname: ([a-z0-9-]+)\ndescription: ([^\n]+)\n---\n", text)
    if not match or match[1] != name or not match[2].strip():
        _fail("invalid skill identity or description")
    metadata = files[required[1]].decode("utf-8")
    if (not metadata.startswith("interface:\n") or any(key not in metadata for key in
            ("display_name:", "short_description:", "default_prompt:")) or "$" + name not in metadata):
        _fail("missing skill display or invocation metadata")
    if optional:
        capability = _json(files[required[2]], "invalid optional capability JSON")
        if (not isinstance(capability, dict) or capability.get("schema_version") != 1
                or capability.get("name") != name or capability.get("execution") != "tool-guided"):
            _fail("optional capability identity or execution drift")
    for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
        if "://" in target or target.startswith("#"):
            continue
        target = target.split("#", 1)[0]
        if not target:
            continue
        resolved = posixpath.normpath(posixpath.join(prefix, target))
        if resolved.startswith("seed/.oasis/manual/"):
            resolved = "docs/" + resolved.removeprefix("seed/.oasis/manual/")
        if resolved not in files:
            _fail("missing required skill reference")


def validate_harness_distribution(files, reviewed=None, *, expected_hashes=None, modes=None):
    """Validate a complete exact file map, optionally pinned to hashes/modes.

    Hashes must describe the same complete projection. If modes are omitted this
    function claims byte/inventory checks only, never verified Git regular modes.
    A reviewed mapping records bounded false-positive review, not owner consent.
    """
    if not isinstance(files, dict) or not files:
        _fail("complete explicit source file map required")
    _inventory(files)
    policy = review_policy(reviewed)
    if set(policy) - set(files):
        _fail("review policy names an absent source file")
    if expected_hashes is not None:
        if not isinstance(expected_hashes, dict) or set(expected_hashes) != set(files):
            _fail("committed snapshot inventory differs")
        for name, expected in expected_hashes.items():
            if (not isinstance(expected, str) or not _SHA256.fullmatch(expected)
                    or not isinstance(files[name], bytes) or digest(files[name]) != expected):
                _fail("committed snapshot byte hash drift")
    if modes is not None:
        if (not isinstance(modes, dict) or set(modes) != set(files)
                or any(not isinstance(mode, str) or mode not in {"100644", "100755"} for mode in modes.values())):
            _fail("missing or non-regular committed file mode")
    if any(not isinstance(data, bytes) for data in files.values()) or sum(map(len, files.values())) > MAX_TOTAL_BYTES:
        _fail("non-byte or oversized source distribution")
    scanned = [scan_harness_file(name, data, policy) for name, data in sorted(files.items())]
    mandatory = {
        "README.md", "AGENTS.md", "oasis.py", "oasis_harness/__init__.py", "docs/upgrade-index.json",
        "docs/installation.md", "docs/workflows.md", "docs/CHANGELOG.md",
        "docs/identity.md", "docs/publication.md", "docs/doctor.md", "docs/validation.md",
    } | SEED_FILES | NEUTRAL_OASIS | set(README_IMAGES) | set(README_SVGS)
    mandatory |= {"oasis_harness/" + module + ".py" for module in (
        "backup", "build", "cli", "common", "doctor", "gitops", "github",
        "installation", "knowledge", "publication", "sessions", "skills", "workflows",
    )}
    if mandatory - set(files):
        _fail("missing source entry, manual or neutral template")
    try:
        tree = ast.parse(files["oasis_harness/__init__.py"].decode("utf-8"))
        versions = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets)]
        if len(versions) != 1 or not isinstance(versions[0], str) or not re.fullmatch(r"\d+\.\d+\.\d+", versions[0]):
            raise ValueError
    except (SyntaxError, ValueError, TypeError):
        _fail("invalid literal source package version")
    for name in DEFAULT_NAMES:
        _skill(files, "seed/.agents/skills/" + name, name, False)
    for name in OPTIONAL_NAMES:
        _skill(files, "library/" + name, name, True)
    inventory = {name: {"sha256": digest(data), **({"mode": modes[name]} if modes is not None else {})}
                 for name, data in sorted(files.items())}
    return {"status": "bounded_source_check_pass", "package_version": versions[0],
            "core_version": _json(files["seed/.oasis/core.json"], "invalid core metadata JSON")["core_version"],
            "default_skills": len(DEFAULT_NAMES),
            "optional_skills": len(OPTIONAL_NAMES),
            "active_skills": len(DEFAULT_NAMES) + len(OPTIONAL_NAMES), "files": inventory,
            "inventory_sha256": digest(inventory), "reviewed_policy_sha256": digest(policy),
            "reviewed_exceptions": [row["path"] for row in scanned if row["reviewed_exception"]],
            "modes_verified": modes is not None, "authority_verified": False,
            "limits": "Bounded text/path and structural checks; supplied hash/mode provenance belongs to the caller. No human approval, semantic certification, Git ancestry, remote identity, binary/archive safety or native adoption proof."}


def validate_harness_directory(root, reviewed=None, *, expected_hashes=None, modes=None):
    """Read every regular member of a retained source directory, without ignores."""
    root = Path(root).absolute()
    if not root.is_dir() or any(path.is_symlink() or is_reparse(path) for path in (root, *root.parents)):
        _fail("missing or linked source directory")
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or is_reparse(path):
            _fail("linked source member")
        if path.is_dir():
            continue
        if not path.is_file():
            _fail("non-regular source member")
        if path.stat().st_size > MAX_FILE_BYTES:
            _fail("oversized source member")
        files[path.relative_to(root).as_posix()] = path.read_bytes()
    return validate_harness_distribution(files, reviewed, expected_hashes=expected_hashes, modes=modes)
