"""Local comparison against a staged donor; no network, implicit apply or consent."""
from __future__ import annotations

from pathlib import Path

from . import installation
from .common import HarnessError, digest, file_hash, read_json, write_json, write_new_json
from .skills import OPTIONAL_NAMES, check_core, validate_core


def upgrade_guidance(package, installed, incoming, differences):
    """Advisory version deltas intersected with actual changed managed paths.

    A missing/broken chain falls back to the complete byte/three-way review.
    Notes never filter installation operations or certify authority/semantics.
    """
    changed = sorted(row["path"] for row in differences if row["upstream_changed"])
    result = {"from": installed, "to": incoming, "chain_complete": False,
              "releases": [], "affected_areas": [], "unmapped_paths": changed,
              "local_review_paths": sorted(row["path"] for row in differences if row["local_changed"]),
              "advisory_only": True, "next": "Review complete actual differences; preserve local knowledge/settings and existing authority"}
    path = Path(package) / "docs/upgrade-index.json"
    if not path.is_file():
        result["reason"] = "Donor has no version delta index"
        return result
    try:
        data = read_json(path)
        if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("releases"), list):
            raise ValueError("Invalid version delta index")
        releases = []
        for release in data["releases"]:
            if not isinstance(release, dict) or not isinstance(release.get("version"), str) or not isinstance(release.get("previous"), str) or not isinstance(release.get("summary"), list) or any(not isinstance(s, str) or not s.strip() for s in release["summary"]) or not isinstance(release.get("areas"), list) or not isinstance(release.get("source_only", []), list) or release["areas"] and not release["summary"]:
                raise ValueError("Invalid version delta")
            for area in release["areas"]:
                if not isinstance(area, dict) or any(not isinstance(area.get(key), str) or not area[key] for key in ("name", "change", "apply")) or not isinstance(area.get("paths"), list) or any(not isinstance(p, str) or not p for p in area["paths"]) or not isinstance(area.get("checks"), list):
                    raise ValueError("Invalid selective application area")
            releases.append(release)
        if not releases or releases[-1]["version"] != incoming:
            raise ValueError("Version index does not end at the incoming package")
        positions = [i for i, r in enumerate(releases[:-1]) if r["version"] == installed]
        if len(positions) > 1:
            raise ValueError("Repeated installed version label needs complete actual-difference review")
        if installed == incoming:
            chain = []
        else:
            start = positions[0] + 1 if positions else 0
            cursor, chain = installed, releases[start:]
            for release in chain:
                if release["previous"] != cursor or release["version"] == cursor:
                    raise ValueError("Version predecessor chain is incomplete or cyclic")
                cursor = release["version"]
        mapped = {".oasis/runtime/oasis_harness/__init__.py", ".oasis/manual/upgrade-index.json"}
        result["chain_complete"] = True
        # Source maintenance still joins the predecessor chain, but contributes
        # no adopter release note. Legacy source_only prose is never displayed.
        result["releases"] = [{"version": r["version"], "previous": r["previous"], "summary": r["summary"]}
                              for r in chain if r["summary"] and r["areas"]]
        for release in chain:
            for area in release["areas"]:
                prefixes = [mapped for prefix in area["paths"] for mapped in _installed_prefixes(prefix)]
                paths = [p for p in changed if any(p == prefix or prefix.endswith("/") and p.startswith(prefix) for prefix in prefixes)]
                if paths:
                    mapped.update(paths)
                    result["affected_areas"].append({**area, "version": release["version"], "actual_paths": paths})
        result["unmapped_paths"] = [p for p in changed if p not in mapped]
        if installed == incoming and changed:
            result["chain_complete"] = False
            result["reason"] = "Same-version byte drift is not a predecessor release delta"
        elif result["unmapped_paths"]:
            result["reason"] = "Actual upstream paths are not fully described; review these explicitly"
        else:
            result["next"] = "Review affected areas and local differences, then apply the complete owned three-way plan at the authorized boundary"
    except (HarnessError, KeyError, TypeError, ValueError) as exc:
        result.update(chain_complete=False, reason=str(exc), releases=[], affected_areas=[], unmapped_paths=changed)
    return result


