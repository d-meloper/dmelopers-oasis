"""Optional local testcase evidence; never a replacement for a verified build."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import shutil
import struct
import sys
import uuid
import xml.etree.ElementTree as ET

from .common import (HarnessError, ProcessTimeout, clean_environment, contained, digest,
                     file_hash, read_json, run, safe_relative, write_json, write_new_json)

MAX_REPORT = 16 * 1024 * 1024
ENVIRONMENT_PROFILES = ("strict", "role-neutral")
ROLE_ENVIRONMENT = {"CODEX_THREAD_ID", "CODEX_SESSION_ID", "OASIS_APP_SERVER_URL"}
FINGERPRINT_FIELDS = {"cwd", "command", "runner", "host_runtime", "inputs", "runtime_inputs", "environment_sha256"}


def fingerprint_changes(recorded, current):
    """Compare original proof only. Missing historical key digests stay unknown."""
    if not isinstance(recorded, dict) or not isinstance(current, dict):
        return {"status": "unknown", "fields": [], "environment_keys": {"status": "unknown"}}
    fields = sorted(key for key in FINGERPRINT_FIELDS if recorded.get(key) != current.get(key))
    details = {}
    for key in ("inputs", "runtime_inputs", "runner", "host_runtime"):
        left, right = recorded.get(key), current.get(key)
        if key in fields and isinstance(left, dict) and isinstance(right, dict):
            details[key] = {"added": sorted(right.keys() - left.keys()), "removed": sorted(left.keys() - right.keys()),
                            "changed": sorted(name for name in left.keys() & right.keys() if left[name] != right[name])}
    left, right = recorded.get("environment_key_digests"), current.get("environment_key_digests")
    environment = {"status": "unknown", "reason": "Original per-key environment evidence was not recorded; do not reconstruct it"}
    if isinstance(left, dict) and isinstance(right, dict):
        environment = {"status": "compared", "added": sorted(right.keys() - left.keys()), "removed": sorted(left.keys() - right.keys()),
                       "changed": sorted(key for key in left.keys() & right.keys() if left[key] != right[key])}
        if left != right and "environment_sha256" not in fields:
            fields.append("environment_key_digests")
    unknown = (recorded.keys() | current.keys()) - FINGERPRINT_FIELDS - {"environment_key_digests"}
    if unknown:
        fields.extend(sorted(unknown))
    return {"status": "changed" if fields else "matching", "fields": fields, "details": details,
            "environment_keys": environment}


def check_environment(profile="strict"):
    if profile not in ENVIRONMENT_PROFILES:
        raise HarnessError("Unsupported check environment profile")
    return {key: value for key, value in clean_environment().items()
            if profile != "role-neutral" or key.upper() not in ROLE_ENVIRONMENT}


def junit_cases(path):
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_REPORT + 1)
    if len(data) > MAX_REPORT or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise HarnessError("JUnit report exceeds the supported plain XML boundary")
    try:
        tree = ET.fromstring(data)
    except ET.ParseError as exc:
        raise HarnessError("Invalid JUnit report") from exc
    if tree.tag not in ("testsuite", "testsuites"):
        raise HarnessError("Expected a JUnit testsuite or testsuites")
    cases = {}
    for item in tree.iter("testcase"):
        name, classname = item.get("name"), item.get("classname")
        if not name or not classname:
            raise HarnessError("JUnit cases need unambiguous classname and name")
        identity = classname + "::" + name
        if identity in cases:
            raise HarnessError("Duplicate JUnit testcase identity; cannot reuse ambiguous coverage")
        status = next((kind for kind in ("error", "failure", "skipped") if item.find(kind) is not None), "passed")
        cases[identity] = status
    if not cases:
        raise HarnessError("JUnit report contains no testcase evidence")
    # Infrastructure/fixture errors cannot be scoped safely from a JUnit pass.
    errors = any(status == "error" for status in cases.values())
    try:
        errors |= any(int(suite.get("errors", "0")) != 0 for suite in tree.iter("testsuite"))
    except ValueError as exc:
        raise HarnessError("Invalid JUnit error count") from exc
    return {"cases": cases, "infrastructure_errors": errors}


def _files(root, selectors, *, allow_empty=False):
    if not isinstance(selectors, (list, tuple)) or any(not isinstance(item, str) or not item for item in selectors):
        raise HarnessError("Check inputs must be explicit path lists")
    result = {}
    for selector in selectors:
        path = Path(selector)
        path = path if path.is_absolute() else root / path
        path = path.resolve(strict=True)
        direct = path.is_file()
        paths = [path] if direct else sorted(path.rglob("*"))
        for child in paths:
            if not direct and any(part in (".git", "__pycache__", ".pytest_cache") for part in child.parts):
                continue
            if not direct and child.is_relative_to(root / ".oasis/local"):
                continue
            if child.is_symlink():
                raise HarnessError("Declare the real check input instead of a symbolic link")
            if child.is_file():
                result[str(child)] = file_hash(child)
    if not result and not allow_empty:
        raise HarnessError("Check input boundary contains no files")
    return result


def fingerprint(root, command, inputs, runtime, *, environment_profile="strict", environment=None):
    root = Path(root).resolve(strict=True)
    if not isinstance(command, list) or not command or any(not isinstance(arg, str) or not arg for arg in command):
        raise HarnessError("Check command must be an argument array")
    environment = check_environment(environment_profile) if environment is None else environment
    executable = shutil.which(command[0], path=environment.get("PATH", os.defpath))
    if executable is None:
        raise HarnessError("Cannot resolve the actual check runner")
    # All inherited values are hashed privately, never logged as plaintext.
    return {"cwd": str(root), "command": command, "runner": {"path": str(Path(executable).resolve()), "sha256": file_hash(executable)},
            "host_runtime": {"implementation": sys.implementation.name, "version": list(sys.version_info[:3]),
                "bits": struct.calcsize("P") * 8, "optimize": sys.flags.optimize, "os": os.name, "machine": platform.machine()},
            "inputs": _files(root, inputs), "runtime_inputs": _files(root, runtime) if runtime else {},
            "environment_sha256": digest(environment),
            "environment_key_digests": {key: digest([key, value]) for key, value in environment.items()}}


def _scope_files(root, selectors):
    files = {}
    for selector in selectors:
        path = contained(root, safe_relative(selector))
        if path.exists():
            files.update({Path(name).relative_to(root).as_posix(): sha
                          for name, sha in _files(root, [str(path)], allow_empty=True).items()})
    return files


def _change_declaration(root, scope, product, experience, protected):
    if not scope:
        if product or experience or protected:
            raise HarnessError("Declare --scope-input for the allowed change boundary")
        return None
    groups = {"scope": list(scope), "product": list(product), "experience": list(experience), "protected": list(protected)}
    options = {"scope": "--scope-input", "product": "--allow-product", "experience": "--allow-experience", "protected": "--protect"}
    for kind, values in groups.items():
        for value in values:
            try:
                safe_relative(value)
                contained(root, value)
            except HarnessError as exc:
                raise HarnessError(f"Invalid {options[kind]} path {value!r}: {exc}. Use a portable relative path with '/' separators, for example tests/test_case.py") from exc
    def inside(name, prefixes):
        return any(name == prefix or name.startswith(prefix + "/") for prefix in prefixes)
    for kind in ("product", "experience", "protected"):
        for name in groups[kind]:
            if not inside(name, scope):
                raise HarnessError(f"{options[kind]} path {name!r} must be within a declared --scope-input")
    for name in product:
        for owner in experience:
            if inside(name, [owner]) or inside(owner, [name]):
                raise HarnessError(f"--allow-product path {name!r} and --allow-experience path {owner!r} require distinct ownership")
    return groups


def _change_boundary(root, scope, product, experience, protected):
    declaration = _change_declaration(root, scope, product, experience, protected)
    return {**declaration, "before": _scope_files(root, scope)} if declaration is not None else None


def review_changes(root, boundary):
    """Compare only the declared baseline; no retrospective input fingerprint."""
    if not isinstance(boundary, dict) or not isinstance(boundary.get("before"), dict):
        return {"status": "unknown", "reason": "No original change boundary was recorded"}
    try:
        declaration = _change_boundary(Path(root), boundary["scope"], boundary["product"], boundary["experience"], boundary["protected"])
        current = declaration["before"]
    except (OSError, HarnessError, KeyError, TypeError) as exc:
        return {"status": "needs_review", "reason": "Change boundary unavailable: " + str(exc)}
    changed = sorted(name for name in boundary["before"].keys() | current.keys()
                     if boundary["before"].get(name) != current.get(name))
    groups = {kind: [] for kind in ("product", "experience", "protected", "unexpected")}
    for name in changed:
        kind = next((kind for kind in ("protected", "product", "experience")
                     if any(name == prefix or name.startswith(prefix + "/") for prefix in boundary[kind])), "unexpected")
        groups[kind].append(name)
    return {"status": "within_scope" if not groups["protected"] and not groups["unexpected"] else "needs_review",
            "changes": groups, "scope": boundary["scope"], "coverage": "declared paths only"}


def execute(root, command, *, inputs=(".",), runtime=(), purpose="regression", timeout=1800,
            environment_profile="strict", scope=(), product=(), experience=(), protected=()):
    """Run an explicitly selected command with a unique {report} JUnit output."""
    root = Path(root).resolve(strict=True)
    if not isinstance(purpose, str) or not purpose.strip():
        raise HarnessError("Check purpose must be nonempty")
    if not any("{report}" in arg for arg in command):
        raise HarnessError("Check command needs {report} for its new JUnit output")
    declaration = _change_declaration(root, scope, product, experience, protected)
    environment = check_environment(environment_profile)
    before = fingerprint(root, command, list(inputs), list(runtime), environment_profile=environment_profile, environment=environment)
    boundary = {**declaration, "before": _scope_files(root, scope)} if declaration is not None else None
    destination = contained(root, ".oasis/local/checks/" + uuid.uuid4().hex)
    destination.mkdir(parents=True, exist_ok=False)
    path, report, log = destination / "receipt.json", destination / "report.xml", destination / "command.log"
    receipt = {"schema_version": 2, "phase": "running", "root": str(root), "command": command,
               "inputs": list(inputs), "runtime": list(runtime), "purpose": purpose, "before": before,
               "environment_profile": environment_profile, "change_boundary": boundary}
    write_new_json(path, receipt)
    try:
        result = run([before["runner"]["path"], *[arg.replace("{report}", str(report)) for arg in command[1:]]], cwd=root, check=False, timeout=timeout,
                     env=environment, inherit_environment=False)
        log.write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
        receipt.update(exit_code=result.returncode, log_sha256=file_hash(log), after=fingerprint(root, command, list(inputs), list(runtime),
                       environment_profile=environment_profile))
        receipt.update(junit_cases(report), report_sha256=file_hash(report), phase="recorded")
    except ProcessTimeout as exc:
        log.write_text(exc.stdout + "\n" + exc.stderr, encoding="utf-8")
        receipt.update(phase="incomplete", timed_out=True, log_sha256=file_hash(log))
        raise
    except Exception:
        receipt["phase"] = "incomplete"
        raise
    finally:
        write_json(path, receipt)
    return {"receipt": str(path), "exit_code": receipt["exit_code"], "whole_run_passed": receipt["exit_code"] == 0,
            "case_counts": {status: sum(outcome == status for outcome in receipt["cases"].values())
                            for status in sorted(set(receipt["cases"].values()))}, "runtime_boundary_declared": bool(runtime)}


def _evidence(path):
    value = read_json(path)
    if not isinstance(value, dict):
        return {}, ["Unsupported receipt object; original evidence is unknown"]
    issues = []
    if type(value.get("schema_version")) is not int or value["schema_version"] not in (1, 2):
        issues.append("Unsupported receipt schema; original evidence is unknown")
    if value.get("phase") != "recorded":
        issues.append("Original run is incomplete or unrecorded")
    if any(not isinstance(value.get(key), str) or not value[key] for key in ("root", "purpose")):
        issues.append("Missing original root or purpose")
    for key in ("command", "inputs", "runtime"):
        if not isinstance(value.get(key), list) or any(not isinstance(arg, str) or not arg for arg in value[key]):
            issues.append("Missing or invalid original " + key)
    if not value.get("command") or not value.get("inputs"):
        issues.append("Missing original command or input boundary")
    if value.get("schema_version") == 2 and value.get("environment_profile") not in ENVIRONMENT_PROFILES:
        issues.append("Missing or unsupported original environment profile")
    for key in ("before", "after"):
        snapshot = value.get(key)
        if not isinstance(snapshot, dict) or any(field not in snapshot for field in
                ("cwd", "command", "runner", "host_runtime", "inputs", "runtime_inputs", "environment_sha256")):
            issues.append("Missing original " + key + " fingerprint; do not reconstruct it")
        elif (snapshot["cwd"] != value.get("root") or snapshot["command"] != value.get("command")
              or not isinstance(snapshot["inputs"], dict) or not snapshot["inputs"]
              or not isinstance(snapshot["runtime_inputs"], dict)
              or not isinstance(snapshot["runner"], dict) or not snapshot["runner"].get("path") or not snapshot["runner"].get("sha256")
              or not isinstance(snapshot["host_runtime"], dict) or not snapshot["host_runtime"]
              or not isinstance(snapshot["environment_sha256"], str)):
            issues.append("Invalid original " + key + " fingerprint")
    if (type(value.get("exit_code")) is not int or not isinstance(value.get("cases"), dict)
            or type(value.get("infrastructure_errors")) is not bool
            or not all(isinstance(value.get(key), str) for key in ("report_sha256", "log_sha256"))):
        issues.append("Missing original testcase, exit or retained artifact evidence")
    if not issues:
        if file_hash(path.parent / "report.xml") != value["report_sha256"] or file_hash(path.parent / "command.log") != value["log_sha256"]:
            raise HarnessError("Retained check evidence drift")
        parsed = junit_cases(path.parent / "report.xml")
        if parsed["cases"] != value["cases"] or parsed["infrastructure_errors"] != value["infrastructure_errors"]:
            raise HarnessError("Structured testcase evidence differs from retained JUnit")
    return value, issues


def _description(path, value, issues):
    cases = value.get("cases") if isinstance(value.get("cases"), dict) else {}
    return {"receipt": str(path), "receipt_sha256": file_hash(path), "schema_version": value.get("schema_version"),
            "evidence_status": "unknown" if issues or not value.get("runtime") else "recorded", "missing_evidence": issues,
            "whole_run_exit_code": value.get("exit_code"), "purpose": value.get("purpose"),
            "environment_profile": (value["environment_profile"] if value.get("schema_version") == 2 else "strict") if not issues else None,
            "case_counts": {status: sum(outcome == status for outcome in cases.values()) for status in ("passed", "failure", "error", "skipped")},
            "artifacts": {name: {"path": str(path.parent / filename), "sha256": value.get(name + "_sha256")}
                          for name, filename in (("report", "report.xml"), ("log", "command.log")) if value.get(name + "_sha256")},
            "other_nonpassing_cases": {key: status for key, status in cases.items() if status != "passed"}}


def describe(path):
    """Stable submission fields; validates retained artifacts without rerunning or rehashing inputs."""
    path = Path(path).resolve(strict=True)
    return _description(path, *_evidence(path))


def reuse(path, cases, *, purpose="regression"):
    """Read-only subset decision. Nonzero whole-run status remains nonzero."""
    path = Path(path).resolve(strict=True)
    if not cases or any(not isinstance(case, str) or not case for case in cases):
        raise HarnessError("Name the exact requested JUnit testcase IDs")
    value, issues = _evidence(path)
    return _reuse(path, value, issues, cases, purpose=purpose)


def _reuse(path, value, issues, cases, *, purpose):
    if issues:
        return {**_description(path, value, issues), "status": "needs_check", "cases": {case: "unknown" for case in dict.fromkeys(cases)},
                "rerun_reasons": issues, "fingerprint_changes": {"status": "unknown"}}
    reasons = []
    changes = {"during_run": fingerprint_changes(value["before"], value["after"]), "current": {"status": "unknown"}}
    if type(value.get("exit_code")) is not int or value["exit_code"] not in (0, 1):
        reasons.append("runner did not finish with a normal test outcome")
    if value["infrastructure_errors"]:
        reasons.append("fixture or infrastructure errors need fresh investigation")
    failures = any(status == "failure" for status in value["cases"].values())
    if value["exit_code"] == 1 and not failures or value["exit_code"] == 0 and failures:
        reasons.append("runner exit status is not explained by the recorded testcase outcomes")
    if not value.get("runtime"):
        reasons.append("consumed dependency/runtime boundary was not declared")
    if purpose != value.get("purpose"):
        reasons.append("verification purpose changed")
    try:
        current = fingerprint(value["root"], value["command"], value["inputs"], value["runtime"],
                              environment_profile=value["environment_profile"] if value["schema_version"] == 2 else "strict")
    except (OSError, HarnessError) as exc:
        reasons.append("consumed input unavailable: " + str(exc))
    else:
        changes["current"] = fingerprint_changes(value["after"], current)
        for phase, label in (("during_run", "during the original run"), ("current", "since the original run")):
            if changes[phase]["status"] == "changed":
                reasons.append("consumed fingerprint changed " + label + ": " + ", ".join(changes[phase]["fields"]))
    requested = {case: value["cases"].get(case, "not_run") for case in dict.fromkeys(cases)}
    if any(status != "passed" for status in requested.values()):
        reasons.append("requested subset contains failed, skipped or missing cases")
    return {**_description(path, value, []), "status": "reusable" if not reasons else "needs_check",
            "cases": requested, "rerun_reasons": reasons, "fingerprint_changes": changes,
            "other_nonpassing_cases": {key: status for key, status in value["cases"].items() if status != "passed"}}


def result_summary(result):
    counts = {status: sum(value == status for value in result.get("cases", {}).values())
              for status in ("passed", "failure", "error", "skipped", "not_run", "unknown")}
    text = f"{result['status']}; selected passed {counts['passed']}/{sum(counts.values())}; original whole exit {result.get('whole_run_exit_code')}."
    if result.get("change_boundary"):
        text += " Scope " + result["change_boundary"]["status"] + "."
    if result.get("rerun_reasons"):
        text += " " + "; ".join(result["rerun_reasons"]) + "."
    return text


def summary_view(result):
    """Optional compact citation; full original evidence remains at its pinned refs."""
    return {key: value for key, value in result.items() if key != "cases"}


def review(path, cases=None, *, purpose=None, changes=False):
    """One consumer path for standard and insufficient historical receipts."""
    path = Path(path).resolve(strict=True)
    value, issues = _evidence(path)
    selected = cases
    if selected is None:
        selected = [] if issues else [key for key, status in value["cases"].items() if status == "passed"]
    if issues or not selected:
        result = {**_description(path, value, issues), "status": "needs_check", "rerun_reasons": issues or ["No passed testcase evidence"]}
    else:
        if any(not isinstance(case, str) or not case for case in selected):
            raise HarnessError("Name the exact requested JUnit testcase IDs")
        result = _reuse(path, value, issues, selected, purpose=purpose if purpose is not None else value["purpose"])
    if changes:
        result["change_boundary"] = review_changes(value.get("root", ""), value.get("change_boundary"))
        result["check_status"] = result["status"]
        if result["change_boundary"]["status"] == "needs_review":
            result["status"] = "needs_review"
        elif result["change_boundary"]["status"] == "unknown":
            result["status"] = "needs_check"
    result["selected_case_counts"] = {status: sum(value == status for value in result.get("cases", {}).values())
                                      for status in ("passed", "failure", "error", "skipped", "not_run", "unknown")}
    result["summary"] = result_summary(result)
    return result


def register(subparsers):
    import argparse
    parser = subparsers.add_parser("check", help="Optional local testcase evidence and read-only subset reuse")
    commands = parser.add_subparsers(dest="check_command", required=True)
    p = commands.add_parser("run")
    p.add_argument("--root", required=True)
    p.add_argument("--input", action="append", dest="inputs")
    p.add_argument("--runtime-input", action="append", default=[])
    p.add_argument("--purpose", default="regression")
    p.add_argument("--environment-profile", choices=ENVIRONMENT_PROFILES, default="strict")
    p.add_argument("--scope-input", action="append", default=[])
    p.add_argument("--allow-product", action="append", default=[])
    p.add_argument("--allow-experience", action="append", default=[])
    p.add_argument("--protect", action="append", default=[])
    p.add_argument("command", nargs=argparse.REMAINDER)
    def run_cli(a):
        value = execute(a.root, a.command[1:] if a.command[:1] == ["--"] else a.command,
                        inputs=a.inputs or ["."], runtime=a.runtime_input, purpose=a.purpose,
                        environment_profile=a.environment_profile, scope=a.scope_input, product=a.allow_product,
                        experience=a.allow_experience, protected=a.protect)
        if value["exit_code"] != 0:
            raise HarnessError(f"Tests exited {value['exit_code']}; testcase evidence retained at {value['receipt']}")
        return value
    p.set_defaults(func=run_cli)
    p = commands.add_parser("reuse")
    p.add_argument("--receipt", required=True)
    p.add_argument("--case", action="append", required=True, dest="cases")
    p.add_argument("--purpose", default="regression")
    p.set_defaults(func=lambda a: reuse(a.receipt, a.cases, purpose=a.purpose))
    p = commands.add_parser("review", help="Consume a receipt without guessing fields or executing tests")
    p.add_argument("--receipt", required=True)
    p.add_argument("--case", action="append", dest="cases")
    p.add_argument("--purpose")
    p.add_argument("--changes", action="store_true", help="Compare the originally declared product/experience/protected scope")
    p.add_argument("--summary", action="store_true", help="Cite counts, differences and pinned evidence without copying the passed-case table")
    p.set_defaults(func=lambda a: summary_view(review(a.receipt, a.cases, purpose=a.purpose, changes=a.changes)) if a.summary
                   else review(a.receipt, a.cases, purpose=a.purpose, changes=a.changes))
