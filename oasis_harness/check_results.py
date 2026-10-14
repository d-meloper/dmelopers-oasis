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
                     file_hash, read_json, run, write_json, write_new_json)

MAX_REPORT = 16 * 1024 * 1024


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


def _files(root, selectors):
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
    if not result:
        raise HarnessError("Check input boundary contains no files")
    return result


def fingerprint(root, command, inputs, runtime):
    root = Path(root).resolve(strict=True)
    if not isinstance(command, list) or not command or any(not isinstance(arg, str) or not arg for arg in command):
        raise HarnessError("Check command must be an argument array")
    executable = shutil.which(command[0], path=clean_environment().get("PATH"))
    if executable is None:
        raise HarnessError("Cannot resolve the actual check runner")
    # All inherited values are hashed privately, never logged as plaintext.
    environment = digest(clean_environment())
    return {"cwd": str(root), "command": command, "runner": {"path": str(Path(executable).resolve()), "sha256": file_hash(executable)},
            "host_runtime": {"implementation": sys.implementation.name, "version": list(sys.version_info[:3]),
                "bits": struct.calcsize("P") * 8, "optimize": sys.flags.optimize, "os": os.name, "machine": platform.machine()},
            "inputs": _files(root, inputs), "runtime_inputs": _files(root, runtime) if runtime else {},
            "environment_sha256": environment}


def execute(root, command, *, inputs=(".",), runtime=(), purpose="regression", timeout=1800):
    """Run an explicitly selected command with a unique {report} JUnit output."""
    root = Path(root).resolve(strict=True)
    if not isinstance(purpose, str) or not purpose.strip():
        raise HarnessError("Check purpose must be nonempty")
    if not any("{report}" in arg for arg in command):
        raise HarnessError("Check command needs {report} for its new JUnit output")
    before = fingerprint(root, command, list(inputs), list(runtime))
    destination = contained(root, ".oasis/local/checks/" + uuid.uuid4().hex)
    destination.mkdir(parents=True, exist_ok=False)
    path, report, log = destination / "receipt.json", destination / "report.xml", destination / "command.log"
    receipt = {"schema_version": 1, "phase": "running", "root": str(root), "command": command,
               "inputs": list(inputs), "runtime": list(runtime), "purpose": purpose, "before": before}
    write_new_json(path, receipt)
    try:
        result = run([arg.replace("{report}", str(report)) for arg in command], cwd=root, check=False, timeout=timeout)
        log.write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
        receipt.update(exit_code=result.returncode, log_sha256=file_hash(log), after=fingerprint(root, command, list(inputs), list(runtime)))
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


def reuse(path, cases, *, purpose="regression"):
    """Read-only subset decision. Nonzero whole-run status remains nonzero."""
    path = Path(path).resolve(strict=True)
    value = read_json(path)
    if not isinstance(value, dict) or value.get("schema_version") != 1 or value.get("phase") != "recorded":
        raise HarnessError("Check receipt is incomplete or unsupported")
    if not cases or any(not isinstance(case, str) or not case for case in cases):
        raise HarnessError("Name the exact requested JUnit testcase IDs")
    if file_hash(path.parent / "report.xml") != value.get("report_sha256") or file_hash(path.parent / "command.log") != value.get("log_sha256"):
        raise HarnessError("Retained check evidence drift")
    parsed = junit_cases(path.parent / "report.xml")
    if parsed["cases"] != value.get("cases") or parsed["infrastructure_errors"] != value.get("infrastructure_errors"):
        raise HarnessError("Structured testcase evidence differs from retained JUnit")
    reasons = []
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
        current = fingerprint(value["root"], value["command"], value["inputs"], value["runtime"])
    except (OSError, HarnessError) as exc:
        reasons.append("consumed input unavailable: " + str(exc))
    else:
        if value.get("before") != value.get("after"):
            reasons.append("consumed inputs changed during the original run")
        if current != value.get("after"):
            reasons.append("source, configuration, runner, dependency/runtime, cwd or environment changed")
    requested = {case: value["cases"].get(case, "not_run") for case in dict.fromkeys(cases)}
    if any(status != "passed" for status in requested.values()):
        reasons.append("requested subset contains failed, skipped or missing cases")
    return {"status": "reusable" if not reasons else "needs_check", "receipt": str(path), "receipt_sha256": file_hash(path),
            "cases": requested, "rerun_reasons": reasons, "whole_run_exit_code": value["exit_code"],
            "other_nonpassing_cases": {key: status for key, status in value["cases"].items() if status != "passed"}}


def register(subparsers):
    import argparse
    parser = subparsers.add_parser("check", help="Optional local testcase evidence and read-only subset reuse")
    commands = parser.add_subparsers(dest="check_command", required=True)
    p = commands.add_parser("run")
    p.add_argument("--root", required=True)
    p.add_argument("--input", action="append", dest="inputs")
    p.add_argument("--runtime-input", action="append", default=[])
    p.add_argument("--purpose", default="regression")
    p.add_argument("command", nargs=argparse.REMAINDER)
    def run_cli(a):
        value = execute(a.root, a.command[1:] if a.command[:1] == ["--"] else a.command,
                        inputs=a.inputs or ["."], runtime=a.runtime_input, purpose=a.purpose)
        if value["exit_code"] != 0:
            raise HarnessError(f"Tests exited {value['exit_code']}; testcase evidence retained at {value['receipt']}")
        return value
    p.set_defaults(func=run_cli)
    p = commands.add_parser("reuse")
    p.add_argument("--receipt", required=True)
    p.add_argument("--case", action="append", required=True, dest="cases")
    p.add_argument("--purpose", default="regression")
    p.set_defaults(func=lambda a: reuse(a.receipt, a.cases, purpose=a.purpose))
