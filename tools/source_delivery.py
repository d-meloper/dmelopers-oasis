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
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from oasis_harness import backup, build, publication
from oasis_harness.common import HarnessError, digest, file_hash, git, git_objects, read_json, write_json
from oasis_harness.github import GitHub
from tools.source_checks import select, test_consumers
from tools.source_policy import scan_harness_file, validate_harness_distribution, review_policy, MAX_FILE_BYTES
from concurrent.futures import ThreadPoolExecutor


def source_config():
    config = read_json(ROOT / "tools/source-publication.json")
    if config.get("schema_version") != 1 or config.get("operation") != "source":
        raise HarnessError("Inspect the exact primary-source publication binding")
    return config


def source_adapter(changed=(), *, full=False, additional_modules=(), version_literal_only=False):
    command = [sys.executable, "-B", "-X", "utf8", "tools/source_checks.py"]
    if full:
        command.append("--full")
    if version_literal_only:
        command.append("--version-literal-only")
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


def _committed_selector(commit):
    entries = _tree_entries(commit)
    names = {name: row["sha"] for name, row in entries.items() if name.startswith("tests/") and name.endswith(".py")}
    blobs = {oid: data.decode("utf-8") for oid, kind, data in git_objects(ROOT, list(dict.fromkeys(names.values()))) if kind == "blob"}
    texts = {name: blobs[oid] for name, oid in names.items()}
    return lambda changed, **kwargs: select(changed, fixture_consumers=test_consumers(changed, texts), **kwargs)


def verification_adapter(proof):
    return source_adapter(proof["check_changed"], full=proof["runner_full"], additional_modules=proof["additional_modules"],
                          version_literal_only=proof.get("version_literal_only", False))


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
    updated = {name: new_entries[name]["sha"] for name in names & new_entries.keys() if old_entries.get(name) != new_entries[name]}
    new_text = {}
    for oid, kind, data in git_objects(ROOT, list(dict.fromkeys(updated.values()))):
        if kind != "blob":
            raise HarnessError("Test input is not a regular blob")
        new_text[oid] = data.decode("utf-8")
    for entries, current in ((old_entries, False), (new_entries, True)):
        for name in names & entries.keys():
            if not current or old_entries.get(name) == entries[name]:
                text = (receipt_path.parent / "source" / name).read_text(encoding="utf-8")
            else:
                text = new_text[entries[name]["sha"]]
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


def _retained_selector(receipt_path):
    """Read historical selection data without importing/executing old code."""
    tree = ast.parse((receipt_path.parent / "source/tools/source_checks.py").read_text(encoding="utf-8"))
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id in {"SMOKE", "DEPENDENTS"}:
            values[node.targets[0].id] = ast.literal_eval(node.value)
    smoke, dependencies = values.get("SMOKE"), values.get("DEPENDENTS")
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "select"]
    if (not isinstance(smoke, set) or any(not isinstance(name, str) for name in smoke) or
            not isinstance(dependencies, dict) or any(not isinstance(key, str) or not isinstance(items, set) or
                any(not isinstance(item, str) for item in items) for key, items in dependencies.items()) or len(functions) != 1):
        raise HarnessError("Retained source selector is not a supported coverage policy")
    modern = any(arg.arg == "version_literal_only" for arg in functions[0].args.kwonlyargs)
    has_consumers = any(arg.arg == "fixture_consumers" for arg in functions[0].args.kwonlyargs)
    texts = {name: (receipt_path.parent / "source" / name).read_text(encoding="utf-8")
             for name in read_json(receipt_path)["source"]["files"] if name.startswith("tests/") and name.endswith(".py")} if has_consumers else {}
    def selection(changed, *, full=False, version_literal_only=False):
        return select(changed, full=full, version_literal_only=version_literal_only, _legacy=not modern,
                      _dependents=dependencies, _smoke=smoke, fixture_consumers=test_consumers(changed, texts))
    return selection, not modern


def _environment_changes(previous, current, modules):
    if previous is None:
        return "unknown-legacy", set(), False
    if previous.get("python") != current.get("python") or previous.get("platform") != current.get("platform") or previous.get("env") != current.get("env"):
        return "changed", set(modules), True
    git_modules = {"tests.test_backup", "tests.test_build", "tests.test_commit_version", "tests.test_gitops",
                   "tests.test_skills", "tests.test_source_delivery", "tests.test_publication", "tests.test_public_source"}
    if previous.get("git") != current.get("git"):
        return "changed", set(modules) & git_modules, False
    return "matched", set(), False


