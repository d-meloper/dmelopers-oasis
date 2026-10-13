"""Primary-source adapter for reviewed public projection and private recovery.

Configure the repositories separately. This tool never converts visibility,
creates a backup repository, edits settings, bypasses checks or grants approval.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from oasis_harness import backup, build, publication
from oasis_harness.common import HarnessError, digest, file_hash, git, read_json, write_json
from oasis_harness.github import GitHub
from tools.source_checks import select
from tools.source_policy import scan_harness_file, validate_harness_distribution, review_policy
from concurrent.futures import ThreadPoolExecutor


def source_config():
    config = read_json(ROOT / "tools/source-publication.json")
    if config.get("schema_version") != 1 or config.get("operation") != "source":
        raise HarnessError("Inspect the exact primary-source publication binding")
    return config


def source_adapter(changed=(), *, full=False, additional_modules=()):
    command = [sys.executable, "-B", "-X", "utf8", "tools/source_checks.py"]
    if full:
        command.append("--full")
    for name in sorted(changed):
        command += ["--changed", name]
    checks = [[sys.executable, "-B", "-X", "utf8", "tools/check_public_source.py", "--snapshot", "{source}", "--inventory", "{source}/../build.json"], command]
    if additional_modules:
        checks.append([sys.executable, "-B", "-X", "utf8", "-m", "unittest", *sorted(additional_modules), "-v"])
    return {"schema_version": 1, "purpose": "source", "build": [], "artifacts": [], "checks": checks}


def _tree_entries(commit):
    result = {}
    for entry in filter(None, git(ROOT, "ls-tree", "-rz", "--full-tree", commit).split("\0")):
        metadata, name = entry.split("\t", 1)
        mode, kind, oid = metadata.split()
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise HarnessError("Source verification contains unsupported objects")
        result[name] = {"mode": mode, "sha": oid}
    return result


def _test_modules(commit):
    return {"tests." + Path(name).stem for name in _tree_entries(commit)
            if name.startswith("tests/test_") and name.endswith(".py") and "/" not in name[6:]}


def _covered(selection, commit):
    return _test_modules(commit) if selection["full"] else set(selection["modules"])


def verification_adapter(proof):
    return source_adapter(proof["check_changed"], full=proof["runner_full"], additional_modules=proof["additional_modules"])


def _version_literal_only(before, after):
    def normalized(text):
        tree = ast.parse(text)
        assignments = [node for node in tree.body if isinstance(node, ast.Assign) and len(node.targets) == 1
                       and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "__version__"]
        if len(assignments) != 1 or not isinstance(assignments[0].value, ast.Constant) or not isinstance(assignments[0].value.value, str):
            return None
        assignments[0].value = ast.Constant(value="version metadata")
        return ast.dump(tree, include_attributes=False)
    previous, current = normalized(before), normalized(after)
    return previous is not None and previous == current


def _test_consumers(receipt_path, receipt, head, changed):
    """Invalidate static fixture consumers in both committed import graphs."""
    old_entries = _tree_entries(receipt["source"]["commit"])
    new_entries = _tree_entries(head)
    names = {name for name in old_entries.keys() | new_entries.keys() if name.startswith("tests/") and name.endswith(".py")}
    modules = {name: name[:-3].replace("/", ".").removesuffix(".__init__") for name in names}
    known = set(modules.values())
    imports = {}
    for entries, current in ((old_entries, False), (new_entries, True)):
        for name in names & entries.keys():
            if not current or old_entries.get(name) == entries[name]:
                text = (receipt_path.parent / "source" / name).read_text(encoding="utf-8")
            else:
                text = git(ROOT, "show", head + ":" + name)
            module = modules[name]
            package = module if name.endswith("/__init__.py") else module.rpartition(".")[0]
            dependencies = imports.setdefault(module, set())
            for node in ast.walk(ast.parse(text, filename=name)):
                if isinstance(node, ast.Import):
                    dependencies.update(alias.name for alias in node.names if alias.name in known)
                elif isinstance(node, ast.ImportFrom):
                    base = node.module or ""
                    if node.level:
                        prefix = package.split(".")[:len(package.split(".")) - node.level + 1]
                        base = ".".join([*prefix, *([base] if base else [])])
                    dependencies.update(candidate for candidate in [base, *(base + "." + alias.name for alias in node.names)] if candidate in known)
    affected = {modules[name] for name in changed if name in modules}
    while True:
        following = affected | {module for module, dependencies in imports.items() if dependencies & affected}
        if following == affected:
            return affected & _test_modules(head)
        affected = following


def _check_adapter(receipt_path, receipt, adapter):
    variables = {"source": str(receipt_path.parent / "source"), "output": str(receipt_path.parent / "output"), "version": receipt["version"]}
    expected = build.adapter_commands(adapter["checks"], variables)
    if (receipt["adapter_sha256"] != digest(adapter) or [row["argv"] for row in receipt["commands"]] != expected
            or any(row["kind"] != "checks" for row in receipt["commands"])):
        raise HarnessError("Reuse needs the actual retained privacy and source-check adapter")


def _checked_receipt(path, expected_sha256=None, seen=()):
    """Read retained successful checks; never promote partial logs into passes."""
    path = Path(path).resolve()
    if path in seen or len(seen) >= 16:
        raise HarnessError("Source verification reuse chain is cyclic or too deep")
    if expected_sha256 is not None and file_hash(path) != expected_sha256:
        raise HarnessError("Reused build receipt drift")
    receipt = build.verify_evidence(path)
    if receipt.get("purpose") != "source" or Path(receipt["source_root"]).resolve() != ROOT.resolve():
        raise HarnessError("Reuse requires this producer's source-only verified build")
    commit = receipt["source"]["commit"]
    entries = _tree_entries(commit)
    if (receipt["source"].get("object_format") != "sha1" or receipt["source"]["tree"] != git(ROOT, "rev-parse", commit + "^{tree}")
            or set(entries) != set(receipt["source"]["files"]) or set(entries) != set(receipt["source"]["modes"])):
        raise HarnessError("Reused source inventory differs from actual committed Git objects")
    for name, entry in entries.items():
        if entry["mode"] != receipt["source"]["modes"][name] or publication.blob_sha((path.parent / "source" / name).read_bytes()) != entry["sha"]:
            raise HarnessError("Reused source bytes/modes differ from actual committed Git objects")
    proof = receipt.get("source_verification")
    if proof is not None:
        expected = verification_plan(commit, proof["public_changed"], full=proof["explicit_full"],
                                     reuse_build_receipt=proof["reuse"]["receipt"], reuse_sha256=proof["reuse"]["sha256"], seen=(*seen, path))
        if proof != expected:
            raise HarnessError("Reused source coverage drift")
        changed, full = proof["check_changed"], proof["runner_full"]
        additional = proof["additional_modules"]
        adapter = verification_adapter(proof)
        covered = set(proof["covered_modules"])
    else:
        # Legacy receipts still contain the actual arguments and retained log.
        # Generic successful commands cannot claim source-suite coverage.
        if len(receipt["commands"]) != 2:
            raise HarnessError("Reuse needs the actual retained privacy and source-check adapter")
        command = receipt["commands"][1]["argv"]
        prefix = [sys.executable, "-B", "-X", "utf8", "tools/source_checks.py"]
        if command[:len(prefix)] != prefix:
            raise HarnessError("Reuse needs the actual retained privacy and source-check adapter")
        args, changed, full = command[len(prefix):], [], False
        if args[:1] == ["--full"]:
            full, args = True, args[1:]
        while args:
            if len(args) < 2 or args[0] != "--changed":
                raise HarnessError("Reused source-check arguments are unsupported")
            changed.append(args[1])
            args = args[2:]
        adapter = source_adapter(changed, full=full)
        covered = _covered(select(changed, full=full), commit)
    _check_adapter(path, receipt, adapter)
    selection = select(changed, full=full)
    header = "Source coverage: " + ("full suite" if selection["full"] else ", ".join(selection["modules"]))
    if header not in (path.parent / "command-2.log").read_text(encoding="utf-8").splitlines():
        raise HarnessError("Retained source-check log does not establish the selected coverage")
    return receipt, covered


def verification_plan(head, public_changed, *, full=False, reuse_build_receipt, reuse_sha256=None, seen=()):
    """Separate current export checks from already passed, unchanged test scope."""
    if full:
        raise HarnessError("Explicit --full requests a new suite; omit reuse for that run")
    path = Path(reuse_build_receipt).resolve()
    receipt, previous = _checked_receipt(path, reuse_sha256, seen)
    changed = sorted(filter(None, git(ROOT, "diff", "--no-renames", "--name-only", "-z", receipt["source"]["commit"], head).split("\0")))
    shared = bool(set(changed) & {"tools/source_checks.py", "tests/__init__.py"})
    if "oasis_harness/__init__.py" in changed:
        before = (path.parent / "source/oasis_harness/__init__.py").read_text(encoding="utf-8") if "oasis_harness/__init__.py" in receipt["source"]["files"] else ""
        after = git(ROOT, "show", head + ":oasis_harness/__init__.py")
        shared = shared or not _version_literal_only(before, after)
    selected = select(changed, full=shared)
    executed = _covered(selected, head)
    required = _covered(select(public_changed), head)
    consumers = set() if selected["full"] else _test_consumers(path, receipt, head, changed)
    # A changed shared/unknown input invalidates the earlier runtime scope.
    reused = set() if selected["full"] else previous & required - executed - consumers
    additional = sorted((required | consumers) - executed - reused)
    return {"schema_version": 1, "public_changed": sorted(public_changed), "explicit_full": False,
            "check_changed": changed, "runner_full": selected["full"], "executed": selected, "additional_modules": additional,
            "reused_modules": sorted(reused), "covered_modules": sorted(executed | reused | set(additional)),
            "reuse": {"receipt": str(path), "sha256": file_hash(path), "source_commit": receipt["source"]["commit"]}}


class SourcePolicy:
    """This checkout's rules only; passed explicitly to the neutral publisher."""
    def __init__(self, reviewed):
        self.reviewed = review_policy(reviewed)
        self.name = "primary-source:" + digest(self.reviewed)

    def scan_file(self, name, data):
        return scan_harness_file(name, data, self.reviewed)

    def validate_projection(self, files, modes):
        return validate_harness_distribution(files, self.reviewed, modes=modes)


