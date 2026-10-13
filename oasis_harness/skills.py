"""Project-local skill selection and structural checks, never semantic certification."""
from __future__ import annotations

from pathlib import Path
import re

from .common import HarnessError, contained, digest, file_hash, operation_lock, read_json, write_json
from .installation import target_root

PACKAGE = Path(__file__).resolve().parents[1]
EXPECTED_CORE_DIGEST = "1ddc968c0c19c1e2f89c56158cf40036c41838f7d97d33799cbf7cf3d6d1b07f"
CORE_NAMES = (
    "oasis-maintenance", "oasis-cameleer", "oasis-camel", "oasis-calf",
    "oasis-skill-manager", "oasis-knowledge", "oasis-git-operations", "oasis-github-publication",
)
DEFAULT_NAMES = CORE_NAMES + ("oasis-harness-doctor",)
OPTIONAL_NAMES = (
    "oasis-build-package", "oasis-dependency-security", "oasis-artifact-security",
    "oasis-distribution-reputation", "oasis-published-content", "oasis-update-delivery",
    "oasis-review", "oasis-support-automation", "oasis-support-knowledge",
    "oasis-interface-design", "oasis-state-integrity", "oasis-runtime-lifecycle",
    "oasis-interaction-timing", "oasis-rendering-performance", "oasis-asset-pipeline",
)
PROJECT_KEYS = {"schema_version", "name", "git", "capabilities", "publication", "backup", "adapters", "extensions"}
PROTECTED_KEYS = {"core", "roles", "authority", "permissions", "routing", "model", "approval_policy",
                  "sandbox", "plan_wait", "manual_relay", "allow_external_writes", "upstream_auto_apply"}


def _extension_keys(value, trail="extensions"):
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower().replace("-", "_") in PROTECTED_KEYS:
                raise HarnessError(f"Protected core key at {trail}.{key}; request a versioned core change")
            _extension_keys(child, f"{trail}.{key}")
    elif isinstance(value, list):
        for child in value:
            _extension_keys(child, trail)


def validate_project(project):
    if not isinstance(project, dict) or set(project) != PROJECT_KEYS or project.get("schema_version") != 1:
        raise HarnessError("Project config must use schema_version 1 and the documented exact top-level keys")
    if not isinstance(project["name"], str):
        raise HarnessError("Project name must be text")
    if not isinstance(project["git"], dict) or project["git"].get("profile") not in {"unmanaged", "single-main", "main-test"}:
        raise HarnessError("Select a documented Git profile; do not change active refs by editing config")
    caps = project["capabilities"]
    if not isinstance(caps, list) or any(not isinstance(name, str) or name not in OPTIONAL_NAMES for name in caps) or len(caps) != len(set(caps)):
        raise HarnessError("Capabilities must be a unique list of exact optional skill names")
    for name in ("publication", "backup"):
        if not isinstance(project[name], dict) or type(project[name].get("configured")) is not bool:
            raise HarnessError(f"{name}.configured must be a boolean; it is not authorization")
    for name in ("adapters", "extensions"):
        if not isinstance(project[name], dict):
            raise HarnessError(f"{name} must be an object")
        _extension_keys(project[name], name)
    return project


def check_core(root, package=PACKAGE):
    root = target_root(root)
    actual = read_json(contained(root, ".oasis/core.json"))
    if digest(actual) != EXPECTED_CORE_DIGEST:
        raise HarnessError("Protected core contract drift: preserve local changes and request an explicit versioned migration")
    project = validate_project(read_json(contained(root, ".oasis/project.json")))
    return {"core_version": actual["core_version"], "core_digest": digest(actual), "project": project,
            "proof": "structural only; free-form adapter meaning and live adoption require review"}


def resource_roots(package=PACKAGE):
    """Resolve bundle versus installed layout without reaching into the donor project."""
    package = Path(package)
    if (package / "seed/.agents/skills").is_dir():
        return package / "seed/.agents/skills", package / "library"
    if package.name == "runtime" and package.parent.name == ".oasis":
        return package.parent.parent / ".agents/skills", package.parent / "library"
    raise HarnessError("Skill resources are unavailable; inspect the package or installed runtime layout")


