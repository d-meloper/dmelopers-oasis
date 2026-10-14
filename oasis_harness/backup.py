"""Optional private Git recovery through an identity-bound external bare relay.

The source never receives a remote. Working files/index/ignored data are not
backup content. Publication and automatic activation are separate operations.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

from .common import (HarnessError, atomic_write, canonical, clean_environment, contained, digest, file_hash, git, git_objects, is_reparse,
                     operation_lock, read_json, run, write_json, write_new_json)
from .github import GitHub, repository_slug
from . import gitops

CATALOG = "refs/heads/oasis/catalog"
SOURCE_POLICIES = ("managed", "isolated-unmanaged")
_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_CODEX_TREE_REF = re.compile(
    r"refs/codex/turn-diffs/(?:captures/[0-9]+/" + _UUID + r"/base|"
    r"checkpoints/[0-9a-f]{32}/[0-9a-f]{32}/[0-9]+/" + _UUID + r")")


def _plumbing_environment():
    return clean_environment({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                              "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_COUNT": "1",
                              "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": os.devnull})


def _git_owned(root, *args, check=True, input_text=None):
    return run(["git", "-C", str(root), *args], env=_plumbing_environment(),
               check=check, input_text=input_text).stdout.strip()


def _provider(provider):
    return provider if provider is not None else GitHub()


def _source_policy(config):
    # Missing means the original managed contract, never an inferred exception.
    value = config.get("source_policy", "managed")
    if value not in SOURCE_POLICIES:
        raise HarnessError("Unsupported private backup source policy")
    return value


def _codex_tree_ref(name):
    return isinstance(name, str) and _CODEX_TREE_REF.fullmatch(name) is not None


def _assert_auxiliary_tree(root, oid):
    if _git_owned(root, "cat-file", "-t", oid) != "tree":
        raise HarnessError("Supported Codex capture/checkpoint refs must identify regular trees")
    entries = _git_owned(root, "ls-tree", "-rz", "--full-tree", oid).split("\0")
    for entry in filter(None, entries):
        metadata, _ = entry.split("\t", 1)
        mode, kind, _ = metadata.split()
        if kind != "blob" or mode not in ("100644", "100755"):
            raise HarnessError("Codex capture/checkpoint trees cannot contain links/submodules")


def _source_hooks(root):
    """Bind actual hook configuration/bytes without executing or replacing them."""
    def values(*scope):
        result = run(["git", "-C", str(root), "config", *scope, "--get-all", "core.hooksPath"], check=False)
        if result.returncode not in (0, 1):
            raise HarnessError("Cannot inspect the actual source hook configuration")
        return result.stdout.splitlines() if result.returncode == 0 else []

    local, effective = values("--local"), values()
    configured = run(["git", "-C", str(root), "config", "--path", "--get", "core.hooksPath"], check=False)
    if configured.returncode not in (0, 1):
        raise HarnessError("Cannot resolve the actual source hook directory")
    setting = configured.stdout.rstrip("\r\n") if configured.returncode == 0 else None
    if setting == "":
        raise HarnessError("Empty source hook path is ambiguous; review it before backup binding")
    disabled = setting is not None and setting.casefold() == os.devnull.casefold()
    directory = None if disabled else Path(setting) if setting is not None else gitops.common_dir(root) / "hooks"
    files = {}
    exists = False
    if directory is not None:
        if not directory.is_absolute():
            directory = root / directory
        directory = directory.absolute()
        for candidate in (directory, *directory.parents):
            if candidate.is_symlink() or is_reparse(candidate):
                raise HarnessError("Source hooks must not traverse linked/reparse paths")
        directory = directory.resolve()
        exists = directory.exists()
        if exists and not directory.is_dir():
            raise HarnessError("Source hook directory is not a regular directory")
        if exists:
            for candidate in sorted(directory.rglob("*")):
                relative = candidate.relative_to(directory).as_posix()
                checked = contained(directory, relative)
                if checked.is_file():
                    files[relative] = file_hash(checked)
    return {"local_values": local, "effective_values": effective,
            "directory": str(directory) if directory is not None else None,
            "disabled": disabled, "exists": exists, "files": files}


def _assert_unmanaged_source(root):
    gitops.assert_isolated(root)
    if gitops.desired_profile(root) != "unmanaged":
        raise HarnessError("isolated-unmanaged backup requires the actual unmanaged project policy")
    if gitops._binding(root) is not None:
        raise HarnessError("Existing managed binding needs explicit migration; this policy does not deactivate it")


def _relay_identity(config):
    value = {key: config[key] for key in ("repository", "repository_id", "account_id", "primary", "common_dir")}
    if _source_policy(config) == "isolated-unmanaged":
        value.update(source_policy="isolated-unmanaged", source_hooks_sha256=digest(config["source_hooks"]))
    return value


def _config(root):
    path = gitops.state_dir(root) / "backup.json"
    if not path.is_file():
        raise HarnessError("Private backup is not configured")
    value = read_json(path)
    if value.get("schema_version") != 1:
        raise HarnessError("Unsupported private backup binding")
    if _source_policy(value) == "isolated-unmanaged" and (
            not isinstance(value.get("source_hooks"), dict) or value.get("automatic_enabled") is not False):
        raise HarnessError("isolated-unmanaged backup needs its reviewed hook inventory and manual-only binding")
    return value


def _assert_source(root, config):
    root = gitops.root_path(root)
    gitops.assert_isolated(root)
    if str(root) != config.get("primary") or str(gitops.common_dir(root)) != config.get("common_dir"):
        raise HarnessError("Copied/moved source cannot inherit backup authority; explicitly reconfigure it")
    if _source_policy(config) == "isolated-unmanaged":
        _assert_unmanaged_source(root)
        if _source_hooks(root) != config.get("source_hooks"):
            raise HarnessError("Source hooks changed since backup binding; preserve them and review an explicit binding migration")
    return root


def _identity(config, provider):
    provider.assert_stored_oauth()
    account = provider.authenticated_user()
    remote = provider.read_repository(repository_slug(config["repository"]))
    if (int(account.get("id", 0)) != config["account_id"] or
        int(remote.get("id", 0)) != config["repository_id"] or
        remote.get("full_name", "").casefold() != config["repository"].casefold() or
        remote.get("private") is not True or remote.get("fork") or remote.get("archived")):
        raise HarnessError("Private backup destination/account identity or visibility changed")
    return remote


def _url(config, provider):
    # Only injected local fixtures expose this method. Public CLI always uses
    # the fixed GitHub transport, not a user-supplied arbitrary remote URL.
    if hasattr(provider, "fixture_git_url"):
        return str(provider.fixture_git_url(config["repository"]))
    return "https://github.com/" + repository_slug(config["repository"]) + ".git"


def _remote_refs(config, provider):
    # A bare drive root has no parent repository to discover. In particular,
    # never inherit the calling source checkout's url.* / include.* settings.
    neutral = Path(Path(config["primary"]).anchor)
    if (neutral / ".git").exists() or ((neutral / "HEAD").exists() and (neutral / "objects").exists()):
        raise HarnessError("Neutral transport directory unexpectedly contains Git state")
    environment = provider.git_environment()
    environment["GIT_CEILING_DIRECTORIES"] = str(neutral)
    result = run(["git", "ls-remote", "--refs", _url(config, provider)], cwd=neutral, env=environment)
    values = {}
    for line in result.stdout.splitlines():
        oid, name = line.split("\t", 1)
        auxiliary = (_source_policy(config) == "isolated-unmanaged"
                     and re.fullmatch(r"refs/tags/source-local-captures/[0-9a-f]{24}/(?:[0-9a-f]{40}|[0-9a-f]{64})", name)
                     and name.rsplit("/", 1)[1] == oid)
        if not (name == CATALOG or name.startswith(("refs/heads/source/", "refs/tags/source/", "refs/heads/retained/")) or auxiliary):
            raise HarnessError(f"Unexpected private backup namespace: {name}")
        values[name] = oid
    return values


def _external(root, value):
    path = Path(value).absolute()
    for item in (path, *path.parents):
        if item.is_symlink() or is_reparse(item):
            raise HarnessError("Backup paths must not traverse links/reparse points")
    path = path.resolve()
    if path.is_relative_to(root) or root.is_relative_to(path):
        raise HarnessError("Backup relay must be separate from source and its ancestors")
    return path


def _relay(config):
    relay = _external(Path(config["primary"]).resolve(), config["relay"])
    record = relay.parent / "oasis-relay.json"
    if not relay.is_dir() or not record.is_file():
        raise HarnessError("Bound relay is missing; explicitly configure a fresh relay from remote")
    expected = _relay_identity(config)
    if read_json(record) != expected or _git_owned(relay, "rev-parse", "--is-bare-repository") != "true":
        raise HarnessError("Relay identity differs from its source binding")
    if _git_owned(relay, "remote"):
        raise HarnessError("Relay contains unexpected named transport configuration")
    allowed = {"core.repositoryformatversion", "core.filemode", "core.bare", "core.logallrefupdates",
               "core.ignorecase", "core.precomposeunicode", "core.symlinks", "extensions.objectformat"}
    keys = _git_owned(relay, "config", "--local", "--no-includes", "--name-only", "--list").splitlines()
    if any(key.lower() not in allowed for key in keys):
        raise HarnessError("Relay local configuration contains unapproved transport/include/credential settings")
    return relay


def configure(root, repository, relay, repository_id, account_id, *, provider=None, source_policy="managed"):
    provider = _provider(provider)
    root = gitops.root_path(root)
    if source_policy not in SOURCE_POLICIES:
        raise HarnessError("Select an explicit supported backup source policy")
    source_hooks = None
    if source_policy == "managed":
        gitops.assert_binding(root)
    else:
        _assert_unmanaged_source(root)
        selected, _ = _selected(root, source_policy=source_policy)  # Full history and classified refs, not repository absence.
        if gitops.branch(root) != "main" or gitops.head(root) != selected["refs/heads/main"]:
            raise HarnessError("Configure isolated-unmanaged backup from its actual committed main checkout")
        source_hooks = _source_hooks(root)
    relay = _external(root, relay)
    config = {"schema_version": 1, "repository": repository_slug(repository),
              "repository_id": int(repository_id), "account_id": int(account_id),
              "primary": str(root), "common_dir": str(gitops.common_dir(root)),
              "relay": str(relay), "automatic_enabled": False}
    if source_policy == "isolated-unmanaged":
        config.update(source_policy=source_policy, source_hooks=source_hooks)
    _identity(config, provider)
    remote = _remote_refs(config, provider)
    with operation_lock(contained(root, ".oasis/local/operations.lock")):
        with operation_lock(relay.parent / "oasis-backup.lock"):
            record = relay.parent / "oasis-relay.json"
            _assert_source(root, config)
            expected = _relay_identity(config)
            if record.exists() and (not record.is_file() or read_json(record) != expected):
                raise HarnessError("Existing relay ownership record belongs to another binding")
            if relay.exists() and any(relay.iterdir()):
                if not record.is_file() or read_json(record) != expected:
                    raise HarnessError("Refusing to adopt an unowned existing relay")
            else:
                run(["git", "init", "--bare", "--template=", str(relay)], env=provider.git_environment())
                write_json(record, expected)
                for name, oid in remote.items():
                    run(["git", "-C", str(relay), "fetch", "--no-tags", _url(config, provider), f"{name}:{name}"], env=provider.git_environment())
            _relay(config)
            _assert_source(root, config)
            old_path = gitops.state_dir(root) / "backup.json"
            if old_path.exists():
                old = read_json(old_path)
                if (any(old.get(key) != config[key] for key in ("repository", "repository_id", "account_id", "relay", "primary", "common_dir"))
                        or _source_policy(old) != source_policy or old.get("source_hooks") != config.get("source_hooks")):
                    raise HarnessError("Existing binding changed; preserve it and review a separate destination migration")
                config["automatic_enabled"] = old.get("automatic_enabled", False)
                if "restore_proof" in old:
                    config["restore_proof"] = old["restore_proof"]
            write_json(old_path, config)
    return {"configured": True, "automatic_enabled": config["automatic_enabled"], "repository_id": config["repository_id"], "relay": str(relay)}


def _batch_objects(root, identities):
    """Read binary Git objects without text newline/Unicode transformations."""
    yield from git_objects(root, identities)


def _assert_self_contained_history(root):
    identities = sorted(set(git(root, "rev-list", "--objects", "--no-object-names", "--all", "--reflog").splitlines()))
    inventory = run(["git", "-C", str(root), "cat-file", "--batch-check"], input_text="\n".join(identities) + "\n").stdout
    inspect = []
    sizes = {}
    for line in inventory.splitlines():
        fields = line.split()
        if len(fields) != 3 or not fields[2].isdigit():
            raise HarnessError("Retained history contains unavailable objects")
        oid, kind, size = fields[0], fields[1], int(fields[2])
        sizes[oid] = size
        if kind == "tree" or kind == "blob" and size <= 4096:
            inspect.append(oid)
    width = 32 if git(root, "rev-parse", "--show-object-format") == "sha256" else 20
    attributes = set()
    for oid, kind, data in _batch_objects(root, inspect):
        if kind == "blob" and data.startswith(b"version https://git-lfs.github.com/spec/v1"):
            raise HarnessError("Retained Git LFS pointer requires an object-storage adapter; incomplete backup refused")
        if kind != "tree":
            continue
        cursor = 0
        while cursor < len(data):
            separator = data.index(b" ", cursor); end = data.index(b"\0", separator)
            mode, name = data[cursor:separator], data[separator + 1:end]
            identity = data[end + 1:end + 1 + width].hex()
            cursor = end + 1 + width
            if mode == b"160000" or name in (b".gitmodules", b".lfsconfig"):
                raise HarnessError("Retained submodule/LFS contract needs independent storage; incomplete backup refused")
            if name == b".gitattributes":
                attributes.add(identity)
    if any(sizes.get(oid, 0) > 1024 * 1024 for oid in attributes):
        raise HarnessError("Oversized retained attributes cannot be verified for external storage")
    for _, kind, data in _batch_objects(root, sorted(attributes)):
        if kind != "blob" or re.search(rb"(?:^|\s)filter=lfs(?:\s|$)", data):
            raise HarnessError("Retained Git LFS attributes require an object-storage adapter")


def _selected(root, *, source_policy="managed"):
    selected = {}
    auxiliary = set()
    for name, oid in gitops.refs(root).items():
        if name.startswith(("refs/heads/", "refs/tags/", "refs/notes/", "refs/oasis/recovery/")) or name == "refs/stash":
            selected[name] = oid
        elif source_policy == "isolated-unmanaged" and _codex_tree_ref(name):
            if oid not in auxiliary:
                _assert_auxiliary_tree(root, oid)
                auxiliary.add(oid)
            selected[name] = oid
        else:
            raise HarnessError(f"Unclassified source ref needs an explicit retention contract: {name}")
    if "refs/heads/main" not in selected:
        raise HarnessError("Private backup requires a committed main baseline")
    _assert_self_contained_history(root)
    reflog = sorted(set(git(root, "reflog", "show", "--all", "--format=%H").splitlines()))
    return selected, reflog


def _map(name, oid):
    if name.startswith("refs/heads/"):
        return "refs/heads/source/" + name[len("refs/heads/"):]
    if name.startswith("refs/tags/"):
        return "refs/tags/source/" + name[len("refs/tags/"):]
    if _codex_tree_ref(name):
        # Git branch refs require commits. Immutable tags can retain private trees.
        return "refs/tags/source-local-captures/" + digest(name)[:24] + "/" + oid
    return "refs/heads/retained/" + digest(name)[:24] + "/" + oid


def _snapshot(root, config, triggering_commit=None):
    selected, reflog = _selected(root, source_policy=_source_policy(config))
    if triggering_commit:
        if git(root, "cat-file", "-t", triggering_commit, check=False) != "commit":
            raise HarnessError("Triggering commit does not exist")
        if triggering_commit not in reflog and not any(
                run(["git", "-C", str(root), "merge-base", "--is-ancestor", triggering_commit, oid], check=False).returncode == 0
                for name, oid in selected.items() if name.startswith("refs/heads/")):
            raise HarnessError("Snapshot does not cover the actual triggering commit")
    value = {"schema_version": 1, "repository_id": config["repository_id"],
             "main": selected["refs/heads/main"], "main_tree": git(root, "rev-parse", selected["refs/heads/main"] + "^{tree}"),
             "refs": selected, "reflog_commits": reflog, "triggering_commit": triggering_commit}
    if _source_policy(config) == "isolated-unmanaged":
        value["source_policy"] = "isolated-unmanaged"
    value["snapshot_sha256"] = digest(value)
    return value


def _read_catalog(repo, oid):
    if not oid:
        raise HarnessError("Backup has no catalog")
    try:
        value = json.loads(_git_owned(repo, "show", oid + ":snapshot.json"))
    except ValueError as exc:
        raise HarnessError("Invalid backup catalog JSON") from exc
    if value.get("schema_version") != 1 or value.get("snapshot_sha256") != digest({k: v for k, v in value.items() if k != "snapshot_sha256"}):
        raise HarnessError("Backup catalog schema/hash mismatch")
    expected_keys = {"schema_version", "repository_id", "main", "main_tree", "refs", "reflog_commits", "triggering_commit", "snapshot_sha256"}
    policy = _source_policy(value)
    if policy == "isolated-unmanaged":
        expected_keys.add("source_policy")
    valid_oid = lambda item: isinstance(item, str) and bool(re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", item))
    if (set(value) != expected_keys or not isinstance(value["repository_id"], int) or value["repository_id"] <= 0
            or not isinstance(value["refs"], dict) or value["refs"].get("refs/heads/main") != value["main"]
            or not valid_oid(value["main"]) or not valid_oid(value["main_tree"])
            or not isinstance(value["reflog_commits"], list) or not all(valid_oid(item) for item in value["reflog_commits"])
            or value["triggering_commit"] is not None and not valid_oid(value["triggering_commit"])):
        raise HarnessError("Backup catalog has invalid identity fields")
    auxiliary = set()
    for name, identity in value["refs"].items():
        if (not isinstance(name, str) or not valid_oid(identity) or
                not (name.startswith(("refs/heads/", "refs/tags/", "refs/notes/", "refs/oasis/recovery/")) or name == "refs/stash"
                     or policy == "isolated-unmanaged" and _codex_tree_ref(name)) or
                run(["git", "-C", str(repo), "check-ref-format", name], env=_plumbing_environment(), check=False).returncode):
            raise HarnessError("Backup catalog has an invalid source ref")
        if _codex_tree_ref(name) and identity not in auxiliary:
            _assert_auxiliary_tree(repo, identity)
            auxiliary.add(identity)
    return value


def _catalog(relay, value):
    old = _git_owned(relay, "rev-parse", "--verify", CATALOG, check=False)
    if old and _read_catalog(relay, old) == value:
        return old
    blob = _git_owned(relay, "hash-object", "-w", "--stdin", input_text=canonical(value).decode("utf-8") + "\n")
    tree = _git_owned(relay, "mktree", input_text=f"100644 blob {blob}\tsnapshot.json\n")
    args = ["git", "-C", str(relay), "commit-tree", tree]
    if old:
        args += ["-p", old]
    env = dict(_plumbing_environment(), **{"GIT_AUTHOR_NAME": "Oasis Backup", "GIT_AUTHOR_EMAIL": "backup@oasis.invalid",
           "GIT_COMMITTER_NAME": "Oasis Backup", "GIT_COMMITTER_EMAIL": "backup@oasis.invalid"}
    )
    oid = run(args, input_text="Retain exact source snapshot\n", env=env).stdout.strip()
    _git_owned(relay, "update-ref", CATALOG, oid, old or "0" * len(oid))
    return oid


def _transport_plan(directory, token, url, pending):
    def quoted(value):
        if any(char in value for char in ("\0", "\n", "\r")):
            raise HarnessError("Invalid control character in private transport configuration")
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    alias = "oasis-transfer-" + token
    lines = ["[remote " + quoted(alias) + "]", "\turl = " + quoted(url)]
    lines.extend("\tpush = " + quoted(f"{oid}:{name}") for name, oid in sorted(pending.items()))
    data = ("\n".join(lines) + "\n").encode("utf-8")
    path = directory / ("transport-" + token + ".config")
    if path.exists():
        raise HarnessError("Private transport plan already exists")
    atomic_write(path, data)
    return {"path": str(path), "sha256": digest(data), "alias": alias, "token": token}


def run_backup(root, *, provider=None, triggering_commit=None):
    provider = _provider(provider)
    config = _config(root)
    root = _assert_source(root, config)
    relay = _relay(config)
    with operation_lock(relay.parent / "oasis-backup.lock"):
        _identity(config, provider)
        before_remote = _remote_refs(config, provider)
        value = _snapshot(root, config, triggering_commit)
        expected = {_map(name, oid): oid for name, oid in value["refs"].items()}
        expected.update({"refs/heads/retained/reflog/" + oid: oid for oid in value["reflog_commits"]})
        object_ids = sorted(set(expected.values()))
        for offset in range(0, len(object_ids), 100):
            _git_owned(relay, "fetch", "--no-tags", str(root), *object_ids[offset:offset + 100])
        relay_refs = dict(line.split(" ", 1) for line in _git_owned(relay, "for-each-ref", "--format=%(refname) %(objectname)").splitlines())
        changes = []
        for name, oid in expected.items():
            old = relay_refs.get(name)
            if old and old != oid:
                if name.startswith("refs/tags/") or run(["git", "-C", str(relay), "merge-base", "--is-ancestor", old, oid], env=_plumbing_environment(), check=False).returncode:
                    raise HarnessError(f"Backup refuses immutable/non-fast-forward ref change: {name}")
            if old != oid:
                changes.append(f"update {name} {oid} {old or '0' * len(oid)}")
        if changes:
            _git_owned(relay, "update-ref", "--stdin", input_text="\n".join(changes) + "\n")
        if _snapshot(root, config, triggering_commit) != value:
            raise HarnessError("Source refs/reflogs changed during transfer; inspect and retry a new snapshot")
        catalog = _catalog(relay, value)
        expected[CATALOG] = catalog
        for name, oid in expected.items():
            old = before_remote.get(name)
            if old and old != oid:
                if name.startswith("refs/tags/") or run(["git", "-C", str(relay), "merge-base", "--is-ancestor", old, oid], env=_plumbing_environment(), check=False).returncode:
                    raise HarnessError(f"Remote contains divergent history: {name}")
        if _snapshot(root, config, triggering_commit) != value:
            raise HarnessError("Source changed before publication")
        _relay(config)
        _assert_source(root, config)
        _identity(config, provider)
        if _remote_refs(config, provider) != before_remote:
            raise HarnessError("Remote moved before backup publication")
        pending = {name: oid for name, oid in expected.items() if before_remote.get(name) != oid}
        token = uuid.uuid4().hex
        operation = contained(relay.parent, "operations/" + token)
        transport = _transport_plan(operation, token, _url(config, provider), pending) if pending else None
        receipt = {"schema_version": 1, "phase": "push_intent", "catalog": catalog, "expected": expected,
                   "token": token, "transport": transport}
        receipt_path = relay.parent / "last-operation.json"
        operation_receipt = operation / "receipt.json"
        write_json(operation_receipt, receipt)
        write_json(receipt_path, receipt)
        if pending:
            # Never mirror, force, delete, or fall back from atomic transport.
            # Exact refspecs live in a token-owned external file, so normal
            # retained history cannot exceed Windows' command-line limit.
            if file_hash(Path(transport["path"])) != transport["sha256"]:
                raise HarnessError("Private transport plan changed before execution")
            args = ["git", "-C", str(relay), "-c", "include.path=" + Path(transport["path"]).as_posix(),
                    "push", "--atomic", transport["alias"]]
            run(args, env=provider.git_environment(), timeout=600)
        _identity(config, provider)
        actual = _remote_refs(config, provider)
        if any(actual.get(name) != oid for name, oid in expected.items()):
            raise HarnessError("Backup readback incomplete; source commit remains intact")
        receipt["phase"] = "verified"
        write_json(operation_receipt, receipt)
        write_json(receipt_path, receipt)
        if transport:
            path = Path(transport["path"])
            saved = read_json(operation_receipt)
            if saved.get("token") == token and path.is_file() and file_hash(path) == transport["sha256"]:
                path.unlink()  # Exact token-owned file; uncertain attempts retain it.
        return {"status": "verified", "catalog": catalog, "refs": len(value["refs"]),
                "triggering_commit": triggering_commit, "working_files_backed_up": False}


def status(root, *, provider=None):
    path = gitops.state_dir(root) / "backup.json"
    if not path.is_file():
        return {"configured": False, "automatic_enabled": False}
    config = _config(root)
    root = _assert_source(root, config)
    provider = _provider(provider)
    _identity(config, provider)
    relay = _relay(config)
    remote = _remote_refs(config, provider)
    local_catalog = _git_owned(relay, "rev-parse", "--verify", CATALOG, check=False)
    matches = bool(local_catalog) and remote.get(CATALOG) == local_catalog
    selected, reflog = _selected(root, source_policy=_source_policy(config))
    catalog = _read_catalog(relay, local_catalog) if matches else None
    source_matches = bool(catalog and catalog["refs"] == selected and catalog["reflog_commits"] == reflog)
    if source_matches:
        expected = {_map(name, oid): oid for name, oid in selected.items()}
        expected.update({"refs/heads/retained/reflog/" + oid: oid for oid in reflog})
        source_matches = all(remote.get(name) == oid for name, oid in expected.items())
    committed_refs = {name: oid for name, oid in selected.items() if name.startswith(("refs/heads/", "refs/tags/"))}
    main_matches = bool(catalog and catalog["main"] == selected["refs/heads/main"]
                        and catalog["main_tree"] == git(root, "rev-parse", "refs/heads/main^{tree}")
                        and remote.get("refs/heads/source/main") == selected["refs/heads/main"]
                        and all(catalog["refs"].get(name) == oid and remote.get(_map(name, oid)) == oid
                                for name, oid in committed_refs.items()))
    auxiliary_matches = None
    if _source_policy(config) == "isolated-unmanaged":
        auxiliary = {name: oid for name, oid in selected.items() if _codex_tree_ref(name)}
        saved = {name: oid for name, oid in catalog["refs"].items() if _codex_tree_ref(name)} if catalog else None
        auxiliary_matches = bool(saved == auxiliary and all(remote.get(_map(name, oid)) == oid for name, oid in auxiliary.items()))
    return {"configured": True, "automatic_enabled": config["automatic_enabled"],
            "source_policy": _source_policy(config),
            "repository_id": config["repository_id"], "remote_catalog": remote.get(CATALOG),
            "relay_matches_remote": matches, "source_refs_match": bool(source_matches),
            "source_main_match": main_matches, "source_auxiliary_refs_match": auxiliary_matches,
            "working_files_backed_up": False}


def export_binding(root, output):
    config = _config(root)
    root = _assert_source(root, config)
    output = _external(root, output)
    if output.exists():
        raise HarnessError("Recovery binding output already exists")
    write_new_json(output, config)
    return {"binding": str(output), "contains_credentials": False,
            "purpose": "Remote-only restore after loss of source and relay"}


def restore(config, destination, *, provider=None):
    destination = Path(destination).absolute()
    for candidate in (destination, *destination.parents):
        if candidate.is_symlink() or is_reparse(candidate):
            raise HarnessError("Restore path traverses a link")
    lock = destination.parent / ("oasis-restore-" + digest(str(destination).casefold())[:24] + ".lock")
    with operation_lock(lock):
        return _restore_reserved(config, destination, provider=provider)


def _restore_reserved(config, destination, *, provider=None):
    provider = _provider(provider)
    _identity(config, provider)
    destination = Path(destination).absolute()
    if destination.is_symlink() or is_reparse(destination) or (destination.exists() and (not destination.is_dir() or any(destination.iterdir()))):
        raise HarnessError("Restore destination must be a new or empty normal directory")
    for protected in (Path(config["primary"]).resolve(), Path(config["relay"]).resolve()):
        if destination.resolve().is_relative_to(protected) or protected.is_relative_to(destination.resolve()):
            raise HarnessError("Restore destination overlaps source or relay")
    for parent in destination.parents:
        if parent.is_symlink() or is_reparse(parent):
            raise HarnessError("Restore path traverses a link")
    remote = _remote_refs(config, provider)
    if CATALOG not in remote:
        raise HarnessError("No remote catalog is available")
    intake = destination.parent / ("oasis-restore-intake-" + uuid.uuid4().hex + ".git")
    run(["git", "init", "--bare", "--template=", str(intake)], env=provider.git_environment())
    for name in remote:
        run(["git", "-C", str(intake), "fetch", "--no-tags", _url(config, provider), f"{name}:{name}"], env=provider.git_environment())
    if _remote_refs(config, provider) != remote:
        raise HarnessError("Remote changed during restore; preserve the intake and retry after inspection")
    value = _read_catalog(intake, remote[CATALOG])
    if value["repository_id"] != config["repository_id"]:
        raise HarnessError("Catalog belongs to another destination")
    if _source_policy(value) != _source_policy(config):
        raise HarnessError("Catalog source policy differs from the reviewed restore binding")
    for name, oid in value["refs"].items():
        if remote.get(_map(name, oid)) != oid:
            raise HarnessError("Remote source refs do not match their retained catalog")
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise HarnessError("Restore destination changed during intake; foreign bytes were preserved")
    run(["git", "init", "--template=", "--initial-branch=main", str(destination)], env=_plumbing_environment())
    _git_owned(destination, "config", "core.autocrlf", "false")
    _git_owned(destination, "config", "core.hooksPath", os.devnull)
    write_json(gitops.state_dir(destination) / "restore-pending.json", {"schema_version": 1, "catalog": remote[CATALOG], "destination": str(destination)})
    for oid in sorted(set(value["refs"].values()) | set(value["reflog_commits"])):
        _git_owned(destination, "fetch", "--no-tags", str(intake), oid)
    changes = [f"create {name} {oid}" for name, oid in value["refs"].items()]
    for oid in value["reflog_commits"]:
        name = "refs/oasis/recovery/" + oid
        if name not in value["refs"]:
            changes.append(f"create {name} {oid}")
    _git_owned(destination, "update-ref", "--stdin", input_text="\n".join(changes) + "\n")
    _git_owned(destination, "symbolic-ref", "HEAD", "refs/heads/main")
    if any(path.name != ".git" for path in destination.iterdir()):
        raise HarnessError("Restore destination changed before checkout; foreign bytes were preserved")
    _git_owned(destination, "read-tree", "refs/heads/main")
    # checkout-index without --force refuses existing files, including a writer
    # racing the preceding directory check. Never reset --hard in restore.
    _git_owned(destination, "checkout-index", "--all")
    _git_owned(destination, "fsck", "--full")
    if _git_owned(destination, "remote") or _git_owned(destination, "for-each-ref", "refs/remotes"):
        raise HarnessError("Restore unexpectedly inherited source remotes")
    if _git_owned(destination, "rev-parse", "main^{tree}") != value["main_tree"] or _git_owned(destination, "status", "--porcelain=v1", "--untracked-files=all"):
        raise HarnessError("Restored main tree/working state failed verification")
    if git(destination, "config", "--get", "core.hooksPath", check=False) != os.devnull:
        raise HarnessError("Restore effective hooks are not inactive")
    proof = {"schema_version": 1, "catalog": remote[CATALOG], "main": value["main"],
             "main_tree": value["main_tree"], "active": False, "intake": str(intake), "destination": str(destination.resolve())}
    write_json(gitops.state_dir(destination) / "restore.json", proof)
    (gitops.state_dir(destination) / "restore-pending.json").unlink()
    return proof


def enable_auto(root, destination, *, provider=None):
    provider = _provider(provider)
    if _source_policy(_config(root)) != "managed":
        raise HarnessError("Automatic backup requires the managed post-commit engine; isolated-unmanaged is manual-only")
    gitops.assert_binding(root)
    run_backup(root, provider=provider)
    config = _config(root)
    proof = restore(config, destination, provider=provider)
    with operation_lock(contained(root, ".oasis/local/operations.lock")):
        _assert_source(root, config)
        _identity(config, provider)
        config["automatic_enabled"] = True
        config["restore_proof"] = {"catalog": proof["catalog"], "main": proof["main"], "destination": proof["destination"]}
        write_json(gitops.state_dir(root) / "backup.json", config)
    return {"automatic_enabled": True, "restore_proof": proof}


def automatic(root, commit, *, provider=None):
    path = gitops.state_dir(root) / "backup.json"
    if not path.is_file():
        return {"inactive": True}
    config = _config(root)
    _assert_source(root, config)
    if not config.get("automatic_enabled"):
        return {"inactive": True}
    return run_backup(root, provider=provider, triggering_commit=commit)


def register(subparsers):
    parser = subparsers.add_parser("backup", help="Explicit private Git backup and inactive remote-only restore")
    commands = parser.add_subparsers(dest="backup_command", required=True)
    for name in ("configure", "status", "run", "enable-auto", "restore", "export-binding"):
        child = commands.add_parser(name)
        if name == "restore":
            source = child.add_mutually_exclusive_group(required=True)
            source.add_argument("--root", type=Path)
            source.add_argument("--binding", type=Path)
        else:
            child.add_argument("--root", type=Path, required=True)
        if name == "configure":
            child.add_argument("--repository", required=True)
            child.add_argument("--repository-id", type=int, required=True)
            child.add_argument("--account-id", type=int, required=True)
            child.add_argument("--relay", type=Path, required=True)
            child.add_argument("--source-policy", choices=SOURCE_POLICIES, default="managed",
                               help="Explicit isolated-unmanaged manual backup preserves reviewed existing source hooks")
            child.set_defaults(func=lambda args: configure(args.root, args.repository, args.relay, args.repository_id, args.account_id,
                                                           source_policy=args.source_policy))
        elif name == "status":
            child.set_defaults(func=lambda args: status(args.root))
        elif name == "run":
            child.set_defaults(func=lambda args: run_backup(args.root))
        elif name == "export-binding":
            child.add_argument("--output", type=Path, required=True)
            child.set_defaults(func=lambda args: export_binding(args.root, args.output))
        else:
            child.add_argument("--destination", type=Path, required=True)
            child.set_defaults(func=(lambda args: enable_auto(args.root, args.destination)) if name == "enable-auto" else
                               (lambda args: restore(read_json(args.binding) if args.binding else _config(args.root), args.destination)))
