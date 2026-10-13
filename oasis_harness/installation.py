"""Conflict-first, journalled installation and three-way upgrades.

The journal lives outside the target. Recovery never replaces bytes which differ
from both sides of the recorded operation. Package files are data, not commands.
"""
from __future__ import annotations

import argparse
import ast
import base64
import difflib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

from .common import (HarnessError, atomic_write, canonical, contained, digest,
                     file_hash, is_reparse, operation_lock, read_json, safe_relative, write_json)

MANIFEST = ".oasis/install-manifest.json"
# Source development instructions are never adopter instructions. New manuals
# and runtime modules require an explicit distribution decision here.
ADOPTER_MANUALS = frozenset({
    "installation.md", "identity.md", "sessions.md", "doctor.md",
    "git-backup.md", "publication.md", "knowledge.md", "validation.md",
    "adaptation-map.md", "adaptation-map.json", "migration-lessons.md", "license.md", "workflows.md",
})
ADOPTER_MODULES = frozenset({
    "__init__.py", "backup.py", "build.py", "cli.py", "common.py", "doctor.py",
    "gitops.py", "github.py", "installation.py", "knowledge.py", "packets.py",
    "publication.py", "sessions.py", "skills.py", "workflows.py",
})
ENTRYPOINT = b'''#!/usr/bin/env python3
from pathlib import Path
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".oasis" / "runtime"))
from oasis_harness.cli import main
if __name__ == "__main__":
    raise SystemExit(main())
'''


def target_root(value):
    root = Path(value).absolute()
    for candidate in (root, *root.parents):
        if candidate.is_symlink() or is_reparse(candidate):
            raise HarnessError(f"Linked installation root is not supported: {candidate}")
    if not root.is_dir() or root == Path(root.anchor):
        raise HarnessError("Installation needs an existing, non-root directory")
    return root.resolve()


def checked_path(root, relative):
    path = contained(root, relative)
    current = Path(root)
    for part in relative.split("/"):
        if current.is_dir():
            matches = [p.name for p in current.iterdir() if p.name.casefold() == part.casefold()]
            if any(name != part for name in matches):
                raise HarnessError(f"Case-colliding installation path: {relative}")
        current /= part
        if current.exists() and current != path and not current.is_dir():
            raise HarnessError(f"File occupies installation directory: {current}")
    if path.exists() and not path.is_file():
        raise HarnessError(f"Non-file destination: {relative}")
    return path


def managed_path(relative):
    """Installation cannot own host settings, Git state or private evidence."""
    relative = safe_relative(relative)
    parts = relative.casefold().split("/")
    if any(part in (".git", ".codex") for part in parts) or any(
            pair == [".oasis", "local"] for pair in (parts[i:i + 2] for i in range(len(parts) - 1))):
        raise HarnessError(f"Protected installation path: {relative}")
    return relative


def package_files(package):
    package = target_root(package)
    files = {}
    folded = {}
    for folder, prefix in (("seed", ""), ("library", ".oasis/library/"), ("docs", ".oasis/manual/"),
                           ("oasis_harness", ".oasis/runtime/oasis_harness/")):
        source = contained(package, folder)
        if not source.is_dir():
            raise HarnessError(f"Incomplete package: missing {folder}")
        for item in sorted(source.rglob("*")):
            if "__pycache__" in item.parts or item.suffix == ".pyc":
                continue
            if item.is_symlink() or is_reparse(item):
                raise HarnessError(f"Linked package member: {item}")
            if not item.is_file():
                continue
            member = item.relative_to(source).as_posix()
            relative = managed_path(prefix + member)
            if folder == "docs" and member not in ADOPTER_MANUALS:
                continue
            if folder == "oasis_harness" and member not in ADOPTER_MODULES:
                continue
            if relative.casefold() == MANIFEST or relative.casefold().startswith(".oasis/base/"):
                raise HarnessError("Package attempts to own installer state")
            key = relative.casefold()
            if key in folded:
                raise HarnessError(f"Duplicate/case-colliding package path: {relative}")
            folded[key] = relative
            files[relative] = item.read_bytes()
    # Keep the harness's distribution notices without taking ownership of an
    # adopting project's root license or imposing it on their product source.
    for name in ("LICENSE", "NOTICE"):
        source = contained(package, name)
        if not source.exists():
            continue
        if not source.is_file():
            raise HarnessError(f"Non-file package notice: {name}")
        relative = managed_path(".oasis/manual/" + name)
        key = relative.casefold()
        if key in folded:
            raise HarnessError(f"Duplicate/case-colliding package path: {relative}")
        folded[key] = relative
        files[relative] = source.read_bytes()
    if "tools/oasis.py" in files:
        raise HarnessError("Package seed must not replace the installed entrypoint")
    files["tools/oasis.py"] = ENTRYPOINT
    return files


