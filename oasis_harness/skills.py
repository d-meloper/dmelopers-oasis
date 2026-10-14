"""The complete project-local skill catalog and resource checks."""
from __future__ import annotations

from pathlib import Path
import html
import posixpath
import re
import unicodedata
from urllib.parse import unquote, urlsplit

from .common import HarnessError, contained, file_hash, read_json
from .installation import target_root

PACKAGE = Path(__file__).resolve().parents[1]
CORE_NAMES = (
    "oasis-maintenance", "oasis-cameleer", "oasis-camel",
    "oasis-skill-manager", "oasis-knowledge", "oasis-git-operations", "oasis-github-publication",
)
DEFAULT_NAMES = CORE_NAMES + ("oasis-harness-doctor", "oasis-pioneer")
OPTIONAL_NAMES = (
    "oasis-build-package", "oasis-dependency-security", "oasis-artifact-security",
    "oasis-distribution-reputation", "oasis-published-content", "oasis-update-delivery",
    "oasis-review", "oasis-support-automation", "oasis-support-knowledge",
    "oasis-interface-design", "oasis-state-integrity", "oasis-runtime-lifecycle",
    "oasis-interaction-timing", "oasis-rendering-performance", "oasis-asset-pipeline",
)
ALL_NAMES = DEFAULT_NAMES + OPTIONAL_NAMES
PROJECT_KEYS = {"schema_version", "name", "git", "capabilities", "publication", "backup", "adapters", "extensions"}


def validate_project(project):
    if not isinstance(project, dict) or set(project) != PROJECT_KEYS or type(project.get("schema_version")) is not int or project["schema_version"] != 1:
        raise HarnessError("Project config must use schema_version 1 and the documented exact top-level keys")
    if not isinstance(project["name"], str):
        raise HarnessError("Project name must be text")
    if not isinstance(project["git"], dict) or project["git"].get("profile") not in {"unmanaged", "single-main", "main-test"}:
        raise HarnessError("git.profile must be unmanaged, single-main or main-test")
    caps = project["capabilities"]
    if not isinstance(caps, list) or any(not isinstance(name, str) or name not in OPTIONAL_NAMES for name in caps) or len(caps) != len(set(caps)):
        raise HarnessError("Capabilities metadata must be a unique list of catalog capability names")
    for name in ("publication", "backup"):
        if not isinstance(project[name], dict) or type(project[name].get("configured")) is not bool:
            raise HarnessError(f"{name}.configured must be a boolean")
    for name in ("adapters", "extensions"):
        if not isinstance(project[name], dict):
            raise HarnessError(f"{name} must be an object")
    workflow = project["extensions"].get("workflow", {})
    if not isinstance(workflow, dict) or ("mode" in workflow and
            (not isinstance(workflow["mode"], str) or workflow["mode"] not in {"pioneer", "oasis"})):
        raise HarnessError("extensions.workflow.mode must be pioneer or oasis; legacy missing mode means oasis")
    return project


def check_core(root, package=PACKAGE):
    root = target_root(root)
    actual = validate_core(read_json(contained(root, ".oasis/core.json")))
    project = validate_project(read_json(contained(root, ".oasis/project.json")))
    return {"core_version": actual["core_version"], "project": project,
            "proof": "JSON input shapes only; role guidance is descriptive"}


def validate_core(actual):
    """Read descriptive version metadata without sealing its behavior or text."""
    if not isinstance(actual, dict) or type(actual.get("schema_version")) is not int or actual["schema_version"] != 1:
        raise HarnessError("Core metadata must be a schema-1 JSON object")
    if not isinstance(actual.get("core_version"), str) or not re.fullmatch(r"\d+\.\d+\.\d+", actual["core_version"]):
        raise HarnessError("core_version must be X.Y.Z text")
    return actual


def resource_roots(package=PACKAGE):
    """Resolve bundle versus installed layout without reaching into the donor project."""
    package = Path(package)
    if (package / "seed/.agents/skills").is_dir():
        return package / "seed/.agents/skills", package / "library"
    if package.name == "runtime" and package.parent.name == ".oasis":
        active = package.parent.parent / ".agents/skills"
        return active, active
    raise HarnessError("Skill resources are unavailable; inspect the package or installed runtime layout")