def _checked_receipt(path, expected_sha256=None, seen=()):
    """Read retained successful checks; never promote partial logs into passes."""
    path = Path(path).resolve()
    if path in seen or len(seen) >= 16:
        raise HarnessError("Source verification reuse chain is cyclic or reached depth 16; inspect status and select an existing full baseline with --reuse-build-receipt; no automatic full run")
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
    selection, legacy = _retained_selector(path)
    proof = receipt.get("source_verification")
    if proof is not None:
        expected = verification_plan(commit, proof["public_changed"], full=proof["explicit_full"],
                                     reuse_build_receipt=proof["reuse"]["receipt"], reuse_sha256=proof["reuse"]["sha256"], seen=(*seen, path),
                                     _selection=selection, _legacy=legacy,
                                     _environment=receipt.get("execution_environment"),
                                     public_version_literal_only=proof.get("public_version_literal_only", False))
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
        args, changed, full, literal_only = command[len(prefix):], [], False, False
        if args[:1] == ["--full"]:
            full, args = True, args[1:]
        if args[:1] == ["--version-literal-only"]:
            literal_only, args = True, args[1:]
        while args:
            if len(args) < 2 or args[0] != "--changed":
                raise HarnessError("Reused source-check arguments are unsupported")
            changed.append(args[1])
            args = args[2:]
        adapter = source_adapter(changed, full=full, version_literal_only=literal_only)
        covered = _covered(selection(changed, full=full, version_literal_only=literal_only), commit)
    _check_adapter(path, receipt, adapter)
    selected = selection(changed, full=full, version_literal_only=proof.get("version_literal_only", False) if proof else literal_only)
    header = "Source coverage: " + ("full suite" if selected["full"] else ", ".join(selected["modules"]))
    if header not in (path.parent / "command-2.log").read_text(encoding="utf-8").splitlines():
        raise HarnessError("Retained source-check log does not establish the selected coverage")
    return receipt, covered


def verification_plan(head, public_changed, *, full=False, reuse_build_receipt, reuse_sha256=None, seen=(),
                      public_version_literal_only=False, _selection=None, _legacy=False, _environment=None):
    """Separate current export checks from already passed, unchanged test scope."""
    if full:
        raise HarnessError("Explicit --full requests a new suite; omit reuse for that run")
    path = Path(reuse_build_receipt).resolve()
    receipt, previous = _checked_receipt(path, reuse_sha256, seen)
    selector = _committed_selector(head) if _selection is None else _selection
    changed = sorted(filter(None, git(ROOT, "diff", "--no-renames", "--name-only", "-z", receipt["source"]["commit"], head).split("\0")))
    shared = bool(set(changed) & {"tools/source_checks.py", "tests/__init__.py"})
    literal_only = False
    if "oasis_harness/__init__.py" in changed:
        before = (path.parent / "source/oasis_harness/__init__.py").read_text(encoding="utf-8") if "oasis_harness/__init__.py" in receipt["source"]["files"] else ""
        after = git(ROOT, "show", head + ":oasis_harness/__init__.py")
        literal_only = _version_literal_only(before, after)
        shared = shared or not literal_only
    environment = {} if _legacy else _environment if _environment is not None else build.execution_environment(ROOT, list(receipt.get("execution_environment", {}).get("env", {})))
    environment_match, invalidated, environment_full = _environment_changes(receipt.get("execution_environment"), environment, _test_modules(head)) if not _legacy else ("unknown-legacy", set(), False)
    selected = selector(changed, full=shared or environment_full, version_literal_only=literal_only)
    executed = _covered(selected, head)
    required = _covered(selector(public_changed, version_literal_only=public_version_literal_only), head)
    consumers = set() if selected["full"] else _test_consumers(path, receipt, head, changed)
    # A changed shared/unknown input invalidates the earlier runtime scope.
    reused = set() if selected["full"] else previous & required - executed - consumers - invalidated
    additional = sorted((required | consumers | invalidated) - executed - reused)
    result = {"schema_version": 1, "public_changed": sorted(public_changed), "explicit_full": False,
            "check_changed": changed, "runner_full": selected["full"], "executed": selected, "additional_modules": additional,
            "reused_modules": sorted(reused), "covered_modules": sorted(executed | reused | set(additional)),
            "reuse": {"receipt": str(path), "sha256": file_hash(path), "source_commit": receipt["source"]["commit"]}}
    if not _legacy:
        result.update(version_literal_only=literal_only, public_version_literal_only=public_version_literal_only,
                      selection_policy=2, environment_match=environment_match, environment_invalidated_modules=sorted(invalidated))
    return result


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
            bounded = getattr(self.provider, "download_source_bounded", None)
            local = self.spec.get("public_files", {}).get(name)
            size = (self.dest / local["file"]).stat().st_size if local else None
            data = bounded(self.slug, commit, name, max_bytes=MAX_FILE_BYTES, expected_size=size) if callable(bounded) else self.provider.download_source(self.slug, commit, name)
            if len(data) > MAX_FILE_BYTES or size is not None and len(data) != size:
                raise HarnessError("Anonymous public source size differs from approved bytes")
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