def package_version(files):
    try:
        tree = ast.parse(files[".oasis/runtime/oasis_harness/__init__.py"].decode("utf-8"))
        values = [ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                  and any(isinstance(name, ast.Name) and name.id == "__version__" for name in node.targets)]
        if len(values) != 1 or not isinstance(values[0], str) or not values[0].strip():
            raise ValueError("missing package version")
        return values[0]
    except (ValueError, KeyError, SyntaxError, UnicodeError) as exc:
        raise HarnessError("Package must declare one literal __version__; package code is never executed") from exc


def _encode(content):
    return None if content is None else base64.b64encode(content).decode("ascii")


def _decode(content):
    try:
        return None if content is None else base64.b64decode(content, validate=True)
    except (ValueError, TypeError) as exc:
        raise HarnessError("Invalid transaction payload") from exc


def _bytes(path):
    return path.read_bytes() if path.is_file() else None


def _merge_json(base, local, incoming):
    if local == base:
        return incoming
    if incoming == base or local == incoming:
        return local
    if not all(isinstance(value, dict) for value in (base, local, incoming)):
        raise HarnessError("Both local and package changed the same JSON value")
    missing = object()
    result = {}
    for key in base.keys() | local.keys() | incoming.keys():
        value = _merge_json(base.get(key, missing), local.get(key, missing), incoming.get(key, missing))
        if value is not missing:
            result[key] = value
    return result