def _markdown_content(text):
    """Discard fenced examples, leaving actual headings and links to inspect."""
    lines = text.splitlines()
    if lines and lines[0] == "---":
        closing = next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
        if closing is not None and any(re.match(r"^[a-zA-Z_][a-zA-Z0-9_-]*:", line) for line in lines[1:closing]):
            lines = lines[closing + 1:]
    result, fence = [], None
    for line in lines:
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            continue
        if marker:
            fence = marker[1]
        else:
            result.append(line)
    return re.sub(r"<!--[\s\S]*?-->", "", "\n".join(result))


def _markdown_targets(text):
    text = re.sub(r"(`+).*?\1", "", text)
    definitions = {}
    for match in re.finditer(r"^ {0,3}\[([^\]\n]+)\]:\s*(<[^>\n]+>|\S+)", text, re.MULTILINE):
        label = " ".join(match[1].casefold().split())
        if not label.startswith("^"):
            definitions.setdefault(label, match[2].strip("<>"))
    references = re.sub(r"^ {0,3}\[[^\]\n]+\]:.*$", "", text, flags=re.MULTILINE)
    for match in re.finditer(r"!?\[([^\]\n]+)\](?:\[([^\]\n]*)\])?(?!\(|:)", references):
        label = " ".join((match[2] or match[1]).casefold().split())
        if label in definitions:
            yield definitions[label]
    for match in re.finditer(r"!?\[[^\]\n]*\]\(\s*", text):
        offset = match.end()
        if offset >= len(text):
            continue
        if text[offset] == "<":
            end = text.find(">", offset + 1)
            if end >= 0:
                yield text[offset + 1:end]
            continue
        target, depth = [], 0
        while offset < len(text):
            character = text[offset]
            if character == "\\" and offset + 1 < len(text):
                target.append(text[offset + 1])
                offset += 2
                continue
            if character == "(":
                depth += 1
            elif character == ")":
                if not depth:
                    break
                depth -= 1
            elif character.isspace() and not depth:
                break
            target.append(character)
            offset += 1
        if target:
            yield "".join(target)


def _markdown_anchors(text):
    markup = re.sub(r"(`+).*?\1", "", text)
    anchors = set(re.findall(r"<[^>]*\b(?:id|name)=[\"']([^\"']+)[\"']", markup))
    generated = set()
    previous = ""
    for line in text.splitlines():
        match = re.match(r"^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        heading = match[1] if match else previous if re.fullmatch(r" {0,3}(?:=+|-+)\s*", line) else None
        previous = line.strip()
        if not heading:
            continue
        heading = re.sub(r"!?\[([^\]]+)\]\([^)]*\)", r"\1", heading)
        heading = html.unescape(re.sub(r"<[^>]*>", "", heading)).replace("`", "")
        heading = re.sub(r"(?<!\w)(__|_)(.+?)\1(?!\w)", r"\2", heading)
        slug = "".join(character for character in heading.lower()
                       if character in "_- " or unicodedata.category(character)[0] not in "PSC").replace(" ", "-")
        candidate, number = slug, 0
        while candidate in generated:
            number += 1
            candidate = f"{slug}-{number}"
        generated.add(candidate)
        anchors.add(candidate)
    return anchors


def validate_markdown_links(name, text, read):
    """Check local links against supplied bytes; never fetch or execute targets."""
    content = _markdown_content(text)
    for target in _markdown_targets(content):
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("//"):
            continue
        parsed = urlsplit(target)
        path = unquote(parsed.path)
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), path)) if path else name
        if resolved.startswith("../") or resolved.startswith("/"):
            raise HarnessError(f"Markdown resource escapes its project: {name}: {target}")
        data = read(resolved)
        if data is None:
            raise HarnessError(f"Missing Markdown resource: {name}: {target}")
        if parsed.fragment:
            try:
                headings = _markdown_anchors(_markdown_content(data.decode("utf-8")))
            except UnicodeError as exc:
                raise HarnessError(f"Non-text Markdown fragment target: {name}: {target}") from exc
            if unquote(parsed.fragment) not in headings:
                raise HarnessError(f"Missing Markdown heading: {name}: {target}")