def current_policy():
    return SourcePolicy(read_json(ROOT / "tools/public-source-policy.json")["reviewed"])


class SourcePublisher(publication.Publisher):
    def __init__(self, candidate, sha256, provider=None):
        super().__init__(candidate, sha256, provider, policy=current_policy())
        selected = source_config()
        if any(self.config.get(key) != selected.get(key) for key in
               ("repository", "repository_id", "base_branch", "operation", "channel", "required_checks")) or self.spec["account_id"] != selected["account_id"]:
            raise HarnessError("Source candidate differs from this primary source's selected binding")

    def verify_source(self, commit):
        # Concurrent anonymous reads shorten delivery without reducing coverage.
        def verify(item):
            name, row = item
            data = self.provider.download_source(self.slug, commit, name)
            if publication.blob_sha(data) != row["sha"]:
                raise HarnessError("Anonymous public source differs from approved bytes")
            self.policy.scan_file(name, data)
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(verify, self.spec["projection"].items()))


def changes_from_public(provider, config, head):
    base = publication.branch_head(provider, config["repository"], config["base_branch"])
    _, remote = publication.remote_tree(provider, config["repository"], base)
    local = {}
    for entry in filter(None, git(ROOT, "ls-tree", "-rz", "--full-tree", head).split("\0")):
        metadata, name = entry.split("\t", 1)
        mode, kind, sha = metadata.split()
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise HarnessError("Source contains unsupported objects")
        local[name] = {"mode": mode, "sha": sha}
    names = set(local) | (set(remote) - {publication.PUBLIC_MANIFEST})
    return base, sorted(name for name in names if local.get(name) != remote.get(name))