def merge_bytes(base, local, incoming, relative):
    if local == base:
        return incoming
    if incoming == base or local == incoming:
        return local
    if any(value is None for value in (base, local, incoming)):
        raise HarnessError(f"Conflicting file addition/deletion: {relative}")
    try:
        texts = [value.decode("utf-8") for value in (base, local, incoming)]
    except UnicodeError as exc:
        raise HarnessError(f"Both sides changed binary file: {relative}") from exc
    if relative.endswith(".json"):
        import json
        try:
            merged = _merge_json(*(json.loads(text) for text in texts))
        except (ValueError, HarnessError) as exc:
            raise HarnessError(f"JSON upgrade conflict: {relative}") from exc
        return (json.dumps(merged, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    old, ours, theirs = [text.splitlines(keepends=True) for text in texts]
    edits = []
    for changed in (ours, theirs):
        for tag, a, b, c, d in difflib.SequenceMatcher(a=old, b=changed, autojunk=False).get_opcodes():
            if tag != "equal":
                edit = (a, b, changed[c:d])
                if edit not in edits:
                    edits.append(edit)
    edits.sort(key=lambda item: (item[0], item[1]))
    for left, right in zip(edits, edits[1:]):
        if right[0] < left[1] or right[0] == left[0] or (left[0] == left[1] == right[0]):
            raise HarnessError(f"Overlapping text upgrade: {relative}")
    result = old[:]
    for a, b, replacement in reversed(edits):
        result[a:b] = replacement
    return "".join(result).encode("utf-8")


def upgrade_files(package, manifest, *, refresh_capabilities=False):
    """Doctor may explicitly refresh selected skills; ordinary upgrades preserve them."""
    incoming = package_files(package)
    owners = {}
    if refresh_capabilities:
        from .skills import OPTIONAL_NAMES
        selected = manifest.get("enabled_capabilities", [])
        if not isinstance(selected, list) or any(not isinstance(name, str) or name not in OPTIONAL_NAMES for name in selected) or len(selected) != len(set(selected)):
            raise HarnessError("Invalid installed capability selection; reconcile before refresh")
        for name in selected:
            prefix = ".oasis/library/" + name + "/"
            members = {key: data for key, data in incoming.items() if key.startswith(prefix)}
            if prefix + "SKILL.md" not in members:
                raise HarnessError(f"Selected capability is absent upstream: {name}; owner decision required")
            for key, data in members.items():
                destination = ".agents/skills/" + name + "/" + key[len(prefix):]
                incoming[destination] = data
                owners[destination] = "capability:" + name
    return incoming, owners


def _initial_resolutions(value, root, incoming, previous, *, upgrade, installed):
    """Bind reviewed initial collision bytes without replacing upstream bases.

    This records exact inputs, not evidence that the owner approved their meaning.
    It must never act as a general overwrite, repair or upgrade switch.
    """
    if value is None:
        return {}
    if upgrade or installed:
        raise HarnessError("Initial collision resolutions require a fresh installation, not an upgrade or installed target")
    if not isinstance(value, dict) or set(value) != {"schema_version", "files"} or type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise HarnessError("Initial collision resolutions require exact schema_version 1 and files keys")
    rows = value["files"]
    if not isinstance(rows, list) or not rows:
        raise HarnessError("Initial collision resolutions require a nonempty files list")
    result, seen = {}, set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"path", "before_sha256", "after_base64"}:
            raise HarnessError("Initial collision resolution requires exact path, before_sha256 and after_base64 keys")
        relative = managed_path(row["path"])
        if relative.casefold() in seen:
            raise HarnessError(f"Duplicate initial collision resolution: {relative}")
        seen.add(relative.casefold())
        before = row["before_sha256"]
        if not isinstance(before, str) or len(before) != 64 or any(c not in "0123456789abcdef" for c in before):
            raise HarnessError(f"Invalid initial collision before_sha256: {relative}")
        if not isinstance(row["after_base64"], str):
            raise HarnessError(f"Initial collision after_base64 must encode file bytes: {relative}")
        after = _decode(row["after_base64"])
        if relative not in incoming or relative in previous["managed"]:
            raise HarnessError(f"Unused or owned initial collision resolution: {relative}")
        current = _bytes(checked_path(root, relative))
        if current is None or current == incoming[relative]:
            raise HarnessError(f"Unused initial collision resolution; no existing collision: {relative}")
        if digest(current) != before:
            raise HarnessError(f"Initial collision destination changed: {relative}")
        result[relative] = (before, after)
    return result


def _setup_has_inline_program(path):
    """A dependency manifest may itself contain executable application source."""
    if path.name.casefold() != "package.json":
        return False
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        scripts = value.get("scripts", {})
        if not isinstance(scripts, dict) or any(not isinstance(command, str) for command in scripts.values()):
            return True
    except (ValueError, UnicodeError, AttributeError):
        # Unknown/malformed setup is existing material, never evidence of empty.
        return True
    inline = re.compile(r"(?i)\b(?:node(?:\.exe)?|python(?:3(?:\.\d+)*)?(?:\.exe)?|py(?:\.exe)?|"
                        r"ruby|perl|php|pwsh|powershell|bash|sh)\b[^\r\n;&|]*?\s"
                        r"(?:--eval(?:[=\s]|$)|-[ecpr](?=[\s\"']|$)|-command(?=[\s\"']|$))")
    return any(inline.search(command) for command in scripts.values())


def classify_initial_workflow(root):
    """Conservative fresh-project classification, never a mode switch.

    Git, license, prose guidance and development setup alone can be empty. Any
    other file is existing product material. Unknown or partial harness state
    needs reconciliation before installing, even with an explicit mode choice.
    """
    root = target_root(root)
    if (root / ".oasis").exists():
        raise HarnessError("Partial .oasis installation: reconcile or recover it before fresh installation")
    active = root / ".agents/skills"
    if active.exists() and (active.is_symlink() or is_reparse(active) or
                           any(path.name.startswith("oasis-") for path in active.iterdir())):
        raise HarnessError("Partial Oasis skill installation: reconcile ownership before fresh installation")
    setup_dirs = {".git", ".venv", "venv", "node_modules", ".vscode", ".idea"}
    setup_files = {".gitignore", ".gitattributes", ".editorconfig", ".python-version",
                   "pyproject.toml", "requirements.txt", "requirements-dev.txt",
                   "poetry.lock", "uv.lock", "package.json", "package-lock.json",
                   "pnpm-lock.yaml", "yarn.lock", "tsconfig.json", "jsconfig.json"}
    prose_roots = {"readme", "agents", "projectguide", "license", "notice", "copying", "contributing", "security"}
    evidence = []
    def walk_error(exc):
        raise HarnessError("Unreadable project material needs review before workflow classification") from exc
    for directory, subdirs, filenames in os.walk(root, followlinks=False, onerror=walk_error):
        parent = Path(directory)
        if parent == root:
            subdirs[:] = [name for name in subdirs if name.casefold() not in setup_dirs]
        for name in subdirs + filenames:
            path = parent / name
            if path.is_symlink() or is_reparse(path):
                raise HarnessError("Linked project material needs explicit review before workflow classification")
        for name in filenames:
            path = parent / name
            relative = path.relative_to(root)
            if len(relative.parts) == 1 and ((path.name.casefold() in setup_files and not _setup_has_inline_program(path)) or
                    (path.stem.casefold() in prose_roots and path.suffix.casefold() in {"", ".md", ".txt", ".rst"})):
                continue
            if relative.parts[0].casefold() in {"docs", "bestpractice"} and path.suffix.casefold() in {".md", ".txt", ".rst"}:
                continue
            evidence.append(relative.as_posix())
    return {"mode": "oasis" if evidence else "pioneer",
            "classification_basis": "existing-program" if evidence else "empty-or-setup-only",
            "product_material": sorted(evidence)}


def _workflow_selection(root, incoming, *, installed, upgrade, mode):
    relative = ".oasis/project.json"
    if mode is not None and mode not in {"pioneer", "oasis"}:
        raise HarnessError("Initial mode must be pioneer or oasis")
    if mode is not None and (installed or upgrade):
        raise HarnessError("Installation preserves the existing mode; use workflow for an explicit project transition")
    if relative not in incoming:
        if mode is not None:
            raise HarnessError("This package has no project workflow configuration")
        return None
    if installed or upgrade:
        from .skills import validate_project
        project = validate_project(read_json(checked_path(root, relative)))
        workflow = project["extensions"].get("workflow", {})
        selected = workflow.get("mode", "oasis")
        return {"mode": selected, "classification_basis": "preserved-installation" if "mode" in workflow else "legacy-oasis-fallback",
                "initialization_required": False, "native_actions": "none"}
    result = classify_initial_workflow(root)
    if mode is not None:
        result.update(mode=mode, classification_basis="owner-selected", detected_basis=result["classification_basis"])
    result.update(initialization_required=True,
                  required_roles=["Pioneer"] if result["mode"] == "pioneer" else ["Oasis", "Cameleer"],
                  native_actions="agent-assisted-after-file-verification")
    return result


def plan(target, package=None, *, upgrade=False, refresh_capabilities=False, resolutions=None, mode=None):
    root = target_root(target)
    package = Path(package) if package else Path(__file__).resolve().parents[1]
    manifest_path = checked_path(root, MANIFEST)
    previous = read_json(manifest_path) if manifest_path.exists() else {"schema_version": 1, "managed": {}}
    if previous.get("schema_version") != 1 or not isinstance(previous.get("managed"), dict):
        raise HarnessError("Unsupported installed manifest")
    incoming, active_owners = upgrade_files(package, previous, refresh_capabilities=refresh_capabilities)
    version = package_version(incoming)
    workflow = _workflow_selection(root, incoming, installed=manifest_path.exists(), upgrade=upgrade, mode=mode)
    resolved = _initial_resolutions(resolutions, root, incoming, previous,
                                    upgrade=upgrade, installed=manifest_path.exists())
    refreshed_owners = set(active_owners.values())
    operations, conflicts, retained, records = [], [], [], {}
    for relative in sorted(set(previous["managed"]) | set(incoming)):
        try:
            managed_path(relative)
            current = _bytes(checked_path(root, relative))
            new = incoming.get(relative)
            prior = previous["managed"].get(relative)
            resolution = resolved.get(relative)
            if resolution is not None and (prior or current is None or current == new or digest(current) != resolution[0]):
                raise HarnessError(f"Initial collision destination changed: {relative}")
            if prior and prior.get("owner", "").startswith("capability:") and relative not in incoming and prior["owner"] not in refreshed_owners:
                if current is None:
                    raise HarnessError(f"Activated capability file is missing: {relative}")
                base = _bytes(checked_path(root, ".oasis/base/" + prior["base_sha256"]))
                if base is None or digest(base) != prior["base_sha256"]:
                    raise HarnessError(f"Missing/corrupt capability base: {relative}")
                records[relative] = dict(prior, sha256=digest(current))
                continue
            if prior:
                base_path = checked_path(root, ".oasis/base/" + prior["base_sha256"])
                base = _bytes(base_path)
                if base is None or digest(base) != prior["base_sha256"]:
                    raise HarnessError(f"Missing/corrupt installation base: {relative}")
                if not upgrade and new != base:
                    raise HarnessError(f"Package differs from installed base; use upgrade: {relative}")
                if new is None and current != base:
                    retained.append(relative)
                    continue
                result = merge_bytes(base, current, new, relative)
            else:
                if current is not None and current != new:
                    if resolution is None:
                        raise HarnessError(f"Existing file differs: {relative}")
                    result = resolution[1]
                else:
                    result = new
            if relative == ".oasis/project.json" and workflow and workflow["initialization_required"]:
                from .skills import validate_project
                project = validate_project(json.loads(result.decode("utf-8")))
                project["extensions"].setdefault("workflow", {})["mode"] = workflow["mode"]
                result = canonical(project) + b"\n"
            if new is not None:
                if result is None:
                    raise HarnessError(f"Managed file was locally deleted; resolve explicitly: {relative}")
                owner = active_owners.get(relative) or ("runtime" if relative.startswith(".oasis/runtime/") else "library" if relative.startswith(".oasis/library/") else "seed")
                records[relative] = {"sha256": digest(result), "base_sha256": digest(new), "owner": owner}
            # Even an unchanged adopted collision needs an exact before check
            # during apply, rather than silently claiming a later writer's bytes.
            if current != result or resolution is not None:
                operations.append({"path": relative, "before": _encode(current), "after": _encode(result)})
        except (HarnessError, KeyError) as exc:
            conflicts.append(str(exc))
    for content in incoming.values():
        relative = ".oasis/base/" + digest(content)
        try:
            current = _bytes(checked_path(root, relative))
            if current is not None and current != content:
                raise HarnessError(f"Corrupt installation base blob: {relative}")
            if current is None and not any(item["path"] == relative for item in operations):
                operations.append({"path": relative, "before": None, "after": _encode(content)})
        except HarnessError as exc:
            conflicts.append(str(exc))
    manifest = {"schema_version": 1, "package_version": version, "managed": records,
                "enabled_capabilities": previous.get("enabled_capabilities", []),
                "retained_specializations": sorted(set(retained) | set(previous.get("retained_specializations", [])))}
    manifest_bytes = canonical(manifest) + b"\n"
    old_manifest = _bytes(manifest_path)
    if old_manifest != manifest_bytes:
        operations.append({"path": MANIFEST, "before": _encode(old_manifest), "after": _encode(manifest_bytes)})
    value = {"schema_version": 1, "target": str(root), "upgrade": upgrade,
             "operations": operations, "conflicts": sorted(set(conflicts)), "retained": retained}
    if workflow is not None:
        value["workflow"] = workflow
    value["plan_sha256"] = digest(value)
    return value


def _validate_plan(value):
    expected = value.get("plan_sha256")
    body = {key: item for key, item in value.items() if key != "plan_sha256"}
    if value.get("schema_version") != 1 or expected != digest(body) or value.get("conflicts"):
        raise HarnessError("Installation plan is invalid or has unresolved conflicts")
    root = target_root(value["target"])
    seen = set()
    for op in value["operations"]:
        path = managed_path(op["path"])
        if path.casefold() in seen:
            raise HarnessError("Duplicate transaction path")
        seen.add(path.casefold())
        _decode(op["before"]); _decode(op["after"])
        checked_path(root, path)
    return root


def _state_root(root):
    base = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()))
    return base / "OasisHarness" / "installations" / digest(str(root).casefold())[:24]


