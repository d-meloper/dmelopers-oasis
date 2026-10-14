"""Project-provided build/check adapters, executed against a retained Git snapshot."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import struct
import subprocess
import sys
import uuid

from .common import (HarnessError, ProcessTimeout, clean_environment, contained, digest, file_hash,
                     git, git_objects, json_object, read_json, run, write_json, write_new_json)


def committed_snapshot(root, revision, destination):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    if destination.is_relative_to(root) or root.is_relative_to(destination):
        raise HarnessError("Build evidence must be outside the source checkout")
    if git(root, "rev-parse", "--show-toplevel").casefold() != str(root).replace("\\", "/").casefold():
        # Git on Windows returns slash paths; compare real paths instead.
        if Path(git(root, "rev-parse", "--show-toplevel")).resolve() != root:
            raise HarnessError("Select the exact source repository root")
    oid = git(root, "rev-parse", "--verify", revision + "^{commit}")
    tree = git(root, "rev-parse", oid + "^{tree}")
    fmt = git(root, "rev-parse", "--show-object-format")
    entries = run(["git", "-C", str(root), "ls-tree", "-rz", "--full-tree", oid]).stdout.split("\0")
    files, aliases = [], {}
    for entry in filter(None, entries):
        metadata, name = entry.split("\t", 1)
        mode, kind, blob = metadata.split()
        target = contained(destination, name)
        if kind != "blob" or mode not in ("100644", "100755"):
            raise HarnessError("Build snapshot rejects links/submodules; register a verified acquisition adapter")
        parts = name.split("/")
        for index in range(1, len(parts) + 1):
            path = "/".join(parts[:index])
            alias = path.casefold()
            if alias in aliases and aliases[alias] != path:
                raise HarnessError("Source contains colliding Windows paths")
            aliases[alias] = path
        files.append((name, blob, target, mode))
    destination.mkdir(parents=True, exist_ok=False)
    hashes, modes = {}, {}
    for index, (object_id, kind, data) in enumerate(git_objects(root, [row[1] for row in files])):
        name, blob, target, mode = files[index]
        if kind != "blob" or object_id != blob:
            raise HarnessError("Cannot materialize committed source blob")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
        hashes[name] = digest(data)
        modes[name] = mode
    return {"state": "committed", "object_format": fmt, "commit": oid, "tree": tree, "files": hashes, "modes": modes}


def tree_hashes(root):
    result = {}
    for path in sorted(Path(root).rglob("*")):
        checked = contained(root, path.relative_to(root).as_posix())
        if checked.is_file():
            result[checked.relative_to(Path(root).resolve()).as_posix()] = file_hash(checked)
    return result


def adapter_commands(value, variables):
    if not isinstance(value, list) or not value:
        raise HarnessError("At least one project command is required")
    commands = []
    for command in value:
        if not isinstance(command, list) or not command or any(not isinstance(part, str) or not part for part in command):
            raise HarnessError("Commands must be nonempty argument arrays, never shell text")
        try:
            commands.append([part.format_map(variables) for part in command])
        except (KeyError, ValueError) as exc:
            raise HarnessError("Only source/output/version placeholders are supported") from exc
    return commands


def execution_environment(root, keys=()):
    """Minimal private runtime inputs; never collect ambient configuration."""
    if not isinstance(keys, (list, tuple)) or any(not isinstance(key, str) or not key or not key.isidentifier() for key in keys):
        raise HarnessError("verification_env must name explicit environment inputs")
    return {"python": {"implementation": sys.implementation.name, "version": list(sys.version_info[:3]),
                       "bits": struct.calcsize("P") * 8, "optimize": sys.flags.optimize},
            "platform": {"os": os.name, "machine": platform.machine()},
            "git": git(root, "--version"),
            "env": {key: {"set": key in os.environ, "sha256": digest(os.environ.get(key, ""))}
                    for key in sorted(set(keys))}}


def execute(root, revision, adapter, destination, version):
    """Adapters are executable project code: inspect/authorize them before invocation."""
    destination = Path(destination).resolve()
    if destination.exists():
        raise HarnessError("Build evidence destination already exists; retain it and use a new run")
    adapter = read_json(adapter) if isinstance(adapter, (str, Path)) else adapter
    adapter = json_object(adapter, "Build adapter")
    if not {"schema_version", "build", "checks", "artifacts"}.issubset(adapter) or set(adapter) - {"schema_version", "build", "checks", "artifacts", "purpose", "verification_env"} or type(adapter["schema_version"]) is not int or adapter["schema_version"] != 1:
        raise HarnessError("Expected a schema-1 project build adapter")
    purpose = adapter.get("purpose", "release")
    if purpose not in ("source", "release"):
        raise HarnessError("Build purpose must be source or release")
    if (not isinstance(adapter["artifacts"], list) or any(not isinstance(path, str) or not path for path in adapter["artifacts"]) or
            (purpose == "release" and not adapter["artifacts"])):
        raise HarnessError("Adapter must name exact artifact output paths")
    # Validate commands before creating the retained workspace.
    variables = {"source": str(destination / "source"), "output": str(destination / "output"), "version": version}
    commands = [(kind, cmd) for kind in ("build", "checks") for cmd in
                ([] if kind == "build" and purpose == "source" and adapter[kind] == [] else adapter_commands(adapter[kind], variables))]
    environment = execution_environment(root, adapter.get("verification_env", []))
    source = committed_snapshot(root, revision, destination / "source")
    output = destination / "output"
    output.mkdir()
    receipt = {"schema_version": 1, "run_id": uuid.uuid4().hex, "source": source,
               "source_root": str(Path(root).resolve()), "adapter_sha256": digest(adapter), "version": version,
               "phase": "running", "purpose": purpose, "commands": [], "artifacts": {},
               "execution_environment": environment}
    receipt_path = destination / "build.json"
    write_new_json(receipt_path, receipt)
    try:
        for kind, command in commands:
            try:
                result = run(command, cwd=destination / "source", check=False, timeout=1800)
            except ProcessTimeout as exc:
                log = destination / f"command-{len(receipt['commands']) + 1}.log"
                with log.open("x", encoding="utf-8", newline="\n") as stream:
                    stream.write(exc.stdout + "\n" + exc.stderr)
                receipt["commands"].append({"kind": kind, "argv": command, "exit_code": None,
                                            "timed_out": True, "log_sha256": file_hash(log)})
                raise
            # Logs are local evidence and may contain private project information.
            log = destination / f"command-{len(receipt['commands']) + 1}.log"
            with log.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(result.stdout + "\n" + result.stderr)
            receipt["commands"].append({"kind": kind, "argv": command, "exit_code": result.returncode, "log_sha256": file_hash(log)})
            write_json(receipt_path, receipt)
            if result.returncode:
                raise HarnessError(f"Project {kind} command failed with exit code {result.returncode}; evidence retained")
        # Commands may produce generated files, but cannot silently change committed inputs.
        for name, expected in source["files"].items():
            path = contained(destination / "source", name)
            if not path.is_file() or file_hash(path) != expected:
                raise HarnessError(f"Adapter modified committed source input: {name}")
        aliases = set()
        for name in adapter["artifacts"]:
            path = contained(output, name)
            if not path.is_file() or Path(name).name.casefold() in aliases:
                raise HarnessError("Missing artifact or colliding release basenames")
            aliases.add(Path(name).name.casefold())
            receipt["artifacts"][name] = {"sha256": file_hash(path), "size": path.stat().st_size}
        receipt["phase"] = "verified"
    except Exception as exc:
        receipt.update(phase="failed", error=str(exc))
        write_json(receipt_path, receipt)
        raise
    write_json(receipt_path, receipt)
    return {"receipt": str(receipt_path), "phase": receipt["phase"], "source": source["commit"], "artifacts": receipt["artifacts"]}


def verify_evidence(path):
    path = Path(path).resolve()
    value = json_object(read_json(path), "Build receipt")
    if value.get("phase") != "verified" or not value.get("commands") or (value.get("purpose", "release") == "release" and not value.get("artifacts")):
        raise HarnessError("Build receipt is not a verified project adapter run")
    if (not isinstance(value["commands"], list) or not isinstance(value.get("source"), dict) or
            not isinstance(value["source"].get("files"), dict) or not isinstance(value.get("artifacts"), dict)):
        raise HarnessError("Build receipt collections have invalid types")
    if (type(value.get("schema_version")) is not int or value["schema_version"] != 1 or
            not isinstance(value.get("source_root"), str) or not isinstance(value.get("adapter_sha256"), str) or
            any(not isinstance(value["source"].get(key), str) for key in ("commit", "tree")) or
            ("modes" in value["source"] and (not isinstance(value["source"]["modes"], dict) or
                any(not isinstance(name, str) or not isinstance(mode, str) for name, mode in value["source"]["modes"].items())))):
        raise HarnessError("Build receipt identity fields have invalid types")
    if "execution_environment" in value:
        environment = value["execution_environment"]
        if (not isinstance(environment, dict) or not isinstance(environment.get("python"), dict) or
                not isinstance(environment.get("platform"), dict) or not isinstance(environment.get("git"), str) or
                not isinstance(environment.get("env"), dict) or any(not isinstance(key, str) or not isinstance(row, dict) or
                    type(row.get("set")) is not bool or not isinstance(row.get("sha256"), str) for key, row in environment["env"].items())):
            raise HarnessError("Execution environment has invalid consumed fields")
    for row in value["commands"]:
        if (not isinstance(row, dict) or not isinstance(row.get("kind"), str) or type(row.get("exit_code")) is not int or
                not isinstance(row.get("argv"), list) or not row["argv"] or any(not isinstance(arg, str) for arg in row["argv"]) or
                not isinstance(row.get("log_sha256"), str)):
            raise HarnessError("Build receipt command has invalid consumed fields")
    for name, expected in value["source"]["files"].items():
        if not isinstance(name, str) or not isinstance(expected, str):
            raise HarnessError("Build source inventory must contain text paths and hashes")
    for name, expected in value["artifacts"].items():
        if (not isinstance(name, str) or not isinstance(expected, dict) or not isinstance(expected.get("sha256"), str) or
                type(expected.get("size")) is not int or expected["size"] < 0):
            raise HarnessError("Build artifact inventory has invalid consumed fields")
    if any(row["exit_code"] != 0 for row in value["commands"]) or not any(row["kind"] == "checks" for row in value["commands"]):
        raise HarnessError("Product checks did not pass")
    for index, row in enumerate(value["commands"], 1):
        if file_hash(path.parent / f"command-{index}.log") != row["log_sha256"]:
            raise HarnessError("Build log drift")
    for name, expected in value["source"]["files"].items():
        if file_hash(contained(path.parent / "source", name)) != expected:
            raise HarnessError("Retained producer source drift")
    for name, expected in value["artifacts"].items():
        artifact = contained(path.parent / "output", name)
        if file_hash(artifact) != expected["sha256"] or artifact.stat().st_size != expected["size"]:
            raise HarnessError("Build artifact drift")
    return value


def register(subparsers):
    from . import check_results
    check_results.register(subparsers)
    p = subparsers.add_parser("build", help="Execute an inspected project build adapter in a retained source snapshot")
    p.add_argument("--root", required=True)
    p.add_argument("--revision", required=True)
    p.add_argument("--adapter", required=True)
    p.add_argument("--destination", required=True)
    p.add_argument("--version", required=True)
    p.set_defaults(func=lambda a: execute(a.root, a.revision, a.adapter, a.destination, a.version))
