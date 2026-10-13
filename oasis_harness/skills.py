"""The complete project-local skill catalog and resource checks."""
from __future__ import annotations

from pathlib import Path
import re

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


def inspect_skill(path):
    path = target_root(path)
    source = path / "SKILL.md"
    if not source.is_file() or source.is_symlink():
        raise HarnessError(f"Missing regular SKILL.md: {path.name}")
    text = source.read_text(encoding="utf-8")
    match = re.match(r"\A---\nname: ([a-z0-9-]+)\ndescription: ([^\n]+)\n---\n", text)
    if not match or match[1] != path.name or not match[2].strip():
        raise HarnessError(f"Invalid skill metadata: {path.name}")
    for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
        if "://" in target or target.startswith("#"):
            continue
        target = target.split("#", 1)[0]
        if target and not (path / target).is_file():
            raise HarnessError(f"Broken installed skill resource {path.name}: {target}")
    files = {}
    for candidate in sorted(path.rglob("*")):
        relative = candidate.relative_to(path).as_posix()
        checked = contained(path, relative)
        if checked.is_file():
            files[relative] = file_hash(checked)
    return {"name": path.name, "description": match[2], "files": files}


def list_skills(root=None, package=PACKAGE):
    result = []
    core_root, library_root = resource_roots(package)
    if root is not None:
        check_core(root, package)
    for name in ALL_NAMES:
        optional = name in OPTIONAL_NAMES
        source = (library_root if optional else core_root) / name
        row = inspect_skill(source)
        row.update({"kind": "capability" if optional else "core" if name in CORE_NAMES else "default", "selected": True,
                    "installed": None if root is None else (Path(root) / ".agents/skills" / name / "SKILL.md").is_file()})
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
    listing.set_defaults(func=lambda args: list_skills(args.project))
    validation = subs.add_parser("validate")
    validation.add_argument("--project", required=True)
    validation.set_defaults(func=lambda args: validate_skills(args.project))