def _write_operation(root, op, side):
    path = checked_path(root, managed_path(op["path"]))
    value = _decode(op[side])
    if value is None:
        if path.exists():
            path.unlink()  # Exact journal-owned file, never recursive cleanup.
    else:
        atomic_write(path, value)
    if _bytes(path) != value:
        raise HarnessError(f"Installation readback failed: {op['path']}")


def apply(value, *, state_root=None, interrupt_after=None):
    root = _validate_plan(value)
    state = Path(state_root) if state_root else _state_root(root)
    if state.resolve().is_relative_to(root):
        raise HarnessError("Transaction evidence must be outside the target")
    with operation_lock(contained(root, ".oasis/local/operations.lock")):
        for op in value["operations"]:
            if _bytes(checked_path(root, op["path"])) != _decode(op["before"]):
                raise HarnessError(f"Destination changed since plan: {op['path']}")
        pending = [p for p in state.glob("*/journal.json") if read_json(p).get("state") not in ("complete", "rolled_back")]
        if pending:
            raise HarnessError(f"Recover pending installation first: {pending[0]}")
        if not value["operations"]:
            return {"status": "unchanged", "target": str(root), "changed": []}
        journal_path = state / uuid.uuid4().hex / "journal.json"
        journal = {"schema_version": 1, "state": "applying", "plan": value, "completed": 0}
        write_json(journal_path, journal)
        for number, op in enumerate(value["operations"], 1):
            if _bytes(checked_path(root, op["path"])) != _decode(op["before"]):
                raise HarnessError(f"Concurrent destination edit; recover {journal_path}")
            _write_operation(root, op, "after")
            journal["completed"] = number
            write_json(journal_path, journal)
            if interrupt_after == number:
                raise HarnessError(f"Injected interruption; recover {journal_path}")
        journal["state"] = "complete"
        write_json(journal_path, journal)
        return {"status": "installed", "target": str(root), "journal": str(journal_path),
                "changed": [op["path"] for op in value["operations"] if not op["path"].startswith(".oasis/base/")]}