def public_version_literal_only(provider, config, base, head, changed):
    name = "oasis_harness/__init__.py"
    if name not in changed:
        return False
    _, remote = publication.remote_tree(provider, config["repository"], base)
    if name not in remote:
        return False
    before = publication.read_blob(provider, config["repository"], remote[name]["sha"]).decode("utf-8")
    after = git(ROOT, "show", head + ":" + name)
    return _version_literal_only(before, after)


def source_head():
    if git(ROOT, "branch", "--show-current") != "main":
        raise HarnessError("Source delivery requires the actual main checkout")
    head = git(ROOT, "rev-parse", "HEAD")
    if head != git(ROOT, "rev-parse", "refs/heads/main"):
        raise HarnessError("Source delivery HEAD differs from actual main")
    return head


def delivery_destination(destination=None):
    destination = destination if destination is not None else ROOT / ".oasis/local/deliveries" / uuid.uuid4().hex
    destination = build.evidence_destination(ROOT, destination)
    if destination.exists():
        raise HarnessError("Use a new delivery evidence directory; retain existing runs")
    return destination


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
    destination = delivery_destination(destination)
    # A command uses argument arrays and executes only the already reviewed
    # committed source. Raw source and logs stay in private retained evidence.
    base, changed = changes_from_public(provider, config, head)
    literal_only = public_version_literal_only(provider, config, base, head, changed)
    proof = verification_plan(head, changed, full=full, reuse_build_receipt=reuse_build_receipt,
                              public_version_literal_only=literal_only) if reuse_build_receipt is not None else None
    adapter = verification_adapter(proof) if proof else source_adapter(changed, full=full, version_literal_only=literal_only)
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
    coverage = {**_committed_selector(head)(changed, full=full, version_literal_only=literal_only), "base_commit": base, "explicit_full": full,
                "version_literal_only": literal_only}
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
    literal_only = public_version_literal_only(provider, selected, base, receipt["source"]["commit"], changed)
    expected_coverage = {**_committed_selector(receipt["source"]["commit"])(changed, full=coverage["explicit_full"], version_literal_only=literal_only), "base_commit": base,
                         "explicit_full": coverage["explicit_full"], "version_literal_only": literal_only}
    if "version_literal_only" not in coverage and not literal_only:
        expected_coverage.pop("version_literal_only")
    proof = coverage.get("verification")
    if proof is not None:
        expected_proof = verification_plan(receipt["source"]["commit"], changed, full=coverage["explicit_full"],
                                           reuse_build_receipt=proof["reuse"]["receipt"], reuse_sha256=proof["reuse"]["sha256"],
                                           public_version_literal_only=literal_only)
        if proof != expected_proof or receipt.get("source_verification") != expected_proof:
            raise HarnessError("Source verification reuse differs from retained actual inputs/checks")
        expected_coverage["verification"] = expected_proof
    elif receipt.get("source_verification") is not None:
        raise HarnessError("Source reuse evidence is missing from candidate coverage")
    if coverage != expected_coverage or base != publisher.spec["base_commit"]:
        raise HarnessError("Source impact coverage differs from the actual public base")
    expected_adapter = verification_adapter(proof) if proof else source_adapter(changed, full=coverage["explicit_full"], version_literal_only=literal_only)
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


def reuse_chain(path):
    """Explain retained references; this inventory does not certify their checks."""
    seen, full_baselines = set(), []
    cursor = Path(path).resolve()
    while cursor not in seen and len(seen) < 64:
        seen.add(cursor)
        value = read_json(cursor)
        if not isinstance(value, dict):
            raise HarnessError("Reuse receipt must be a JSON object")
        proof = value.get("source_verification")
        if proof is None:
            commands = value.get("commands", [])
            if len(commands) > 1 and "--full" in commands[1].get("argv", []):
                full_baselines.append(str(cursor))
            break
        if proof.get("runner_full"):
            full_baselines.append(str(cursor))
        cursor = Path(proof["reuse"]["receipt"]).resolve()
    return {"depth": len(seen), "maximum_reuse_depth": 16, "cycle": cursor in seen and proof is not None,
            "existing_full_baselines": full_baselines, "evidence_verified": False}


