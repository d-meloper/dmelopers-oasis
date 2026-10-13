"""Repository development hook: increment package patch without sweeping local edits."""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from oasis_harness.common import HarnessError, atomic_write, contained, operation_lock

VERSION_PATH = "oasis_harness/__init__.py"
VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")


def git(*arguments, data=None, check=True):
    # A real pre-commit context supplies its index. Never replace it with a
    # guessed index or strip it as a service/relay transport would do.
    result = subprocess.run(["git", "-C", str(ROOT), *arguments], input=data, capture_output=True)
    if check and result.returncode:
        raise HarnessError("Version hook Git operation failed: " + arguments[0])
    return result


def literal(data):
    tree = ast.parse(data.decode("utf-8"))
    declarations = [node for node in tree.body if isinstance(node, ast.Assign)
                    and any(isinstance(name, ast.Name) and name.id == "__version__" for name in node.targets)]
    if len(declarations) != 1 or len(declarations[0].targets) != 1:
        raise HarnessError("Package version must have one literal assignment")
    value = declarations[0].value
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str) or not VERSION.fullmatch(value.value):
        raise HarnessError("Package version must be a plain X.Y.Z literal")
    lines = data.splitlines(keepends=True)
    start = sum(map(len, lines[:value.lineno - 1])) + value.col_offset
    end = sum(map(len, lines[:value.end_lineno - 1])) + value.end_col_offset
    return value.value, start, end


def replace(data, version):
    _, start, end = literal(data)
    return data[:start] + json.dumps(version).encode("ascii") + data[end:]


def bump():
    root = Path(git("rev-parse", "--show-toplevel").stdout.decode("utf-8").strip()).resolve()
    if root != ROOT:
        raise HarnessError("Version hook root differs from the actual Git checkout")
    gitdir = Path(git("rev-parse", "--absolute-git-dir").stdout.decode("utf-8").strip())
    selected_index = os.environ.get("GIT_INDEX_FILE")
    if selected_index:
        selected_index = Path(selected_index)
        if not selected_index.is_absolute():
            selected_index = ROOT / selected_index
        if selected_index.resolve() != (gitdir / "index").resolve():
            raise HarnessError("Stage the intended files and use git commit; partial-path/alternate-index commits cannot safely update the package version")
    with operation_lock(gitdir / "oasis-version-hook.lock"):
        head = git("show", "HEAD:" + VERSION_PATH, check=False)
        if head.returncode:
            raise HarnessError("Enable the version hook after the initial tracked package commit")
        head_version = literal(head.stdout)[0]
        staged = git("show", ":" + VERSION_PATH).stdout
        stage_version = literal(staged)[0]
        override = git("config", "--get", "oasis.versionBase", check=False)
        target = git("config", "--show-scope", "--get", "oasis.versionTarget", check=False)
        if target.returncode == 0:
            scope, separator, expected = target.stdout.decode("utf-8").strip().partition("\t")
            if (scope != "command" or not separator or not VERSION.fullmatch(expected)
                    or override.returncode == 0 or expected == head_version):
                raise HarnessError("An exact owner-selected version needs command-local oasis.versionTarget=X.Y.Z, a changed target and no versionBase")
            allowed = {expected}
        else:
            base = override.stdout.decode("utf-8").strip() if override.returncode == 0 else head_version
            if not VERSION.fullmatch(base):
                raise HarnessError("Explicit version base must be X.Y.Z")
            major, minor, patch = map(int, base.split("."))
            expected = f"{major}.{minor}.{patch + 1}"
            if base.split(".")[:2] == head_version.split(".")[:2] and patch < int(head_version.split(".")[2]):
                raise HarnessError("Version base is stale; patch must advance from HEAD")
            allowed = {base, expected}
        if stage_version not in allowed:
            raise HarnessError("Version change needs the owner's explicit base or exact command-local target")
        path = contained(ROOT, VERSION_PATH)
        before = path.read_bytes()
        if literal(before)[0] not in allowed:
            raise HarnessError("Unstaged version differs; preserve it and resolve the owner's intended base")
        after = replace(before, expected)
        candidate = replace(staged, expected)
        entry = git("ls-files", "--stage", "-z", "--", VERSION_PATH).stdout
        rows = [row for row in entry.split(b"\0") if row]
        if len(rows) != 1:
            raise HarnessError("Version index is unresolved")
        metadata, indexed_path = rows[0].split(b"\t", 1)
        mode, old_blob, stage = metadata.decode("ascii").split()
        if stage != "0" or indexed_path.decode("utf-8") != VERSION_PATH or mode not in ("100644", "100755"):
            raise HarnessError("Version file must be a regular stage-zero tracked file")
        new_blob = git("hash-object", "-w", "--stdin", data=candidate).stdout.decode("ascii").strip()
        if git("show", ":" + VERSION_PATH).stdout != staged or path.read_bytes() != before:
            raise HarnessError("Version bytes changed during preparation; no version is applied")
        if before != after:
            atomic_write(path, after)
        try:
            git("update-index", "--cacheinfo", mode + "," + new_blob + "," + VERSION_PATH)
        except Exception:
            if path.read_bytes() == after and before != after:
                atomic_write(path, before)
            raise
        if git("show", ":" + VERSION_PATH).stdout != candidate:
            raise HarnessError("Version index readback differs; inspect before retrying")
        return expected


if __name__ == "__main__":
    try:
        print("Oasis package version: " + bump())
    except (HarnessError, OSError, ValueError, SyntaxError) as exc:
        print("Oasis version hook: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