def recover(journal_path, *, action="resume"):
    journal_path = Path(journal_path).resolve()
    journal = read_json(journal_path)
    root = _validate_plan(journal["plan"])
    if journal_path.is_relative_to(root):
        raise HarnessError("Recovery journal must be external")
    if action not in ("resume", "rollback"):
        raise HarnessError("Recovery action must be resume or rollback")
    with operation_lock(contained(root, ".oasis/local/operations.lock")):
        journal = read_json(journal_path)
        operations = journal["plan"]["operations"]
        for op in operations:
            if _bytes(checked_path(root, op["path"])) not in (_decode(op["before"]), _decode(op["after"])):
                raise HarnessError(f"Recovery would overwrite changed user bytes: {op['path']}")
        if journal.get("state") in ("complete", "rolled_back"):
            return {"status": journal["state"], "journal": str(journal_path)}
        side = "after" if action == "resume" else "before"
        for op in operations if action == "resume" else reversed(operations):
            if _bytes(checked_path(root, op["path"])) not in (_decode(op["before"]), _decode(op["after"])):
                raise HarnessError(f"Recovery would overwrite changed user bytes: {op['path']}")
            _write_operation(root, op, side)
        journal["state"] = "complete" if action == "resume" else "rolled_back"
        write_json(journal_path, journal)
        return {"status": journal["state"], "journal": str(journal_path)}