def source_head():
    if git(ROOT, "branch", "--show-current") != "main":
        raise HarnessError("Source delivery requires the actual main checkout")
    head = git(ROOT, "rev-parse", "HEAD")
    if head != git(ROOT, "rev-parse", "refs/heads/main"):
        raise HarnessError("Source delivery HEAD differs from actual main")
    return head


def prepare(destination, title, notes, provider=None, *, full=False, remove_public_files=(), reuse_build_receipt=None):
    provider = provider or GitHub()
    config = source_config()
    if git(ROOT, "status", "--porcelain=v1", "--untracked-files=all"):
        raise HarnessError("Source delivery requires clean owned committed source")
    head = source_head()
    backup_status = backup.status(ROOT, provider=provider)
    if not backup_status.get("source_main_match", backup_status.get("source_refs_match")):
        raise HarnessError("Private snapshot must match the actual source before public preparation")
    if provider.authenticated_user()["id"] != config["account_id"]:
        raise HarnessError("Source delivery account changed")
    destination = Path(destination).resolve()
    if destination.exists() or destination.is_relative_to(ROOT) or ROOT.is_relative_to(destination):
        raise HarnessError("Use a new external delivery evidence directory")
    # A command uses argument arrays and executes only the already reviewed
    # committed source. Raw source and logs stay in external private evidence.
    base, changed = changes_from_public(provider, config, head)
    proof = verification_plan(head, changed, full=full, reuse_build_receipt=reuse_build_receipt) if reuse_build_receipt is not None else None
    adapter = verification_adapter(proof) if proof else source_adapter(changed, full=full)
    # Version comes from the committed tree, not a duplicated guide literal.
    import ast
    text = git(ROOT, "show", head + ":oasis_harness/__init__.py")
    version = next(ast.literal_eval(node.value) for node in ast.parse(text).body if isinstance(node, ast.Assign)
                   and any(isinstance(name, ast.Name) and name.id == "__version__" for name in node.targets))
    result = build.execute(ROOT, head, adapter, destination / "build", version)
    receipt = build.verify_evidence(result["receipt"])
    if proof:
        receipt["source_verification"] = proof
        write_json(result["receipt"], receipt)
    policy = read_json(destination / "build/source/tools/public-source-policy.json")
    publication_config = {"schema_version": 1, "repository": config["repository"], "repository_id": config["repository_id"],
                          "base_branch": config["base_branch"], "channel": config["channel"], "operation": "source",
                          "mode": "source-and-artifacts", "version": version, "tag": None, "title": title,
                          "make_latest": False, "exports": {name: name for name in sorted(receipt["source"]["files"])},
                          "required_checks": config["required_checks"], "source_policy": SourcePolicy(policy["reviewed"]).name,
                          "remove_public_files": list(remove_public_files)}
    write_json(destination / "publication.json", publication_config)
    (destination / "notes.md").write_bytes(Path(notes).read_bytes())
    coverage = {**select(changed, full=full), "base_commit": base, "explicit_full": full}
    if proof:
        coverage["verification"] = proof
    write_json(destination / "coverage.json", coverage)
    result = publication.prepare(destination / "publication.json", result["receipt"], destination / "notes.md", destination / "candidate", provider,
                                 policy=SourcePolicy(policy["reviewed"]))
    if result["base"] != base:
        raise HarnessError("Public base changed during checks; retain evidence and prepare again")
    return result


