"""Primary-source adapter for reviewed public projection and private recovery.

Configure the repositories separately. This tool never converts visibility,
creates a backup repository, edits settings, bypasses checks or grants approval.
"""
from __future__ import annotations

import argparse
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


def source_adapter(changed=(), *, full=False):
    command = [sys.executable, "-B", "-X", "utf8", "tools/source_checks.py"]
    if full:
        command.append("--full")
    for name in sorted(changed):
        command += ["--changed", name]
    return {"schema_version": 1, "purpose": "source", "build": [], "artifacts": [],
            "checks": [[sys.executable, "-B", "-X", "utf8", "tools/check_public_source.py", "--snapshot", "{source}", "--inventory", "{source}/../build.json"],
                       command]}


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


def prepare(destination, title, notes, provider=None, *, full=False, remove_public_files=()):
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
    adapter = source_adapter(changed, full=full)
    # Version comes from the committed tree, not a duplicated guide literal.
    import ast
    text = git(ROOT, "show", head + ":oasis_harness/__init__.py")
    version = next(ast.literal_eval(node.value) for node in ast.parse(text).body if isinstance(node, ast.Assign)
                   and any(isinstance(name, ast.Name) and name.id == "__version__" for name in node.targets))
    result = build.execute(ROOT, head, adapter, destination / "build", version)
    receipt = build.verify_evidence(result["receipt"])
    policy = read_json(destination / "build/source/tools/public-source-policy.json")
    publication_config = {"schema_version": 1, "repository": config["repository"], "repository_id": config["repository_id"],
                          "base_branch": config["base_branch"], "channel": config["channel"], "operation": "source",
                          "mode": "source-and-artifacts", "version": version, "tag": None, "title": title,
                          "make_latest": False, "exports": {name: name for name in sorted(receipt["source"]["files"])},
                          "required_checks": config["required_checks"], "source_policy": SourcePolicy(policy["reviewed"]).name,
                          "remove_public_files": list(remove_public_files)}
    write_json(destination / "publication.json", publication_config)
    (destination / "notes.md").write_bytes(Path(notes).read_bytes())
    write_json(destination / "coverage.json", {**select(changed, full=full), "base_commit": base, "explicit_full": full})
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
    if coverage != expected_coverage or base != publisher.spec["base_commit"]:
        raise HarnessError("Source impact coverage differs from the actual public base")
    expected_adapter = source_adapter(changed, full=coverage["explicit_full"])
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
            result = prepare(args.destination, args.title, args.notes, full=args.full, remove_public_files=args.remove_public_file)
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