def _skill_link_reader(path):
    """Give donor and installed skills the same logical project-local layout."""
    package = None
    if path.parent.name == "library" and (path.parent.parent / "seed/.agents/skills").is_dir():
        package = path.parent.parent
        root = package / "seed"
    elif path.parent.name == "skills" and path.parent.parent.name == ".agents":
        root = path.parents[2]
        if root.name == "seed" and (root.parent / "library").is_dir():
            package = root.parent
    else:
        root = path
    logical = ".agents/skills/" + path.name if package or root != path else ""
    cache = {}

    def read(relative):
        if relative not in cache:
            actual_root, member = root, relative
            if package and relative.startswith(".oasis/manual/"):
                from .installation import ADOPTER_MANUALS
                member = relative.removeprefix(".oasis/manual/")
                if member not in ADOPTER_MANUALS:
                    return None
                actual_root = package / "docs"
            elif package and relative.startswith(".agents/skills/"):
                pieces = relative.split("/")
                if len(pieces) > 3 and pieces[2] in OPTIONAL_NAMES:
                    actual_root, member = package / "library", "/".join(pieces[2:])
            candidate = contained(actual_root, member)
            cache[relative] = candidate.read_bytes() if candidate.is_file() else None
        return cache[relative]

    return logical, read


def inspect_skill(path):
    path = target_root(path)
    source = path / "SKILL.md"
    if not source.is_file() or source.is_symlink():
        raise HarnessError(f"Missing regular SKILL.md: {path.name}")
    try:
        text = source.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise HarnessError(f"Invalid skill metadata: {path.name}") from exc
    match = re.match(r"\A---\nname: ([a-z0-9-]+)\ndescription: ([^\n]+)\n---\n", text)
    if not match or match[1] != path.name or not match[2].strip():
        raise HarnessError(f"Invalid skill metadata: {path.name}")
    logical, read = _skill_link_reader(path)
    files = {}
    for candidate in sorted(path.rglob("*")):
        relative = candidate.relative_to(path).as_posix()
        checked = contained(path, relative)
        if checked.is_file():
            files[relative] = file_hash(checked)
            if candidate.suffix == ".md":
                try:
                    validate_markdown_links(posixpath.join(logical, relative), checked.read_text(encoding="utf-8"), read)
                except (HarnessError, UnicodeError) as exc:
                    raise HarnessError(f"Broken installed skill resource {path.name}: {exc}") from exc
    return {"name": path.name, "description": match[2], "files": files}


def list_skills(root=None, package=PACKAGE, *, summary=False):
    result = []
    core_root, library_root = resource_roots(package)
    if root is not None:
        root = target_root(root)
        check_core(root, package)
    for name in ALL_NAMES:
        optional = name in OPTIONAL_NAMES
        source = contained(root, f".agents/skills/{name}") if root is not None else (library_root if optional else core_root) / name
        status = "present"
        if root is not None and not contained(root, f".agents/skills/{name}/SKILL.md").is_file():
            row, status = {"name": name, "description": None, "files": {}}, "missing"
        else:
            try:
                row = inspect_skill(source)
            except HarnessError as exc:
                if root is None or not str(exc).startswith(("Invalid skill metadata:", "Broken installed skill resource")):
                    raise
                row, status = {"name": name, "description": None, "files": {}, "error": str(exc)}, "invalid"
        row.update({"kind": "capability" if optional else "core" if name in CORE_NAMES else "default", "selected": True,
                    "installed": None if root is None else status != "missing", "file_status": status})
        if summary:
            row.pop("files", None)
        result.append(row)
    return {"skills": result, "discovery_verified": False,
            "limit": "File inventory is not actual Codex catalog reflection or provider availability"}


def validate_skills(root, package=PACKAGE):
    state = check_core(root, package)
    expected = set(ALL_NAMES)
    checked = []
    for name in sorted(expected):
        checked.append(inspect_skill(contained(root, f".agents/skills/{name}")))
    extras = []
    skill_root = contained(root, ".agents/skills")
    for path in skill_root.iterdir():
        if path.is_dir() and path.name not in expected:
            extras.append(path.name)
    return {"status": "structural_pass", "skills": checked, "preserved_other_skills": sorted(extras),
            "core_version": state["core_version"], "semantic_review": "not performed", "live_discovery": "not performed"}


def register(subparsers):
    parser = subparsers.add_parser("skills", help="List or validate the 24 project-local skills")
    subs = parser.add_subparsers(dest="skills_action", required=True)
    listing = subs.add_parser("list")
    listing.add_argument("--project")
    listing.add_argument("--summary", action="store_true", help="Show names, descriptions and file status without resource hashes")
    listing.set_defaults(func=lambda args: list_skills(args.project, summary=args.summary))
    validation = subs.add_parser("validate")
    validation.add_argument("--project", required=True)
    validation.set_defaults(func=lambda args: validate_skills(args.project))
