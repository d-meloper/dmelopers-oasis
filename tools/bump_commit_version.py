"""Keep development versions stable; finalize one patch for a completed task."""
from __future__ import annotations

import ast
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from oasis_harness.common import HarnessError, atomic_write, contained, operation_lock, write_new_json
from oasis_harness.build import evidence_destination

VERSION_PATH = "oasis_harness/__init__.py"
HISTORY_PATH = "docs/upgrade-index.json"
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


def version_delta(expected, previous, baseline):
    staged = git("show", ":" + HISTORY_PATH, check=False)
    if staged.returncode:
        if git("show", "HEAD:" + HISTORY_PATH, check=False).returncode == 0:
            raise HarnessError("Keep the tracked version delta index and stage the new entry")
        return  # Compatibility for sources predating introduction of the index.
    data = json.loads(staged.stdout.decode("utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("releases"), list):
        raise HarnessError("Stage a schema-1 version delta index")
    for release in data["releases"]:
        if not isinstance(release, dict) or not isinstance(release.get("version"), str) or not VERSION.fullmatch(release["version"]) or not isinstance(release.get("previous"), str) or not VERSION.fullmatch(release["previous"]):
            raise HarnessError("Version deltas need chronological X.Y.Z versions and explicit predecessors")
    prior = git("show", baseline + ":" + HISTORY_PATH, check=False)
    if prior.returncode == 0:
        old = json.loads(prior.stdout.decode("utf-8"))
        old_rows = old.get("releases") if isinstance(old, dict) else None
        if not isinstance(old_rows, list) or len(data["releases"]) != len(old_rows) + 1 or [(r.get("version"), r.get("previous")) for r in data["releases"][:-1]] != [(r.get("version"), r.get("previous")) for r in old_rows]:
            raise HarnessError("Retain prior chronological version entries and append exactly one new delta")
    rows = data["releases"][-1:]
    if len(rows) != 1 or rows[0].get("version") != expected or rows[0].get("previous") != previous or not isinstance(rows[0].get("summary"), list) or any(not isinstance(s, str) or not s.strip() for s in rows[0]["summary"]) or not isinstance(rows[0].get("areas"), list) or not isinstance(rows[0].get("source_only"), list):
        raise HarnessError("Each package bump needs one staged predecessor delta and explicit public summary/application lists")
    if rows[0]["source_only"]:
        raise HarnessError("Keep source-only implementation notes in private evidence; source_only must be empty")
    if bool(rows[0]["summary"]) != bool(rows[0]["areas"]):
        raise HarnessError("Public summaries need adopter areas; source-only deltas leave summary and areas empty")
    for area in rows[0]["areas"]:
        if not isinstance(area, dict) or any(not isinstance(area.get(k), str) or not area[k] for k in ("name", "change", "apply")) or not isinstance(area.get("paths"), list) or not area["paths"] or any(not isinstance(p, str) or not p for p in area["paths"]) or not isinstance(area.get("checks"), list) or any(not isinstance(c, str) for c in area["checks"]):
            raise HarnessError("Each adopter area needs paths, change, application instructions and checks")
    files = rows[0].get("files")
    changed = set(git("diff", "--cached", "--name-only", "-z", baseline).stdout.decode("utf-8").split("\0")) - {"", HISTORY_PATH, VERSION_PATH}
    if not isinstance(files, list) or any(not isinstance(f, str) for f in files) or len(set(files)) != len(files) or set(files) != changed:
        raise HarnessError("Version delta files must exactly cover the completed task from its baseline to the index, excluding index and package literal")
    return staged.stdout


def task_baseline(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value):
        raise HarnessError("Task finalization requires its full immutable baseline commit")
    if git("rev-parse", "--verify", value + "^{commit}", check=False).returncode or git("merge-base", "--is-ancestor", value, "HEAD", check=False).returncode:
        raise HarnessError("Task baseline must be an existing ancestor of HEAD")
    return value


def local_option(name):
    value = git("config", "--show-scope", "--get", name, check=False)
    if value.returncode:
        return None
    scope, separator, result = value.stdout.decode("utf-8").strip().partition("\t")
    if scope != "command" or not separator:
        raise HarnessError(name + " must use command-local git -c; preserve persistent settings and resolve them explicitly")
    return result


def selected_version(head_version, stage_version, *, draft_base=None):
    finalize = local_option("oasis.versionFinalize")
    baseline = task_baseline(draft_base if draft_base is not None else finalize) if draft_base is not None or finalize is not None else None
    override = git("config", "--show-scope", "--get", "oasis.versionBase", check=False)
    target = git("config", "--show-scope", "--get", "oasis.versionTarget", check=False)
    previous = literal(git("show", baseline + ":" + VERSION_PATH).stdout)[0] if baseline else head_version
    base = previous
    if override.returncode == 0:
        scope, separator, base = override.stdout.decode("utf-8").strip().partition("\t")
        if scope != "command" or not separator or not VERSION.fullmatch(base):
            raise HarnessError("Version base must use command-local git -c oasis.versionBase=X.Y.Z; preserve persistent settings and resolve them explicitly")
    if target.returncode == 0:
        scope, separator, expected = target.stdout.decode("utf-8").strip().partition("\t")
        if scope != "command" or not separator or not VERSION.fullmatch(expected) or override.returncode == 0 or expected == head_version:
            raise HarnessError("An exact owner-selected version needs command-local oasis.versionTarget=X.Y.Z, a changed target and no versionBase")
        allowed = {expected}
    elif baseline or override.returncode == 0:
        major, minor, patch = map(int, base.split("."))
        expected = f"{major}.{minor}.{patch + 1}"
        if base.split(".")[:2] == head_version.split(".")[:2] and patch < int(head_version.split(".")[2]):
            raise HarnessError("Version base is stale; patch must advance from HEAD")
        allowed = {base, expected}
    else:
        expected, allowed = head_version, {head_version}
    if stage_version not in allowed:
        raise HarnessError("Version change needs the owner's explicit base or exact command-local target")
    return expected, allowed, baseline, previous


def stable_history():
    staged = git("show", ":" + HISTORY_PATH, check=False)
    prior = git("show", "HEAD:" + HISTORY_PATH, check=False)
    if prior.returncode:
        if staged.returncode == 0:
            raise HarnessError("A new release index requires task finalization")
        return
    if staged.returncode:
        raise HarnessError("Keep the tracked version delta index")
    def identities(data):
        value = json.loads(data)
        if not isinstance(value, dict) or value.get("schema_version") != 1 or not isinstance(value.get("releases"), list):
            raise HarnessError("Keep a schema-1 version delta index")
        rows = value["releases"]
        if any(not isinstance(row, dict) or any(not isinstance(row.get(key), str) or not VERSION.fullmatch(row[key])
                                               for key in ("version", "previous")) for row in rows):
            raise HarnessError("Keep valid release identities")
        return [(row["version"], row["previous"]) for row in rows]
    if identities(staged.stdout) != identities(prior.stdout):
        raise HarnessError("Release entries change only during explicit task finalization")


def delta_draft(base):
    if Path(git("rev-parse", "--show-toplevel").stdout.decode("utf-8").strip()).resolve() != ROOT:
        raise HarnessError("Version draft root differs from the actual checkout")
    previous = literal(git("show", "HEAD:" + VERSION_PATH).stdout)[0]
    staged = literal(git("show", ":" + VERSION_PATH).stdout)[0]
    expected, _, baseline, previous = selected_version(previous, staged, draft_base=base)
    files = set(git("diff", "--cached", "--name-only", "-z", baseline).stdout.decode("utf-8").split("\0")) - {"", HISTORY_PATH, VERSION_PATH}
    return {"version": expected, "previous": previous, "summary": [], "areas": [], "source_only": [], "files": sorted(files)}


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
        expected, allowed, baseline, previous = selected_version(head_version, stage_version)
        if baseline is None and expected != head_version:
            baseline = git("rev-parse", "HEAD").stdout.decode("ascii").strip()
        history = version_delta(expected, previous, baseline) if baseline else None
        path = contained(ROOT, VERSION_PATH)
        before = path.read_bytes()
        if literal(before)[0] not in allowed:
            raise HarnessError("Unstaged version differs; preserve it and resolve the owner's intended base")
        if baseline is None:
            stable_history()
            return expected
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
        if git("show", ":" + VERSION_PATH).stdout != staged or path.read_bytes() != before or (history is not None and git("show", ":" + HISTORY_PATH).stdout != history):
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delta-draft", action="store_true", help="Read staged scope and print an unfinished release-row draft")
    parser.add_argument("--base", help="Full completed-task baseline commit for the draft")
    parser.add_argument("--output", type=Path, help="New private draft file, preferably under .oasis/local/; no index or version writes")
    args = parser.parse_args()
    if args.output and not args.delta_draft:
        parser.error("--output requires --delta-draft")
    if bool(args.base) != bool(args.delta_draft):
        parser.error("--delta-draft requires --base <full-task-baseline>; --base is draft-only")
    try:
        if args.delta_draft:
            draft = delta_draft(args.base)
            if args.output:
                output = evidence_destination(ROOT, args.output)
                write_new_json(output, draft)
            else:
                print(json.dumps(draft, ensure_ascii=True, indent=2))
        else:
            print("Oasis package version: " + bump())
    except (HarnessError, OSError, ValueError, SyntaxError) as exc:
        print("Oasis version hook: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
