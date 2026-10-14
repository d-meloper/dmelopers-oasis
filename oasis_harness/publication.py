"""Exact-candidate GitHub publication. Local receipts never establish human consent."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import quote

from .build import verify_evidence
from .common import HarnessError, atomic_write, contained, digest, file_hash, operation_lock, read_json, safe_relative, write_json
from .github import GitHub, repository_slug

PUBLIC_MANIFEST = "oasis-release.json"


def enc(value):
    return quote(str(value), safe="")


def public_scan(name, data):
    """A bounded leak gate, not a claim to prove confidentiality of arbitrary bytes."""
    safe_relative(name)
    parts = {part.casefold() for part in name.split("/")}
    if parts & {".git", ".oasis", ".codex", ".agents", "approvals", "receipts"} or any(part.startswith(".env") for part in parts):
        raise HarnessError(f"Private operational path cannot be published: {name}")
    text = data.decode("utf-8", errors="ignore")
    patterns = (r"(?i)[a-z]:[\\/]users[\\/]", r"/Users/[^/]+/", r"/home/[^/]+/",
                r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})\b",
                r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
                r"(?i)(?:CODEX_THREAD_ID|authority_reference|active_permission_profile)\s*[\"'=:\s]")
    if any(re.search(pattern, text) for pattern in patterns):
        raise HarnessError(f"Potential private material in {name}; remove it and prepare a new candidate")
    if re.search(r"https?://[^\s/'\"]+:[^\s/'\"]+@", text):
        raise HarnessError(f"Potential URL credentials in {name}; prepare a sanitized candidate")
    emails = re.findall(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})", text)
    if any(not (domain.endswith((".invalid", ".example")) or domain in {"example.com", "example.org", "example.net"}) for domain in emails):
        raise HarnessError(f"Potential personal email in {name}; prepare a sanitized candidate")


def check_source_policy(config, policy=None):
    """Custom export rules are supplied by an inspected caller, never loaded.

    Candidate data names the exact policy; it cannot select executable code or
    silently fall back to weaker rules when a caller omits that policy.
    """
    selected = config.get("source_policy")
    if "distribution_profile" in config or "scan_review" in config:
        raise HarnessError("Legacy source policy requires a new reviewed candidate")
    if (selected is None and policy is not None) or (selected is not None and
            (not isinstance(selected, str) or not selected or policy is None or policy.name != selected)):
        raise HarnessError("Candidate requires its exact explicitly supplied source policy")


def scan_source_file(name, data, config, policy=None):
    check_source_policy(config, policy)
    return policy.scan_file(name, data) if policy is not None else public_scan(name, data)


def read_blob(provider, slug, sha):
    row = provider.request("GET", f"/repos/{slug}/git/blobs/{sha}")
    try:
        if row["encoding"] != "base64":
            raise ValueError("Unexpected blob encoding")
        data = base64.b64decode("".join(row["content"].split()), validate=True)
        if blob_sha(data) != sha or row.get("size", len(data)) != len(data):
            raise ValueError("Blob hash/size mismatch")
    except (KeyError, TypeError, ValueError) as exc:
        raise HarnessError("Cannot verify complete inherited public bytes") from exc
    return data


def scan_projection(provider, slug, projection, config, local_files, policy=None):
    """Inspect every surviving file, including content inherited from the base."""
    check_source_policy(config, policy)
    files, aliases, blobs = {}, {}, {}
    for name, row in projection.items():
        safe_relative(name)
        parts = name.split("/")
        for index in range(1, len(parts) + 1):
            path = "/".join(parts[:index])
            prior = aliases.setdefault(path.casefold(), path)
            if prior != path:
                raise HarnessError("Public projection has colliding Windows directory paths")
        data = local_files.get(name)
        if data is None:
            if row["sha"] not in blobs:
                blobs[row["sha"]] = read_blob(provider, slug, row["sha"])
            data = blobs[row["sha"]]
        if row["mode"] not in ("100644", "100755") or blob_sha(data) != row["sha"]:
            raise HarnessError("Public projection bytes/mode differ from candidate")
        scan_source_file(name, data, config, policy)
        files[name] = data
    if policy is not None:
        policy.validate_projection(files, {name: row["mode"] for name, row in projection.items()})
    return files


def require_authority(reference):
    if not isinstance(reference, str) or not reference.strip():
        raise HarnessError("A real, current human approval for this exact scope is required; a saved approval file is insufficient")


def target_check(provider, config):
    slug = repository_slug(config["repository"])
    repo = provider.read_repository(slug)
    if repo["id"] != config["repository_id"] or repo["full_name"].casefold() != slug.casefold():
        raise HarnessError("Repository identity changed")
    if repo.get("private") or repo.get("fork") or repo.get("archived") or repo.get("disabled"):
        raise HarnessError("Publication requires the approved active public non-fork repository")
    if repo["default_branch"] != config["base_branch"]:
        raise HarnessError("Repository default branch differs from the approved base")
    if config["channel"] == "preview" and (not config.get("production_repository_id") or config["repository_id"] == config["production_repository_id"]):
        raise HarnessError("Preview requires a separately identified production target and a distinct repository")
    if config.get("operation", "release") == "release" and not (provider.request("GET", f"/repos/{slug}/immutable-releases", allow_404=True) or {}).get("enabled"):
        raise HarnessError("Enable immutable releases through separately approved repository setup first")
    if provider.request("GET", f"/repos/{slug}/hash-algorithm").get("hash_algorithm") != "sha1":
        raise HarnessError("Public tree adapter currently supports GitHub SHA-1 only; no objects will be written")
    return repo


def remote_tree(provider, slug, commit):
    obj = provider.request("GET", f"/repos/{slug}/git/commits/{commit}")
    tree = provider.request("GET", f"/repos/{slug}/git/trees/{obj['tree']['sha']}?recursive=1")
    if tree.get("truncated"):
        raise HarnessError("Public tree response is incomplete")
    files = {}
    aliases = set()
    for row in tree["tree"]:
        safe_relative(row["path"])
        if row["type"] == "tree":
            continue
        if row["type"] != "blob" or row["mode"] not in ("100644", "100755"):
            raise HarnessError("Public base has unsupported link/submodule entries")
        if row["path"].casefold() in aliases:
            raise HarnessError("Public base contains Windows path collisions")
        aliases.add(row["path"].casefold())
        files[row["path"]] = {"sha": row["sha"], "mode": row["mode"]}
    return obj["tree"]["sha"], files


def branch_head(provider, slug, branch):
    return provider.request("GET", f"/repos/{slug}/git/ref/heads/{enc(branch)}")["object"]["sha"]


def blob_sha(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def prepare(config_path, build_receipt, notes_path, destination, provider=None, *, policy=None):
    provider = provider or GitHub()
    config = read_json(config_path)
    required = {"schema_version", "repository", "repository_id", "base_branch", "channel", "mode", "version", "tag", "title", "make_latest", "exports", "required_checks"}
    if not required.issubset(config) or set(config) - required - {"production_repository_id", "remove_public_files", "operation", "source_policy"}:
        raise HarnessError("Publication configuration has missing or unknown keys")
    check_source_policy(config, policy)
    if config["schema_version"] != 1 or config["mode"] not in ("source-and-artifacts", "artifacts-only") or config["channel"] not in ("stable", "preview"):
        raise HarnessError("Unsupported publication schema, mode or channel")
    operation = config.get("operation", "release")
    if operation not in ("source", "release") or (operation == "source" and config["mode"] != "source-and-artifacts"):
        raise HarnessError("Source-only operation requires the selected-source mode")
    if operation == "source" and (config["tag"] is not None or config["make_latest"] is not False):
        raise HarnessError("Source-only publication requires tag null and make_latest false")
    if operation == "release" and (not isinstance(config["tag"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", config["tag"]) or ".." in config["tag"] or config["tag"].endswith(".lock")):
        raise HarnessError("Choose a simple immutable release tag")
    if type(config["make_latest"]) is not bool or (config["channel"] == "preview" and config["make_latest"]):
        raise HarnessError("Preview cannot become latest")
    if not isinstance(config["exports"], dict) or not isinstance(config["required_checks"], list):
        raise HarnessError("Explicit export mapping and check contexts are required")
    if config["mode"] == "artifacts-only" and config["exports"]:
        raise HarnessError("Artifacts-only mode cannot export producer source")
    if config["mode"] == "source-and-artifacts" and not config["exports"]:
        raise HarnessError("Source mode requires an exact source file allowlist")
    build = verify_evidence(build_receipt)
    if operation == "release" and not build["artifacts"]:
        raise HarnessError("Release publication requires actual verified artifacts")
    if build["version"] != config["version"]:
        raise HarnessError("Build and publication versions differ")
    dest = Path(destination).resolve()
    source_root = Path(build["source_root"]).resolve()
    if dest.is_relative_to(source_root) or source_root.is_relative_to(dest):
        raise HarnessError("Publication candidate must live outside producer checkout")
    repo = target_check(provider, config)
    slug = config["repository"]
    base = branch_head(provider, slug, config["base_branch"])
    tree_id, base_files = remote_tree(provider, slug, base)
    if operation == "release" and provider.request("GET", f"/repos/{slug}/git/ref/tags/{enc(config['tag'])}", allow_404=True):
        raise HarnessError("Tag already exists; never replace or move it")
    if operation == "release" and any(r["tag_name"] == config["tag"] for r in provider.pages(f"/repos/{slug}/releases")):
        raise HarnessError("Release already exists; inspect its original retained candidate")
    notes = Path(notes_path).read_bytes()
    notes.decode("utf-8")
    public_scan("notes.md", notes)
    public_scan("title.txt", config["title"].encode("utf-8"))
    assets, public_files, retained = {}, {}, {}
    evidence_root = Path(build_receipt).resolve().parent
    for name, info in (build["artifacts"] if operation == "release" else {}).items():
        basename = Path(name).name
        data = contained(evidence_root / "output", name).read_bytes()
        public_scan(basename, data)
        retained[f"assets/{basename}"] = data
        assets[basename] = {**info, "file": f"assets/{basename}"}
    for source, public in config["exports"].items():
        if source not in build["source"]["files"]:
            raise HarnessError("Export is not an exact committed producer input")
        data = contained(evidence_root / "source", source).read_bytes()
        scan_source_file(source, data, config, policy)
        scan_source_file(public, data, config, policy)
        if public == PUBLIC_MANIFEST or public.casefold() in {p.casefold() for p in public_files}:
            raise HarnessError("Colliding public export path")
        retained[f"public/{public}"] = data
        mode = build["source"].get("modes", {}).get(source, "100644")
        if mode not in ("100644", "100755"):
            raise HarnessError("Unsupported committed export mode")
        public_files[public] = {"sha": blob_sha(data), "mode": mode, "sha256": digest(data), "file": f"public/{public}"}
    manifest = {"schema_version": 1, "version": config["version"], "channel": config["channel"],
                "mode": config["mode"], "files": sorted(public_files),
                "assets": {name: {k: row[k] for k in ("sha256", "size")} for name, row in assets.items()}}
    data = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    public_files[PUBLIC_MANIFEST] = {"sha": blob_sha(data), "mode": "100644", "sha256": digest(data), "file": "public/" + PUBLIC_MANIFEST}
    retained["public/" + PUBLIC_MANIFEST] = data
    remove = config.get("remove_public_files", [])
    if not isinstance(remove, list) or len(remove) != len(set(remove)):
        raise HarnessError("Public removals must be exact unique paths")
    for name in remove:
        safe_relative(name)
        if name not in base_files or name in public_files:
            raise HarnessError("Removal must identify an existing public file absent from exports")
    projection = {name: row for name, row in base_files.items() if name not in remove}
    projection.update({name: {k: row[k] for k in ("sha", "mode")} for name, row in public_files.items()})
    if len({n.casefold() for n in projection}) != len(projection):
        raise HarnessError("Export collides with existing public base path")
    scan_projection(provider, slug, projection, config, {name: retained[row["file"]] for name, row in public_files.items()}, policy)
    spec = {"schema_version": 1, "config": config, "base_commit": base, "base_tree": tree_id,
            "base_files": base_files, "projection": projection, "public_files": public_files,
            "assets": assets, "notes_sha256": digest(notes), "build_receipt_sha256": file_hash(build_receipt),
            "private_producer": build["source"], "created_at": datetime.now(timezone.utc).isoformat(),
            "account_id": provider.authenticated_user()["id"], "repository_id": repo["id"]}
    candidate_id = digest(spec)
    dest.mkdir(parents=True, exist_ok=False)
    for name, content in retained.items():
        atomic_write(contained(dest, name), content)
    atomic_write(dest / "notes.md", notes)
    write_json(dest / "candidate.json", spec)
    write_json(dest / "state.json", {"candidate_id": candidate_id, "phase": "prepared", "events": []})
    return {"candidate": str(dest), "sha256": candidate_id, "repository": slug, "repository_id": repo["id"],
            "public_files": sorted(projection), "assets": assets, "base": base,
            "review_required": "Review all public bytes, removals, existing base, notes, target and operations. No approval is inferred."}


def load_candidate(destination, expected):
    dest = Path(destination).resolve()
    spec, state = read_json(dest / "candidate.json"), read_json(dest / "state.json")
    if digest(spec) != expected or state["candidate_id"] != expected:
        raise HarnessError("Candidate changed; present a new candidate for approval")
    if file_hash(dest / "notes.md") != spec["notes_sha256"]:
        raise HarnessError("Release notes changed")
    for row in list(spec["public_files"].values()) + list(spec["assets"].values()):
        path = contained(dest, row["file"])
        if file_hash(path) != row["sha256"] or ("size" in row and path.stat().st_size != row["size"]):
            raise HarnessError("Approved public bytes changed")
    return dest, spec, state


class Publisher:
    def __init__(self, destination, expected, provider=None, *, policy=None):
        self.dest, self.spec, self.state = load_candidate(destination, expected)
        self.provider = provider or GitHub()
        self.config = self.spec["config"]
        check_source_policy(self.config, policy)
        self.policy = policy
        self.slug = self.config["repository"]
        self.prefix = f"/repos/{self.slug}"
        self.branch = "oasis-candidate/" + expected[:24]

    def save(self, **changes):
        self.state.update(changes)
        write_json(self.dest / "state.json", self.state)

    def mutation(self, operation, method, path, payload):
        self.state["events"].append({"operation": operation, "request_sha256": digest(payload), "status": "intent"})
        self.save(phase=operation)
        try:
            result = self.provider.request(method, path, payload)
        except Exception:
            self.state["events"][-1]["status"] = "uncertain_or_rejected"
            self.save()
            raise
        self.state["events"][-1]["status"] = "response_received"
        self.save()
        return result

    def check_target(self):
        target_check(self.provider, self.config)
        if self.provider.authenticated_user()["id"] != self.spec["account_id"]:
            raise HarnessError("Authenticated account changed")

    def check_commit(self, commit, parent):
        obj = self.provider.request("GET", self.prefix + f"/git/commits/{commit}")
        _, actual = remote_tree(self.provider, self.slug, commit)
        if actual != self.spec["projection"] or [p["sha"] for p in obj["parents"]] != [parent]:
            raise HarnessError("Public commit does not contain exactly the approved tree and parent")

    def merged_commit(self, pr):
        """Resolve this exact merged PR without guessing from the current base tip."""
        saved = self.state.get("merge_commit")
        legacy = pr.get("merge_commit_sha")
        if self.state.get("pr_number") not in (None, pr["number"]):
            raise HarnessError("Retained merge belongs to a different pull request")
        if saved is not None and legacy is not None and saved != legacy:
            raise HarnessError("Retained and remote merge identities disagree; preserve and reconcile")
        commit = saved if saved is not None else legacy
        if commit is None:
            owner, name = repository_slug(self.slug).split("/")
            # A GraphQL query transported with POST is read-only. Do not send it
            # through mutation(), infer a merge from branch_head(), or retry an
            # uncertain merge merely because REST omitted the legacy field.
            response = self.provider.request("POST", "/graphql", {
                "query": "query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){databaseId pullRequest(number:$number){number merged mergeCommit{oid}}}}",
                "variables": {"owner": owner, "name": name, "number": pr["number"]},
            })
            try:
                if not isinstance(response, dict) or response.get("errors"):
                    raise ValueError("Incomplete GraphQL response")
                repository = response["data"]["repository"]
                actual_pr = repository["pullRequest"]
                if (repository["databaseId"] != self.spec["repository_id"]
                        or actual_pr["number"] != pr["number"] or actual_pr["merged"] is not True):
                    raise ValueError("Different repository or merged pull request")
                commit = actual_pr["mergeCommit"]["oid"]
            except (KeyError, TypeError, ValueError):
                raise HarnessError("Cannot establish this exact PR's merge identity; preserve and reconcile") from None
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise HarnessError("Merged PR has no supported exact SHA-1 commit identity")
        self.check_commit(commit, self.spec["base_commit"])
        return commit

    def merge(self):
        prs = list(self.provider.pages(self.prefix + f"/pulls?state=all&head={enc(self.slug.split('/')[0] + ':' + self.branch)}"))
        if len(prs) > 1:
            raise HarnessError("Ambiguous candidate pull requests")
        pr = self.provider.request("GET", self.prefix + f"/pulls/{prs[0]['number']}") if prs else None
        if pr and pr.get("merged"):
            self.check_pr(pr)
            commit = self.merged_commit(pr)
            self.save(pr_url=pr["html_url"], pr_number=pr["number"], merge_commit=commit)
            return commit
        if branch_head(self.provider, self.slug, self.config["base_branch"]) != self.spec["base_commit"]:
            raise HarnessError("Public base moved; prepare a new candidate and approval")
        ref_path = self.prefix + f"/git/ref/heads/{enc(self.branch)}"
        ref = self.provider.request("GET", ref_path, allow_404=True)
        if ref:
            head = ref["object"]["sha"]
            self.check_commit(head, self.spec["base_commit"])
        else:
            entries = []
            known_blobs = {row["sha"] for row in self.spec.get("base_files", {}).values()}
            for name, row in self.spec["public_files"].items():
                if row["sha"] not in known_blobs:
                    blob = self.mutation("blob", "POST", self.prefix + "/git/blobs", {"content": base64.b64encode(contained(self.dest, row["file"]).read_bytes()).decode(), "encoding": "base64"})
                    if blob["sha"] != row["sha"]:
                        raise HarnessError("GitHub blob hash differs from approved bytes")
                entries.append({"path": name, "mode": row["mode"], "type": "blob", "sha": row["sha"]})
            entries.extend({"path": name, "mode": "100644", "type": "blob", "sha": None} for name in self.config.get("remove_public_files", []))
            tree = self.mutation("tree", "POST", self.prefix + "/git/trees", {"base_tree": self.spec["base_tree"], "tree": entries})
            identity = {"name": "Oasis publication", "email": "publication@users.noreply.github.com", "date": self.spec["created_at"]}
            commit = self.mutation("commit", "POST", self.prefix + "/git/commits", {"message": self.config["title"], "tree": tree["sha"], "parents": [self.spec["base_commit"]], "author": identity, "committer": identity})
            head = commit["sha"]
            self.check_commit(head, self.spec["base_commit"])
            self.mutation("branch", "POST", self.prefix + "/git/refs", {"ref": "refs/heads/" + self.branch, "sha": head})
        self.save(candidate_commit=head)
        if not pr:
            if any(e["operation"] == "pull_request" and e["status"] in ("intent", "uncertain_or_rejected") for e in self.state["events"]):
                raise HarnessError("PR creation was uncertain and lookup found none; obtain operator reconciliation before retry")
            body = (self.dest / "notes.md").read_text(encoding="utf-8").rstrip() + f"\n\nExact publication candidate {self.state['candidate_id']}.\n"
            pr = self.mutation("pull_request", "POST", self.prefix + "/pulls", {"title": self.config["title"], "body": body, "head": self.branch, "base": self.config["base_branch"]})
        self.save(pr_url=pr["html_url"], pr_number=pr["number"])
        pr = self.provider.request("GET", self.prefix + f"/pulls/{pr['number']}")
        self.check_pr(pr)
        statuses = list(self.provider.pages(self.prefix + f"/commits/{head}/statuses"))
        latest = {}
        for row in statuses:
            latest.setdefault(row["context"], row["state"])
        for context in self.config["required_checks"]:
            if latest.get(context) != "success":
                raise HarnessError(f"Required commit status is not successful: {context}; resume after it completes")
        if branch_head(self.provider, self.slug, self.config["base_branch"]) != self.spec["base_commit"]:
            raise HarnessError("Public base changed before merge")
        merged = self.mutation("merge", "PUT", self.prefix + f"/pulls/{pr['number']}/merge", {"sha": head, "merge_method": "squash", "commit_title": self.config["title"], "commit_message": ""})
        if not merged.get("merged"):
            raise HarnessError("Exact squash merge did not complete; keep the candidate for inspection")
        self.check_commit(merged["sha"], self.spec["base_commit"])
        self.save(merge_commit=merged["sha"])
        return merged["sha"]

    def check_pr(self, pr):
        if (pr["head"]["repo"]["id"] != self.spec["repository_id"] or pr["base"]["repo"]["id"] != self.spec["repository_id"] or
            pr["head"]["ref"] != self.branch or pr["base"]["ref"] != self.config["base_branch"] or
            not pr.get("merged") and pr["base"]["sha"] != self.spec["base_commit"]):
            raise HarnessError("PR target, base or source changed")
        # After merge, verify the immutable merge parent in merge(), rather
        # than treating mutable base-branch metadata as historical evidence.
        self.check_commit(pr["head"]["sha"], self.spec["base_commit"])
        if self.state.get("candidate_commit") and pr["head"]["sha"] != self.state["candidate_commit"]:
            raise HarnessError("PR head changed")

    def check_release(self, release, commit):
        if release["tag_name"] != self.config["tag"] or release["name"] != self.config["title"] or release.get("body", "") != (self.dest / "notes.md").read_text(encoding="utf-8") or release["prerelease"] != (self.config["channel"] == "preview"):
            raise HarnessError("Release metadata differs from approved candidate")
        ref = self.provider.request("GET", self.prefix + f"/git/ref/tags/{enc(self.config['tag'])}", allow_404=True)
        if ref and (ref["object"]["type"] != "commit" or ref["object"]["sha"] != commit):
            raise HarnessError("Release tag is not the exact approved lightweight commit reference")
        if not ref and not release["draft"]:
            raise HarnessError("Published release has no verified tag")
        if release.get("target_commitish") != commit:
            raise HarnessError("Draft/release target changed")

    def assets(self, release, *, complete=False, anonymous=False):
        rows = list(self.provider.pages(self.prefix + f"/releases/{release['id']}/assets"))
        names = [row["name"] for row in rows]
        if len(names) != len(set(names)) or set(names) - self.spec["assets"].keys():
            raise HarnessError("Draft has unexpected or duplicate assets; do not delete or overwrite automatically")
        if complete and set(names) != self.spec["assets"].keys():
            raise HarnessError("Release asset set is incomplete")
        for row in rows:
            expected = self.spec["assets"][row["name"]]
            if row["state"] != "uploaded" or row["size"] != expected["size"]:
                raise HarnessError("Partial or mismatched upload retained for inspection")
            native_digest = getattr(self.provider, "asset_digest", None)
            actual_digest = native_digest(self.slug, row, anonymous=anonymous) if callable(native_digest) else digest(self.provider.download_asset(self.slug, row, anonymous=anonymous))
            if actual_digest != expected["sha256"]:
                raise HarnessError("Downloaded release bytes differ from candidate")
        return set(names)

    def verify_source(self, commit):
        for name, row in self.spec["projection"].items():
            bounded = getattr(self.provider, "download_source_bounded", None)
            local = self.spec["public_files"].get(name)
            size = contained(self.dest, local["file"]).stat().st_size if local else None
            data = bounded(self.slug, commit, name, max_bytes=size if size is not None else 64 * 1024 * 1024,
                           expected_size=size) if callable(bounded) else self.provider.download_source(self.slug, commit, name)
            if size is not None and len(data) != size:
                raise HarnessError("Anonymous public source size differs from approved bytes")
            if blob_sha(data) != row["sha"]:
                raise HarnessError("Anonymous public source differs from approved bytes")
            scan_source_file(name, data, self.config, self.policy)

    def execute(self, authority):
        require_authority(authority)
        with operation_lock(self.dest / "publish.lock"):
            if digest(self.spec) != self.state["candidate_id"]:
                raise HarnessError("In-memory candidate drift; reload the exact reviewed candidate")
            self.dest, self.spec, self.state = load_candidate(self.dest, self.state["candidate_id"])
            self.config = self.spec["config"]
            check_source_policy(self.config, self.policy)
            self.check_target()
            if self.config.get("operation", "release") == "source" and (self.config.get("tag") is not None or self.config.get("make_latest") is not False):
                raise HarnessError("Source-only publication requires tag null and make_latest false")
            public_scan("title.txt", self.config["title"].encode("utf-8"))
            public_scan("notes.md", (self.dest / "notes.md").read_bytes())
            for name, row in self.spec["assets"].items():
                public_scan(name, contained(self.dest, row["file"]).read_bytes())
            scan_projection(self.provider, self.slug, self.spec["projection"], self.config,
                            {name: contained(self.dest, row["file"]).read_bytes() for name, row in self.spec["public_files"].items()}, self.policy)
            self.save(authority_reference=authority, authority_independently_verified=False)
            commit = self.merge()
            if self.config.get("operation", "release") == "source":
                self.verify_source(commit)
                self.save(phase="source_verified", public_commit=commit, release_created=False, anonymous_download_verified=True)
                return self.state
            releases = [row for row in self.provider.pages(self.prefix + "/releases") if row["tag_name"] == self.config["tag"]]
            if len(releases) > 1:
                raise HarnessError("Ambiguous release identity")
            if releases:
                release = self.provider.request("GET", self.prefix + f"/releases/{releases[0]['id']}")
            else:
                if any(e["operation"] == "draft" and e["status"] in ("intent", "uncertain_or_rejected") for e in self.state["events"]):
                    raise HarnessError("Draft creation was uncertain; do not create another until reconciled")
                release = self.mutation("draft", "POST", self.prefix + "/releases", {"tag_name": self.config["tag"], "target_commitish": commit, "name": self.config["title"], "body": (self.dest / "notes.md").read_text(encoding="utf-8"), "draft": True, "prerelease": self.config["channel"] == "preview", "make_latest": "false"})
            self.save(release_id=release["id"])
            self.check_release(release, commit)
            if release["draft"]:
                present = self.assets(release)
                for name, row in self.spec["assets"].items():
                    if name in present:
                        continue
                    operation = "upload:" + name
                    if any(e["operation"] == operation and e["status"] in ("intent", "uncertain_or_rejected") for e in self.state["events"]):
                        raise HarnessError("Upload outcome is unresolved and no matching asset is visible; retain and inspect before retry")
                    self.state["events"].append({"operation": operation, "status": "intent"})
                    self.save()
                    try:
                        self.provider.upload_asset(self.slug, release["id"], name, contained(self.dest, row["file"]), "application/octet-stream")
                    except Exception:
                        self.state["events"][-1]["status"] = "uncertain_or_rejected"
                        self.save()
                        raise
                    self.state["events"][-1]["status"] = "response_received"
                    self.save()
                self.assets(release, complete=True)
                self.check_target()
                current = self.provider.request("GET", self.prefix + f"/releases/{release['id']}")
                self.check_release(current, commit)
                if not current["draft"]:
                    raise HarnessError("Release was published concurrently; inspect before resuming")
                self.mutation("publish", "PATCH", self.prefix + f"/releases/{release['id']}", {"draft": False, "make_latest": str(self.config["make_latest"]).lower()})
            release = self.provider.request("GET", self.prefix + f"/releases/{release['id']}")
            self.check_release(release, commit)
            if release["draft"] or release.get("immutable") is not True:
                raise HarnessError("Publication is not confirmed immutable")
            self.assets(release, complete=True, anonymous=True)
            latest = self.provider.request("GET", self.prefix + "/releases/latest", allow_404=True)
            if self.config["make_latest"] and (latest or {}).get("id") != release["id"]:
                raise HarnessError("Latest release metadata was not applied")
            if not self.config["make_latest"] and (latest or {}).get("id") == release["id"]:
                raise HarnessError("Release unexpectedly became latest")
            self.save(phase="verified", release_url=release["html_url"], anonymous_download_verified=True)
            return self.state


def provision(plan_path, authority=None, apply=False, provider=None):
    """Setup has its own concrete plan and approval, distinct from a release."""
    provider = provider or GitHub()
    plan = read_json(plan_path)
    required = {"schema_version", "repository", "account_id", "create", "repository_id", "base_branch", "bootstrap_readme", "protection"}
    if set(plan) != required or plan["schema_version"] != 1 or type(plan["create"]) is not bool:
        raise HarnessError("Invalid exact repository setup plan")
    slug = repository_slug(plan["repository"])
    public_scan("README.md", plan["bootstrap_readme"].encode("utf-8"))
    user = provider.authenticated_user()
    if user["id"] != plan["account_id"]:
        raise HarnessError("Repository setup account mismatch")
    prefix = "/repos/" + slug
    repo = provider.request("GET", prefix, allow_404=True)
    receipt_path = Path(plan_path).with_suffix(".state.json")
    prior = read_json(receipt_path) if receipt_path.exists() else None
    if repo and plan["repository_id"] is None and not (
        prior and prior.get("plan_sha256") == digest(plan) and prior.get("repository_id") == repo["id"]):
        raise HarnessError("An existing repository needs its verified exact ID; unknown creation must be reviewed in a new explicit connection plan")
    if not repo and plan["repository_id"] is not None:
        raise HarnessError("The expected repository is absent; do not recreate its name under a different identity")
    if repo and (plan["repository_id"] is not None and repo["id"] != plan["repository_id"]):
        raise HarnessError("Repository setup identity mismatch")
    if repo and (repo.get("private") or repo.get("fork") or repo.get("archived")):
        raise HarnessError("Setup will not convert a private/fork/archived repository")
    if not apply:
        return {"plan_sha256": digest(plan), "repository": repo, "operations": ["create if absent", "approved minimal bootstrap if empty", "branch protection", "immutable releases"], "approval_required": True}
    require_authority(authority)
    with operation_lock(Path(plan_path).with_suffix(".lock")):
        state = read_json(receipt_path) if receipt_path.exists() else {"plan_sha256": digest(plan), "phase": "prepared", "events": []}
        if state["plan_sha256"] != digest(plan):
            raise HarnessError("Setup plan changed; retain evidence and present a new plan")
        def mutate(operation, method, endpoint, payload=None):
            state["phase"] = operation
            state["events"].append({"operation": operation, "status": "intent"})
            write_json(receipt_path, state)
            result = provider.request(method, endpoint, payload)
            state["events"][-1]["status"] = "response_received"
            write_json(receipt_path, state)
            return result
        if state.get("repository_id") and repo and state["repository_id"] != repo["id"]:
            raise HarnessError("Previously bound repository was replaced")
        if not repo:
            if not plan["create"] or any(e["operation"] == "create" for e in state["events"]):
                raise HarnessError("Repository absent or previous creation unresolved; inspect before retry")
            owner, name = slug.split("/")
            endpoint = "/user/repos" if owner.casefold() == user["login"].casefold() else f"/orgs/{owner}/repos"
            repo = mutate("create", "POST", endpoint, {"name": name, "private": False, "auto_init": False})
        state["repository_id"] = repo["id"]
        write_json(receipt_path, state)
        branches = list(provider.pages(prefix + "/branches"))
        if not branches:
            if not plan["bootstrap_readme"]:
                raise HarnessError("Empty public repository requires an approved minimal initial README")
            mutate("bootstrap", "PUT", prefix + "/contents/README.md", {"message": "Initialize public distribution", "content": base64.b64encode(plan["bootstrap_readme"].encode()).decode(), "branch": plan["base_branch"]})
        repo = provider.read_repository(slug)
        if repo["default_branch"] != plan["base_branch"]:
            raise HarnessError("Actual default branch differs; include a separately reviewed branch change")
        mutate("protection", "PUT", prefix + f"/branches/{enc(plan['base_branch'])}/protection", plan["protection"])
        mutate("immutable", "PUT", prefix + "/immutable-releases")
        protection = provider.request("GET", prefix + f"/branches/{enc(plan['base_branch'])}/protection")
        for key, expected in plan["protection"].items():
            actual = protection.get(key)
            if isinstance(expected, bool) and isinstance(actual, dict):
                actual = actual.get("enabled")
            if isinstance(expected, dict) and isinstance(actual, dict):
                actual = {k: actual.get(k) for k in expected}
            if actual != expected:
                raise HarnessError(f"Protection setting was not verified: {key}")
        if not provider.request("GET", prefix + "/immutable-releases")["enabled"]:
            raise HarnessError("Immutable release setting was not verified")
        state.update(phase="verified", base_commit=branch_head(provider, slug, plan["base_branch"]), authority_reference=authority, authority_independently_verified=False)
        write_json(receipt_path, state)
        return state


def register(subparsers):
    p = subparsers.add_parser("publish", help="Prepare, inspect and execute an exact public candidate")
    sub = p.add_subparsers(dest="publish_command", required=True)
    s = sub.add_parser("prepare")
    for name in ("config", "build-receipt", "notes", "destination"):
        s.add_argument("--" + name, required=True)
    s.set_defaults(func=lambda a: prepare(a.config, a.build_receipt, a.notes, a.destination))
    s = sub.add_parser("inspect")
    s.add_argument("candidate")
    s.add_argument("--sha256", required=True)
    s.set_defaults(func=lambda a: {"candidate": load_candidate(a.candidate, a.sha256)[1], "state": load_candidate(a.candidate, a.sha256)[2], "authority_verified": False})
    s = sub.add_parser("execute")
    s.add_argument("candidate")
    s.add_argument("--sha256", required=True)
    s.add_argument("--authority", required=True)
    s.set_defaults(func=lambda a: Publisher(a.candidate, a.sha256).execute(a.authority))
    s = sub.add_parser("setup")
    s.add_argument("plan")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--authority")
    s.set_defaults(func=lambda a: provision(a.plan, a.authority, a.apply))