def status(candidate, sha256, *, remote=False, provider=None):
    dest, spec, state = publication.load_candidate(candidate, sha256)
    selected = source_config()
    config = spec["config"]
    if any(config.get(key) != selected.get(key) for key in ("repository", "repository_id", "base_branch", "operation", "channel", "required_checks")) or spec["account_id"] != selected["account_id"]:
        raise HarnessError("Status candidate differs from the selected source binding")
    observed = {"pull_request": bool(state.get("pr_number")), "merge": bool(state.get("merge_commit")),
                "blob": bool(state.get("candidate_commit")), "tree": bool(state.get("candidate_commit")),
                "commit": bool(state.get("candidate_commit")), "branch": bool(state.get("candidate_commit"))}
    unresolved = [] if state.get("phase") == "source_verified" else [row["operation"] for row in state.get("events", [])
                    if row.get("status") in {"intent", "uncertain_or_rejected"} and not observed.get(row["operation"], False)]
    result = {"candidate_sha256": sha256, "phase": state.get("phase"), "pr_url": state.get("pr_url"),
              "candidate_commit": state.get("candidate_commit"), "public_commit": state.get("public_commit"),
              "uncertain_operations": unresolved, "remote_checked": False, "next_commands": [],
              "authority_verified": False}
    receipt = dest.parent / "build/build.json"
    if receipt.is_file():
        result["reuse_chain"] = reuse_chain(receipt)
    base_argv = [sys.executable, "-B", "-X", "utf8", "tools/source_delivery.py"]
    execute = [*base_argv, "execute", "--candidate", str(dest), "--sha256", sha256, "--authority", "<current-request-reference>"]
    if unresolved:
        result["next"] = "Reconcile the retained uncertain operation with its exact remote identity before retrying"
    elif state.get("phase") == "source_verified":
        result["next"] = "Source delivery is recorded complete; no new publication is requested"
    elif state.get("merge_commit") or state.get("public_commit"):
        result["next_commands"] = [execute]
    elif state.get("pr_number") and state.get("candidate_commit"):
        result["next_commands"] = [[*base_argv, "attest", "--candidate", str(dest), "--sha256", sha256,
                                     "--build-receipt", str(receipt), "--authority", "<current-request-reference>"], execute]
        result["next"] = "Attach the existing PR to the active task and use the reviewed current request"
    else:
        result["next_commands"] = [execute]
    if remote:
        provider = provider or GitHub()
        publication.target_check(provider, config)
        if provider.authenticated_user()["id"] != spec["account_id"]:
            raise HarnessError("Source status account changed")
        current_base = publication.branch_head(provider, config["repository"], config["base_branch"])
        result["current_public_base"] = current_base
        merged = False
        if state.get("pr_number"):
            pr = provider.request("GET", f"/repos/{config['repository']}/pulls/{state['pr_number']}")
            if (pr["number"] != state["pr_number"] or pr["head"]["repo"]["id"] != spec["repository_id"] or pr["base"]["repo"]["id"] != spec["repository_id"] or
                    pr["head"]["sha"] != state.get("candidate_commit") or pr["base"]["ref"] != config["base_branch"] or pr["head"]["ref"] != "oasis-candidate/" + sha256[:24]):
                raise HarnessError("Source status PR identity changed")
            rows = provider.pages(f"/repos/{config['repository']}/commits/{pr['head']['sha']}/statuses")
            latest = {}
            for row in rows:
                latest.setdefault(row["context"], row["state"])
            result["required_checks"] = {name: latest.get(name, "missing") for name in config["required_checks"]}
            merged = result["remote_merged"] = bool(pr.get("merged"))
            if not unresolved and (merged or all(latest.get(name) == "success" for name in config["required_checks"])):
                result["next_commands"] = [] if state.get("phase") == "source_verified" else [execute]
        if not merged and current_base != spec["base_commit"] and state.get("phase") != "source_verified":
            result["next_commands"] = []
            result["next"] = "Public base moved; retain this candidate and prepare a new candidate using valid retained checks"
        result["remote_checked"] = True
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    child = commands.add_parser("prepare")
    child.add_argument("--destination", type=Path, help="New evidence directory; defaults to .oasis/local/deliveries/<unique-run>")
    child.add_argument("--title", required=True)
    child.add_argument("--notes", type=Path, required=True)
    child.add_argument("--full", action="store_true", help="Explicit full-suite run instead of impact selection")
    child.add_argument("--reuse-build-receipt", type=Path, help="Retained verified source checks; run only checks invalidated since this snapshot")
    child.add_argument("--remove-public-file", action="append", default=[])
    child = commands.add_parser("execute")
    child.add_argument("--candidate", type=Path, required=True)
    child.add_argument("--sha256", required=True)
    child.add_argument("--authority", required=True)
    child = commands.add_parser("status")
    child.add_argument("--candidate", type=Path, required=True)
    child.add_argument("--sha256", required=True)
    child.add_argument("--remote", action="store_true", help="Read the selected remote PR/checks; never mutate state")
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
        elif args.operation == "attest":
            result = attest(args.candidate, args.sha256, args.build_receipt, args.authority)
        else:
            result = status(args.candidate, args.sha256, remote=args.remote)
        print(json.dumps(result, ensure_ascii=True))
    except (HarnessError, OSError, ValueError) as exc:
        print("Source delivery stopped: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