def _installed_prefixes(path):
    # Historical notes can name installed paths or source distribution paths.
    if path.startswith("seed/"):
        return [path[5:]]
    if path.startswith("library/"):
        return [".agents/skills/" + path[8:]]
    if path.startswith("docs/"):
        member = path[5:]
        return [".oasis/manual/" + member] if not member or member in installation.ADOPTER_MANUALS else []
    if path.startswith("oasis_harness/"):
        member = path[len("oasis_harness/"):]
        return [".oasis/runtime/oasis_harness/" + member] if not member or member in installation.ADOPTER_MODULES else []
    if path in {"README.md", "LICENSE", "NOTICE"} or path.startswith(("tools/", "tests/", ".githooks/")):
        return []
    return [path]


def _prepare(target, package, *, calf_migration=None):
    root = installation.target_root(target)
    donor = installation.target_root(package)
    if root == donor:
        raise HarnessError("Source checkout must use source Git review, not self-installation")
    manifest_path = installation.checked_path(root, installation.MANIFEST)
    if not manifest_path.is_file():
        raise HarnessError("No installed manifest; inspect source Git or request an installation plan explicitly")
    manifest = installation.validate_manifest(read_json(manifest_path))
    incoming, owners = installation.upgrade_files(donor, manifest)
    cases = {}
    issues = []
    for name in incoming:
        if any(name == prefix or name.startswith(prefix + "/") for prefix in (".git", ".codex", ".oasis/local")):
            issues.append({"kind": "protected_path", "path": name})
    try:
        check_core(root)
    except (HarnessError, OSError, ValueError, KeyError) as exc:
        issues.append({"kind": "installed_contract", "detail": str(exc)})
    try:
        validate_core(read_json(donor / "seed/.oasis/core.json"))
    except (HarnessError, OSError, ValueError, KeyError) as exc:
        issues.append({"kind": "incoming_contract", "detail": str(exc)})
    try:
        verification = installation.verify(root)
    except (HarnessError, OSError, ValueError, KeyError) as exc:
        verification = {"status": "blocked", "detail": str(exc)}
        issues.append({"kind": "installed_integrity", "detail": str(exc)})
    value = installation._plan_prepared(root, donor, manifest, incoming, owners, upgrade=True,
                                        calf_migration=calf_migration, case_inventory=cases)
    differences = []
    for name in sorted(set(incoming) | set(manifest["managed"])):
        prior = manifest["managed"].get(name)
        expected = digest(incoming[name]) if name in incoming else None
        try:
            path = installation.checked_path(root, name, case_inventory=cases)
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
    report = {"status": "blocked" if issues or value["conflicts"] else "waiting" if value.get("migration", {}).get("status") == "waiting" else "outdated" if any(row["upstream_changed"] for row in differences) else "current",
              "target": str(root), "package": str(donor),
              "installed_version": manifest.get("package_version"),
              "incoming_version": installation.package_version(incoming),
              "candidate_sha256": digest({name: digest(data) for name, data in sorted(incoming.items())}),
              "differences": differences, "issues": issues, "conflicts": value["conflicts"],
              "installed_integrity": verification,
              "planned_paths": [op["path"] for op in value["operations"] if not op["path"].startswith(".oasis/base/")],
              "plan_sha256": value["plan_sha256"], "capabilities_refreshed": list(OPTIONAL_NAMES),
              "remote_verified": False, "semantic_review": "not performed", "applied": False,
              "limits": ["Caller must verify remote identity/ref and staged bytes", "Hash differences are not proof of a defect", "Material changes require concrete owner decisions"]}
    report["upgrade_guidance"] = upgrade_guidance(donor, report["installed_version"], report["incoming_version"], differences)
    if "migration" in value:
        report["migration"] = value["migration"]
    return report, value


def audit(target, package, *, calf_migration=None):
    return _prepare(target, package, calf_migration=calf_migration)[0]


def plan(target, package, *, calf_migration=None):
    report, value = _prepare(target, package, calf_migration=calf_migration)
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
        child.add_argument("--calf-migration", type=Path,
                           help="Reviewed useful Calf notes for an installed Core 2 transition")
        def command(args, operation=operation):
            result = operation(args.target, args.package,
                               calf_migration=read_json(args.calf_migration) if args.calf_migration else None)
            if args.output:
                if args.output.exists():
                    raise HarnessError("Doctor output already exists; retain previous evidence")
                write_new_json(args.output, result)
            return result
        child.set_defaults(func=command)
