"""Inspect the complete source candidate before a commit or public projection.

The scanner is a bounded leak gate. Its report is evidence, never owner approval.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from oasis_harness.common import HarnessError, digest, git_objects, run
from tools.source_policy import validate_harness_distribution


def candidate(root, revision=None, *, index=False):
    argv = ["git", "-C", str(root)]
    if index:
        entries = run(argv + ["ls-files", "--stage", "-z"]).stdout.split("\0")
    else:
        revision = run(argv + ["rev-parse", "--verify", (revision or "HEAD") + "^{commit}"]).stdout.strip()
        entries = run(argv + ["ls-tree", "-rz", "--full-tree", revision]).stdout.split("\0")
    files, modes, blobs = {}, {}, {}
    for entry in filter(None, entries):
        metadata, name = entry.split("\t", 1)
        fields = metadata.split()
        if index:
            mode, blob, stage = fields
            if stage != "0":
                raise HarnessError("Unmerged index cannot be a public source candidate")
        else:
            mode, kind, blob = fields
            if kind != "blob":
                raise HarnessError("Source candidate contains unsupported objects")
        if mode not in ("100644", "100755") or name in modes:
            raise HarnessError("Source candidate contains links/submodules/duplicate paths")
        modes[name], blobs[name] = mode, blob
    contents = {}
    for oid, kind, data in git_objects(root, list(dict.fromkeys(blobs.values()))):
        if kind != "blob":
            raise HarnessError("Source candidate contains unsupported object contents")
        contents[oid] = data
    files = {name: contents[oid] for name, oid in blobs.items()}
    return files, modes


def inspect(root=ROOT, revision=None, *, index=False):
    files, modes = candidate(root, revision, index=index)
    return inspect_files(files, modes)


def inspect_files(files, modes, expected_hashes=None):
    try:
        policy = json.loads(files["tools/public-source-policy.json"])
        if set(policy) != {"schema_version", "reviewed"} or policy["schema_version"] != 1:
            raise ValueError("Invalid source scan policy")
    except (KeyError, ValueError, TypeError) as exc:
        raise HarnessError("Candidate needs an exact reviewed source scan policy") from exc
    result = validate_harness_distribution(files, policy["reviewed"], modes=modes, expected_hashes=expected_hashes)
    return {"status": "verified", "files": len(files), "candidate_sha256": digest(
        {name: {"sha256": digest(data), "mode": modes[name]} for name, data in sorted(files.items())}),
        "policy_sha256": digest(policy), "checks": {key: value for key, value in result.items() if key != "files"},
        "limit": "Bounded patterns and exact reviewed exceptions do not prove absence of every possible secret"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--revision")
    mode.add_argument("--index", action="store_true")
    mode.add_argument("--snapshot", type=Path)
    parser.add_argument("--inventory", type=Path)
    args = parser.parse_args()
    try:
        if args.snapshot:
            if not args.inventory:
                raise HarnessError("Snapshot inspection requires the retained build inventory")
            from oasis_harness.build import tree_hashes
            from oasis_harness.common import contained
            inventory = json.loads(args.inventory.read_bytes())["source"]
            names = tree_hashes(args.snapshot)
            files = {name: contained(args.snapshot, name).read_bytes() for name in names}
            result = inspect_files(files, inventory["modes"], inventory["files"])
        else:
            if args.inventory:
                raise HarnessError("Build inventory is for snapshot mode only")
            result = inspect(args.root, args.revision, index=args.index)
        print(json.dumps(result, ensure_ascii=True))
    except (HarnessError, OSError, ValueError, TypeError) as exc:
        print("Public source check refused: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