def attest(candidate, sha256, receipt_path, authority, provider=None):
    """Bridge the exact local build/scan evidence to one verified public PR head."""
    publication.require_authority(authority)
    provider = provider or GitHub()
    publisher = SourcePublisher(candidate, sha256, provider)
    publisher.check_target()
    selected = source_config()
    if any(publisher.config.get(key) != selected.get(key) for key in
           ("repository", "repository_id", "base_branch", "operation", "channel", "required_checks")) or publisher.spec["account_id"] != selected["account_id"]:
        raise HarnessError("Attestation differs from this primary source's selected binding")
    if publisher.config.get("operation") != "source":
        raise HarnessError("Attestation applies only to the selected Harness source adapter")
    if file_hash(receipt_path) != publisher.spec["build_receipt_sha256"]:
        raise HarnessError("Attestation build receipt differs from the candidate")
    head = source_head()
    receipt = build.verify_evidence(receipt_path)
    if Path(receipt["source_root"]).resolve() != ROOT.resolve() or receipt["source"]["commit"] != head or receipt["source"]["tree"] != git(ROOT, "rev-parse", "HEAD^{tree}"):
        raise HarnessError("Attestation source root/commit/tree drifted from this producer")
    scanner_spec = importlib.util.spec_from_file_location("source_delivery_scanner", Path(__file__).with_name("check_public_source.py"))
    scanner = importlib.util.module_from_spec(scanner_spec)
    scanner_spec.loader.exec_module(scanner)
    actual_files, actual_modes = scanner.candidate(ROOT, receipt["source"]["commit"])
    if {name: digest(data) for name, data in actual_files.items()} != receipt["source"]["files"] or actual_modes != receipt["source"]["modes"]:
        raise HarnessError("Attestation receipt inventory differs from actual committed Git objects")
    current_backup = backup.status(ROOT, provider=provider)
    if not current_backup.get("source_main_match", current_backup.get("source_refs_match")):
        raise HarnessError("Attestation requires the exact producer commit's verified private recovery")
    coverage = read_json(Path(candidate).parent / "coverage.json")
    if type(coverage.get("explicit_full")) is not bool:
        raise HarnessError("Source coverage needs an explicit boolean full-suite selection")
    base, changed = changes_from_public(provider, selected, receipt["source"]["commit"])
    expected_coverage = {**select(changed, full=coverage["explicit_full"]), "base_commit": base, "explicit_full": coverage["explicit_full"]}
    proof = coverage.get("verification")
    if proof is not None:
        expected_proof = verification_plan(receipt["source"]["commit"], changed, full=coverage["explicit_full"],
                                           reuse_build_receipt=proof["reuse"]["receipt"], reuse_sha256=proof["reuse"]["sha256"])
        if proof != expected_proof or receipt.get("source_verification") != expected_proof:
            raise HarnessError("Source verification reuse differs from retained actual inputs/checks")
        expected_coverage["verification"] = expected_proof
    elif receipt.get("source_verification") is not None:
        raise HarnessError("Source reuse evidence is missing from candidate coverage")
    if coverage != expected_coverage or base != publisher.spec["base_commit"]:
        raise HarnessError("Source impact coverage differs from the actual public base")
    expected_adapter = verification_adapter(proof) if proof else source_adapter(changed, full=coverage["explicit_full"])
    variables = {"source": str(Path(receipt_path).resolve().parent / "source"),
                 "output": str(Path(receipt_path).resolve().parent / "output"), "version": receipt["version"]}
    expected_commands = build.adapter_commands(expected_adapter["checks"], variables)
    if receipt["adapter_sha256"] != digest(expected_adapter) or [row["argv"] for row in receipt["commands"]] != expected_commands or any(row["kind"] != "checks" for row in receipt["commands"]):
        raise HarnessError("Attestation needs the actual retained privacy and impact-selected source adapter")
    if receipt["source"] != publisher.spec["private_producer"] or receipt.get("purpose") != "source":
        raise HarnessError("Attestation source evidence differs")
    if set(publisher.config["exports"]) != set(receipt["source"]["files"]) or any(source != target for source, target in publisher.config["exports"].items()):
        raise HarnessError("Attestation requires the exact complete source projection")
    for name, expected in receipt["source"]["files"].items():
        row = publisher.spec["public_files"].get(name, {})
        if row.get("sha256") != expected or row.get("mode") != receipt["source"]["modes"][name]:
            raise HarnessError("Attestation public bytes/modes differ from checked source")
    publication.scan_projection(provider, publisher.slug, publisher.spec["projection"], publisher.config,
                                {name: (Path(candidate) / row["file"]).read_bytes() for name, row in publisher.spec["public_files"].items()}, publisher.policy)
    head = publisher.state.get("candidate_commit")
    if not head or not publisher.state.get("pr_number"):
        raise HarnessError("Prepare the exact PR before attestation; preserve its candidate")
    publisher.check_commit(head, publisher.spec["base_commit"])
    pr = provider.request("GET", publisher.prefix + f"/pulls/{publisher.state['pr_number']}")
    publisher.check_pr(pr)
    if pr.get("merged") or publication.branch_head(provider, publisher.slug, publisher.config["base_branch"]) != publisher.spec["base_commit"]:
        raise HarnessError("Attestation cannot approve a merged or drifted candidate")
    contexts = publisher.config["required_checks"]
    if contexts != ["oasis-source-checks"]:
        raise HarnessError("Unknown source status bridge; inspect the selected checks")
    result = provider.request("POST", publisher.prefix + f"/statuses/{head}", {
        "state": "success", "context": contexts[0], "description": "Exact source, privacy gate and impact-selected tests verified", "target_url": pr["html_url"]})
    if result.get("sha", head) != head or result.get("context") != contexts[0] or result.get("state") != "success":
        raise HarnessError("Source status attestation readback is uncertain")
    return {"verified_head": head, "context": contexts[0], "candidate_sha256": sha256,
            "receipt_sha256": file_hash(receipt_path), "authority_is_external": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    child = commands.add_parser("prepare")
    child.add_argument("--destination", type=Path, required=True)
    child.add_argument("--title", required=True)
    child.add_argument("--notes", type=Path, required=True)
    child.add_argument("--full", action="store_true", help="Explicit full-suite run instead of impact selection")
    child.add_argument("--reuse-build-receipt", type=Path, help="Retained verified source checks; run only checks invalidated since this snapshot")
    child.add_argument("--remove-public-file", action="append", default=[])
    child = commands.add_parser("execute")
    child.add_argument("--candidate", type=Path, required=True)
    child.add_argument("--sha256", required=True)
    child.add_argument("--authority", required=True)
    child = commands.add_parser("attest")
    child.add_argument("--candidate", type=Path, required=True)
    child.add_argument("--sha256", required=True)
    child.add_argument("--build-receipt", type=Path, required=True)
    child.add_argument("--authority", required=True)
    args = parser.parse_args()
    try:
        if args.operation == "prepare":
            result = prepare(args.destination, args.title, args.notes, full=args.full, remove_public_files=args.remove_public_file,
                             reuse_build_receipt=args.reuse_build_receipt)
        elif args.operation == "execute":
            result = SourcePublisher(args.candidate, args.sha256).execute(args.authority)
        else:
            result = attest(args.candidate, args.sha256, args.build_receipt, args.authority)
        print(json.dumps(result, ensure_ascii=True))
    except (HarnessError, OSError, ValueError) as exc:
        print("Source delivery stopped: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