def verify(target):
    root = target_root(target)
    manifest = read_json(checked_path(root, MANIFEST))
    missing, specialized = [], []
    for relative, record in manifest["managed"].items():
        path = checked_path(root, managed_path(relative))
        base = checked_path(root, ".oasis/base/" + record["base_sha256"])
        if not base.is_file() or file_hash(base) != record["base_sha256"]:
            raise HarnessError(f"Invalid installed base: {relative}")
        if not path.is_file():
            missing.append(relative)
        elif file_hash(path) != record["base_sha256"]:
            specialized.append(relative)
    return {"status": "incomplete" if missing else "verified", "missing": missing,
            "specialized": specialized, "retained": manifest.get("retained_specializations", [])}


def register(subparsers):
    parser = subparsers.add_parser("install", help="Audit, install, recover, or upgrade owned harness files")
    commands = parser.add_subparsers(dest="install_command", required=True)
    for name in ("audit", "plan", "upgrade"):
        child = commands.add_parser(name)
        child.add_argument("--target", required=True, type=Path)
        child.add_argument("--package", type=Path)
        child.add_argument("--output", type=Path)
        if name != "upgrade":
            child.add_argument("--mode", choices=("pioneer", "oasis"),
                               help="Explicit initial project mode; installed mode changes use workflow")
            child.add_argument("--resolutions", type=Path,
                               help="Exact reviewed initial collision bytes; not an overwrite or approval switch")
        def make(args, upgrade=name == "upgrade"):
            resolution_path = getattr(args, "resolutions", None)
            result = plan(args.target, args.package, upgrade=upgrade,
                          resolutions=read_json(resolution_path) if resolution_path else None,
                          mode=getattr(args, "mode", None))
            if args.output:
                if args.output.exists():
                    raise HarnessError("Plan output already exists")
                write_json(args.output, result)
            return result
        child.set_defaults(func=make)
    child = commands.add_parser("apply")
    child.add_argument("--plan", type=Path, required=True)
    child.set_defaults(func=lambda args: apply(read_json(args.plan)))
    child = commands.add_parser("verify")
    child.add_argument("--target", type=Path, required=True)
    child.set_defaults(func=lambda args: verify(args.target))
    child = commands.add_parser("recover")
    child.add_argument("--journal", type=Path, required=True)
    child.add_argument("--action", choices=("resume", "rollback"), default="resume")
    child.set_defaults(func=lambda args: recover(args.journal, action=args.action))
