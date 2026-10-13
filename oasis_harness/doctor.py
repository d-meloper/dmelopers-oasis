"""Local comparison against a staged donor; no network, implicit apply or consent."""
from __future__ import annotations

from pathlib import Path

from . import installation
from .common import HarnessError, digest, file_hash, read_json, write_json
from .skills import EXPECTED_CORE_DIGEST, check_core


def _prepare(target, package):
    root = installation.target_root(target)
    donor = installation.target_root(package)
    if root == donor:
        raise HarnessError("Source checkout must use source Git review, not self-installation")
    manifest_path = installation.checked_path(root, installation.MANIFEST)
    if not manifest_path.is_file():
        raise HarnessError("No installed manifest; inspect source Git or request an installation plan explicitly")
    manifest = read_json(manifest_path)
    incoming, _ = installation.upgrade_files(donor, manifest, refresh_capabilities=True)
    issues = []
    for name in incoming:
        if any(name == prefix or name.startswith(prefix + "/") for prefix in (".git", ".codex", ".oasis/local")):
            issues.append({"kind": "protected_path", "path": name})
    try:
        project = check_core(root)["project"]
        if set(project["capabilities"]) != set(manifest.get("enabled_capabilities", [])):
            issues.append({"kind": "selection_mismatch", "detail": "Project selection and installed capabilities disagree"})
    except (HarnessError, OSError, ValueError, KeyError) as exc:
        issues.append({"kind": "installed_contract", "detail": str(exc)})
    try:
        if digest(read_json(donor / "seed/.oasis/core.json")) != EXPECTED_CORE_DIGEST:
            issues.append({"kind": "core_migration", "detail": "Incoming core requires an approved versioned migration"})
    except (OSError, ValueError, KeyError) as exc:
        issues.append({"kind": "incoming_contract", "detail": str(exc)})
    try:
        verification = installation.verify(root)
    except (HarnessError, OSError, ValueError, KeyError) as exc:
        verification = {"status": "blocked", "detail": str(exc)}
        issues.append({"kind": "installed_integrity", "detail": str(exc)})
    value = installation.plan(root, donor, upgrade=True, refresh_capabilities=True)
    differences = []
    for name in sorted(set(incoming) | set(manifest["managed"])):
        prior = manifest["managed"].get(name)
        expected = digest(incoming[name]) if name in incoming else None
        try:
            path = installation.checked_path(root, name)
            current = file_hash(path) if path.is_file() else None
        except (HarnessError, OSError) as exc:
            issues.append({"kind": "destination", "path": name, "detail": str(exc)})
            continue
        base = prior.get("base_sha256") if prior else None
        if current == expected == base:
            continue
        differences.append({"path": name, "base_sha256": base, "current_sha256": current,
                            "incoming_sha256": expected, "upstream_changed": base != expected,
                            "local_changed": bool(prior and current != base),
                            "missing": current is None, "new_upstream_file": prior is None and expected is not None})
    report = {"status": "blocked" if issues or value["conflicts"] else "outdated" if any(row["upstream_changed"] for row in differences) else "current",
              "target": str(root), "package": str(donor),
              "installed_version": manifest.get("package_version"),
              "incoming_version": installation.package_version(incoming),
              "candidate_sha256": digest({name: digest(data) for name, data in sorted(incoming.items())}),
              "differences": differences, "issues": issues, "conflicts": value["conflicts"],
              "installed_integrity": verification,
              "planned_paths": [op["path"] for op in value["operations"] if not op["path"].startswith(".oasis/base/")],
              "plan_sha256": value["plan_sha256"], "selected_skills_refreshed": manifest.get("enabled_capabilities", []),
              "remote_verified": False, "semantic_review": "not performed", "applied": False,
              "limits": ["Caller must verify remote identity/ref and staged bytes", "Hash differences are not proof of a defect", "Material changes require concrete owner decisions"]}
    return report, value


def audit(target, package):
    return _prepare(target, package)[0]


def plan(target, package):
    report, value = _prepare(target, package)
    if report["status"] == "blocked":
        raise HarnessError("Doctor plan blocked; inspect doctor audit issues/conflicts and reconcile owner decisions")
    return value


def register(subparsers):
    parser = subparsers.add_parser("doctor", help="Compare installed harness with a staged donor; no fetch or automatic apply")
    commands = parser.add_subparsers(dest="doctor_command", required=True)
    for name, operation in (("audit", audit), ("plan", plan)):
        child = commands.add_parser(name)
        child.add_argument("--target", required=True, type=Path)
        child.add_argument("--package", required=True, type=Path)
        child.add_argument("--output", type=Path)
        def command(args, operation=operation):
            result = operation(args.target, args.package)
            if args.output:
                if args.output.exists():
                    raise HarnessError("Doctor output already exists; retain previous evidence")
                write_json(args.output, result)
            return result
        child.set_defaults(func=command)