def inspect_skill(path):
    path = target_root(path)
    source = path / "SKILL.md"
    if not source.is_file() or source.is_symlink():
        raise HarnessError(f"Missing regular SKILL.md: {path.name}")
    text = source.read_text(encoding="utf-8")
    match = re.match(r"\A---\nname: ([a-z0-9-]+)\ndescription: ([^\n]+)\n---\n", text)
    if not match or match[1] != path.name or len(match[2]) < 30:
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
    selected = set()
    if root is not None:
        selected = set(check_core(root, package)["project"]["capabilities"])
    for name in DEFAULT_NAMES + OPTIONAL_NAMES:
        optional = name in OPTIONAL_NAMES
        source = (library_root if optional else core_root) / name
        row = inspect_skill(source)
        row.update({"kind": "optional" if optional else "core" if name in CORE_NAMES else "default", "selected": not optional or name in selected,
                    "installed": None if root is None else (Path(root) / ".agents/skills" / name / "SKILL.md").is_file()})
        result.append(row)
    return {"skills": result, "discovery_verified": False,
            "limit": "File inventory is not actual Codex catalog reflection or provider availability"}


def validate_skills(root, package=PACKAGE):
    state = check_core(root, package)
    expected = set(DEFAULT_NAMES) | set(state["project"]["capabilities"])
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


def activate(root, names, package=PACKAGE):
    """Only explicitly named, already configured capabilities. Never overwrite a skill."""
    root = target_root(root)
    _, library_root = resource_roots(package)
    if not names or len(names) != len(set(names)) or any(name not in OPTIONAL_NAMES for name in names):
        raise HarnessError("Select unique exact optional skill names")
    lock = contained(root, ".oasis/local/operations.lock")
    with operation_lock(lock):
        state = check_core(root, package)
        manifest_path = contained(root, ".oasis/install-manifest.json")
        manifest = read_json(manifest_path)
        if manifest.get("schema_version") != 1 or not isinstance(manifest.get("managed"), dict):
            raise HarnessError("Installation manifest is missing or invalid; repair installation before activating skills")
        if not set(names).issubset(state["project"]["capabilities"]):
            raise HarnessError("Requested capabilities are not selected in project.json; obtain owner selection before configuring them")
        destinations = [(name, contained(root, f".agents/skills/{name}")) for name in names]
        payloads = {}
        for name, destination in destinations:
            inspected = inspect_skill(library_root / name)
            payloads[name] = {}
            for relative, expected_hash in inspected["files"].items():
                data = contained(library_root / name, relative).read_bytes()
                if digest(data) != expected_hash:
                    raise HarnessError("Capability source changed during inspection; revalidate before activation")
                payloads[name][relative] = data
            if destination.exists():
                raise HarnessError(f"Existing skill preserved: {name}; review a scoped upgrade instead")
        created = []
        try:
            for name, destination in destinations:
                # mkdir is exclusive even if another non-cooperating writer raced preflight.
                destination.mkdir(parents=False, exist_ok=False)
                created.append(destination)
                for relative, data in payloads[name].items():
                    target = contained(destination, relative)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as stream:
                        stream.write(data)
                inspect_skill(destination)
                for source in sorted(destination.rglob("*")):
                    if source.is_file():
                        relative = source.relative_to(root).as_posix()
                        sha = file_hash(source)
                        baseline = contained(root, f".oasis/base/{sha}")
                        baseline.parent.mkdir(parents=True, exist_ok=True)
                        if baseline.exists():
                            if file_hash(baseline) != sha:
                                raise HarnessError("Existing managed baseline blob is corrupt; preserve it and repair installation")
                        else:
                            with baseline.open("xb") as stream:
                                stream.write(source.read_bytes())
                        manifest["managed"][relative] = {"sha256": sha, "base_sha256": sha, "owner": f"capability:{name}"}
        except Exception:
            # Leave partial owned files for inspection; never delete another writer's work.
            raise HarnessError("Capability activation incomplete; preserve existing/partial skills and inspect before recovery")
        receipt = {"schema_version": 1, "skills": [inspect_skill(path) for path in created],
                   "core_digest": state["core_digest"], "discovery_verified": False}
        manifest["enabled_capabilities"] = sorted(set(manifest.get("enabled_capabilities", [])) | set(names))
        write_json(manifest_path, manifest)
        write_json(contained(root, ".oasis/local/capability-activation.json"), receipt)
        return {"status": "installed", "selected": names, "receipt": receipt,
                "next": "Confirm actual Codex discovery; no external service was configured or invoked"}


def register(subparsers):
    parser = subparsers.add_parser("skills", help="List, validate or activate selected local skills")
    subs = parser.add_subparsers(dest="skills_action", required=True)
    listing = subs.add_parser("list")
    listing.add_argument("--project")
    listing.set_defaults(func=lambda args: list_skills(args.project))
    validation = subs.add_parser("validate")
    validation.add_argument("--project", required=True)
    validation.set_defaults(func=lambda args: validate_skills(args.project))
    activation = subs.add_parser("activate")
    activation.add_argument("--project", required=True)
    activation.add_argument("--skill", action="append", required=True)
    activation.set_defaults(func=lambda args: activate(args.project, args.skill))
