"""Explicit local source profiles with branch-independent, identity-bound hooks."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import sys

from .common import (HarnessError, atomic_write, canonical, contained, digest, file_hash,
                     git, is_reparse, operation_lock, read_json, run, write_json)

PROFILES = ("unmanaged", "single-main", "main-test")


def desired_profile(root):
    path = contained(root, ".oasis/project.json")
    value = read_json(path).get("git", {}).get("profile") if path.is_file() else "unmanaged"
    if value not in PROFILES:
        raise HarnessError("Project declares an unsupported desired Git profile")
    return value


def _assert_desired(root, profile):
    if desired_profile(root) != profile:
        raise HarnessError("Commit the requested git.profile in .oasis/project.json before this explicit profile operation")


def root_path(root):
    root = Path(root).absolute()
    if root.is_symlink() or is_reparse(root):
        raise HarnessError("Linked repository root is unsupported")
    actual = Path(git(root, "rev-parse", "--show-toplevel")).resolve()
    if actual != root.resolve():
        raise HarnessError("Select the exact repository root, not its child directory")
    return actual


def common_dir(root):
    return Path(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()


def state_dir(root):
    return common_dir(root) / "oasis"


def refs(root):
    result = {}
    for line in git(root, "for-each-ref", "--format=%(refname) %(objectname)").splitlines():
        name, oid = line.split(" ", 1)
        result[name] = oid
    return result


def head(root):
    return git(root, "rev-parse", "--verify", "HEAD", check=False)


def branch(root):
    return git(root, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)


def assert_isolated(root):
    if git(root, "remote") or git(root, "for-each-ref", "--format=%(refname)", "refs/remotes"):
        raise HarnessError("Managed source must have no remotes or remote-tracking refs; preserve and resolve existing configuration explicitly")
    if git(root, "config", "--get-regexp", r"^branch\..*\.(remote|merge|vscode-merge-base)$", check=False):
        raise HarnessError("Managed source must not have upstream/comparison configuration")
    if git(root, "rev-parse", "--is-shallow-repository") != "false" or git(root, "for-each-ref", "--format=%(refname)", "refs/replace"):
        raise HarnessError("Shallow/replace history cannot establish managed ancestry")
    if (common_dir(root) / "info/grafts").exists():
        raise HarnessError("Grafted history cannot establish managed ancestry")


def assert_clean(root):
    if git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise HarnessError("Profile changes require a clean owned checkout; do not stash or discard peer state")


def _binding(root):
    path = state_dir(root) / "binding.json"
    return read_json(path) if path.is_file() else None


def _assert_engine(binding):
    engine = Path(binding["engine"])
    if engine.is_symlink() or is_reparse(engine):
        raise HarnessError("Linked active engine is forbidden")
    for relative, expected in binding["engine_files"].items():
        path = contained(engine, relative)
        if not path.is_file() or file_hash(path) != expected:
            raise HarnessError(f"Active engine changed or is missing: {relative}")


def assert_binding(root, *, permit_transition=False):
    root = root_path(root)
    binding = _binding(root)
    if not binding or binding.get("schema_version") != 1 or binding.get("primary") != str(root):
        raise HarnessError("Repository is inactive or moved/copied; deliberate rebind is required")
    if str(common_dir(root)) != binding.get("common_dir"):
        raise HarnessError("Git common-directory identity changed; rebind is required")
    if (state_dir(root) / "activation-pending.json").exists():
        raise HarnessError("Interrupted activation requires explicit recovery/rebind")
    if not permit_transition and (state_dir(root) / "transition.json").exists():
        raise HarnessError("Profile transition is pending; resume that exact operation")
    configured = git(root, "config", "--local", "--get-all", "core.hooksPath", check=False).replace("\\", "/")
    effective = git(root, "config", "--get", "core.hooksPath", check=False).replace("\\", "/")
    if configured != binding["hooks_path"] or effective != binding["hooks_path"]:
        raise HarnessError("Active hook binding differs from its verified receipt")
    _assert_engine(binding)
    assert_isolated(root)
    return binding


def status(root):
    root = Path(root).resolve()
    try:
        root = root_path(root)
    except HarnessError as exc:
        return {"profile": "unmanaged", "active": False, "reason": str(exc)}
    binding = _binding(root)
    result = {"profile": binding["profile"] if binding else "unmanaged", "active": False,
              "desired_profile": desired_profile(root),
              "branch": branch(root), "head": head(root), "refs": refs(root),
              "working_state": git(root, "status", "--porcelain=v1", "--untracked-files=all")}
    if binding:
        try:
            assert_binding(root)
            result["active"] = True
        except HarnessError as exc:
            result["reason"] = str(exc)
    result["profile_matches_desired"] = result["profile"] == result["desired_profile"]
    return result


def initialize(root):
    from .installation import MANIFEST, checked_path, target_root
    root = target_root(root)
    manifest = read_json(checked_path(root, MANIFEST))
    with operation_lock(contained(root, ".oasis/local/operations.lock")):
        probe = run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], check=False)
        if probe.returncode:
            if git(root, "rev-parse", "--is-bare-repository", check=False) == "true":
                raise HarnessError("A bare repository requires an explicit checkout mapping")
            run(["git", "init", "--initial-branch=main", str(root)])
        root = root_path(root)
        if head(root):
            raise HarnessError("Repository already has history; initialization never replaces it")
        if branch(root) != "main":
            raise HarnessError("Unborn branch must be explicitly selected as main before initialization")
        assert_isolated(root)
        if git(root, "diff", "--cached", "--name-only"):
            raise HarnessError("Foreign staged data must be resolved before initialization")
        if not git(root, "var", "GIT_AUTHOR_IDENT", check=False):
            raise HarnessError("Configure an actual Git author; the harness never invents one")
        paths = [MANIFEST]
        for relative, record in manifest["managed"].items():
            path = checked_path(root, relative)
            if not path.is_file() or file_hash(path) != record["sha256"]:
                raise HarnessError(f"Reviewed installation changed before initial commit: {relative}")
            paths.extend((relative, ".oasis/base/" + record["base_sha256"]))
        write_json(contained(root, ".oasis/local/initialize.json"), {"schema_version": 1, "state": "committing", "owned": sorted(set(paths))})
        # Keep the command under Windows command-line limits; every path is owned.
        paths = sorted(set(paths))
        for offset in range(0, len(paths), 40):
            git(root, "add", "--", *paths[offset:offset + 40])
        git(root, "commit", "-m", "Initialize Oasis Harness")
        result = {"schema_version": 1, "state": "committed", "head": head(root), "profile": "unmanaged"}
        write_json(contained(root, ".oasis/local/initialize.json"), result)
        return result


def _shell_quote(value):
    return "'" + str(value).replace("'", "'\"'\"'") + "'"


def install_engine(root):
    source = Path(__file__).resolve().parent
    files = {"oasis_harness/" + p.relative_to(source).as_posix(): p.read_bytes()
             for p in source.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}
    runner = b'''import pathlib, sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from oasis_harness.gitops import hook_main
raise SystemExit(hook_main(sys.argv[1:]))
'''
    files["hook.py"] = runner
    engine_id = digest({"files": {name: digest(data) for name, data in files.items()},
                        "primary": str(root), "common_dir": str(common_dir(root)),
                        "python": str(Path(sys.executable).resolve())})
    engine = state_dir(root) / "engines" / engine_id
    for name in ("pre-commit", "reference-transaction", "pre-push", "post-commit"):
        command = "#!/bin/sh\nexec " + _shell_quote(Path(sys.executable).as_posix()) + " " + _shell_quote((engine / "hook.py").as_posix()) + " " + name + ' "$@"\n'
        files["hooks/" + name] = command.encode("utf-8")
    for relative, data in files.items():
        path = contained(engine, relative)
        if path.exists():
            if path.read_bytes() != data:
                raise HarnessError("Previously installed immutable engine has changed")
        else:
            atomic_write(path, data)
        if relative.startswith("hooks/"):
            path.chmod(path.stat().st_mode | 0o111)
    return engine, {name: digest(data) for name, data in files.items()}


def activate(root, profile, expected_head, *, rebind=False):
    root = root_path(root)
    if profile not in ("single-main", "main-test"):
        raise HarnessError("Select a managed profile")
    with operation_lock(contained(root, ".oasis/local/operations.lock")):
        assert_isolated(root); assert_clean(root)
        _assert_desired(root, profile)
        if head(root) != expected_head or branch(root) != "main" or git(root, "rev-parse", "refs/heads/main") != expected_head:
            raise HarnessError("Activation requires exact reviewed main checkout/HEAD")
        old = _binding(root)
        if old and not rebind:
            raise HarnessError("Already configured; use transition or deliberate rebind")
        configured = git(root, "config", "--get-all", "core.hooksPath", check=False)
        restore_receipt = state_dir(root) / "restore.json"
        inactive_restore = bool(rebind and restore_receipt.is_file() and
                                read_json(restore_receipt).get("destination") == str(root) and
                                git(root, "config", "--get", "core.hooksPath", check=False) == os.devnull)
        if configured and not old and not inactive_restore:
            raise HarnessError("Existing hooks require explicit migration; no automatic replacement")
        hook_directory = common_dir(root) / "hooks"
        if not old and hook_directory.is_dir() and any(p.is_file() and not p.name.endswith(".sample") for p in hook_directory.iterdir()):
            raise HarnessError("Existing default hook files require explicit migration")
        all_refs = refs(root)
        test = all_refs.get("refs/heads/test")
        if profile == "main-test" and test not in (None, expected_head):
            raise HarnessError("Divergent test requires an explicit history mapping")
        engine, inventory = install_engine(root)
        assert_clean(root)
        if head(root) != expected_head or branch(root) != "main" or refs(root) != all_refs:
            raise HarnessError("Source identity or refs changed while preparing activation")
        binding = {"schema_version": 1, "profile": profile, "primary": str(root),
                   "common_dir": str(common_dir(root)), "engine": str(engine), "engine_files": inventory,
                   "hooks_path": (engine / "hooks").as_posix(),
                   "retained_heads": {name: oid for name, oid in all_refs.items() if name.startswith("refs/heads/") and name not in ("refs/heads/main", "refs/heads/test")}}
        pending = state_dir(root) / "activation-pending.json"
        write_json(pending, {"binding": binding, "previous": old, "expected_head": expected_head})
        if profile == "main-test" and test is None:
            # First activation has not bound the new hooks yet. Existing hooks
            # were refused above. Rebind cannot silently create missing history.
            if old:
                raise HarnessError("Rebind requires retained test; inspect interrupted activation")
            git(root, "update-ref", "refs/heads/test", expected_head, "0" * len(expected_head))
        expected_refs = dict(all_refs)
        if profile == "main-test":
            expected_refs["refs/heads/test"] = expected_head
        assert_clean(root)
        if head(root) != expected_head or branch(root) != "main" or refs(root) != expected_refs:
            raise HarnessError("Source changed during activation; pending evidence retained")
        git(root, "config", "--local", "core.hooksPath", binding["hooks_path"])
        if git(root, "config", "--local", "--get-all", "core.hooksPath").replace("\\", "/") != binding["hooks_path"]:
            raise HarnessError("Hook configuration readback failed; retain pending activation")
        write_json(state_dir(root) / "binding.json", binding)
        pending.unlink()
        return {"profile": profile, "active": True, "head": expected_head, "hooks": binding["hooks_path"]}


def transition(root, profile, expected_main, expected_test=None):
    root = root_path(root)
    if profile not in ("single-main", "main-test"):
        raise HarnessError("Managed deactivation/history migration requires a separate reviewed operation")
    with operation_lock(contained(root, ".oasis/local/operations.lock")):
        binding = assert_binding(root, permit_transition=True)
        assert_clean(root)
        _assert_desired(root, profile)
        if branch(root) != "main" or head(root) != expected_main:
            raise HarnessError("Transition requires exact reviewed main selected by its owner")
        current = refs(root).get("refs/heads/test")
        pending = state_dir(root) / "transition.json"
        saved = read_json(pending) if pending.exists() else None
        already_created = bool(saved and saved["to"] == "main-test" and saved["test"] is None and current == expected_main)
        if current != expected_test and not already_created:
            raise HarnessError("Test tip changed from the reviewed expected value")
        if current not in (None, expected_main):
            raise HarnessError("Divergent histories require an explicit mapping; no automatic merge")
        if profile == binding["profile"]:
            if saved:
                if (saved.get("to") != profile or saved.get("main") != expected_main or
                        saved.get("test") != expected_test or saved.get("primary") != str(root)):
                    raise HarnessError("Another transition is pending")
                pending.unlink()
                return {"status": "recovered", "profile": profile}
            return {"status": "unchanged", "profile": profile}
        receipt = {"schema_version": 1, "from": binding["profile"], "to": profile,
                   "main": expected_main, "test": expected_test, "primary": str(root)}
        if pending.exists() and read_json(pending) != receipt:
            raise HarnessError("Another transition is pending")
        write_json(pending, receipt)
        if profile == "main-test" and current is None:
            git(root, "update-ref", "refs/heads/test", expected_main, "0" * len(expected_main))
        binding["profile"] = profile
        write_json(state_dir(root) / "binding.json", binding)
        pending.unlink()
        return {"status": "transitioned", "profile": profile, "main": expected_main,
                "test": refs(root).get("refs/heads/test"), "retained": profile == "single-main"}


def recover(root, expected_head):
    """Resume the exact local journal; never infer rollback or rewrite refs."""
    root = root_path(root)
    pending = state_dir(root) / "activation-pending.json"
    if pending.is_file():
        with operation_lock(contained(root, ".oasis/local/operations.lock")):
            saved = read_json(pending)
            binding = saved["binding"]
            assert_isolated(root); assert_clean(root)
            _assert_desired(root, binding["profile"])
            if (saved["expected_head"] != expected_head or head(root) != expected_head or branch(root) != "main"
                    or binding["primary"] != str(root) or binding["common_dir"] != str(common_dir(root))):
                raise HarnessError("Pending activation no longer matches the reviewed identity")
            _assert_engine(binding)
            actual = refs(root)
            if any(actual.get(name) != oid for name, oid in binding["retained_heads"].items()):
                raise HarnessError("Retained history moved during activation")
            current_hooks = git(root, "config", "--local", "--get-all", "core.hooksPath", check=False).replace("\\", "/")
            allowed = {"", binding["hooks_path"]}
            if saved.get("previous"):
                allowed.add(saved["previous"]["hooks_path"])
            if current_hooks not in allowed:
                raise HarnessError("Hook configuration changed during activation")
            if binding["profile"] == "main-test" and actual.get("refs/heads/test") != expected_head:
                if actual.get("refs/heads/test") is not None or saved.get("previous") or current_hooks:
                    raise HarnessError("Pending activation lacks its exact test seed; inspect before recovery")
                git(root, "update-ref", "refs/heads/test", expected_head, "0" * len(expected_head))
            git(root, "config", "--local", "core.hooksPath", binding["hooks_path"])
            if git(root, "config", "--local", "--get-all", "core.hooksPath").replace("\\", "/") != binding["hooks_path"]:
                raise HarnessError("Recovered hook binding readback failed")
            write_json(state_dir(root) / "binding.json", binding)
            pending.unlink()
            return {"status": "recovered", "profile": binding["profile"]}
    pending = state_dir(root) / "transition.json"
    if pending.is_file():
        saved = read_json(pending)
        if expected_head != saved["main"]:
            raise HarnessError("Recovery expected head differs from transition")
        return transition(root, saved["to"], saved["main"], saved["test"])
    raise HarnessError("No pending profile operation exists")


def enforce_reference(root, phase, payload):
    if phase in ("committed", "aborted"):
        return
    if phase != "prepared":
        raise HarnessError("Unknown ref transaction phase")
    binding = assert_binding(root, permit_transition=True)
    pending_path = state_dir(root) / "transition.json"
    pending = read_json(pending_path) if pending_path.exists() else None
    for line in payload.splitlines():
        fields = line.split()
        if len(fields) != 3:
            raise HarnessError("Malformed ref transaction")
        old, new, ref = fields
        if ref in ("HEAD", "ORIG_HEAD", "AUTO_MERGE", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "REBASE_HEAD", "BISECT_EXPECTED_REV"):
            continue
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", old) or len(new) != len(old) or not re.fullmatch(r"[0-9a-f]+", new):
            raise HarnessError("Invalid ref object identity")
        zero = "0" * len(old)
        if pending:
            if not (pending["to"] == "main-test" and pending["primary"] == str(root)
                    and ref == "refs/heads/test" and old == zero and new == pending["main"]
                    and head(root) == pending["main"]):
                raise HarnessError("Only the exact pending transition may mutate refs")
            continue
        if ref.startswith("refs/tags/"):
            # Git's deletion APIs may omit expected-old and send 0 -> 0.
            # Inspect current state too, so that omission never weakens anchors.
            actual = git(root, "show-ref", "--verify", "--hash", ref, check=False)
            if old != zero or new == zero or actual:
                raise HarnessError("Existing source tags are immutable")
            continue
        if ref.startswith("refs/heads/"):
            allowed = {"refs/heads/main"} | ({"refs/heads/test"} if binding["profile"] == "main-test" else set())
            if ref not in allowed:
                raise HarnessError("Retained/non-profile branches are immutable")
            if old == zero or new == zero:
                raise HarnessError("Managed lanes cannot be created/deleted outside profile transition")
            if run(["git", "-C", str(root), "merge-base", "--is-ancestor", old, new], check=False).returncode:
                raise HarnessError("Managed lanes must advance without rewriting history")
        elif ref not in ("refs/stash",) and not ref.startswith("refs/notes/"):
            raise HarnessError(f"Unclassified source ref mutation: {ref!r}")


def hook_main(argv):
    event = argv[0] if argv else ""
    try:
        root = root_path(Path.cwd())
        if event == "reference-transaction":
            enforce_reference(root, argv[1] if len(argv) > 1 else "", sys.stdin.read())
        elif event == "pre-push":
            raise HarnessError("Managed source never pushes; use a bound external provider workspace")
        elif event == "pre-commit":
            binding = assert_binding(root)
            if branch(root) not in (("main", "test") if binding["profile"] == "main-test" else ("main",)):
                raise HarnessError("Only the selected managed lane may commit")
        elif event == "post-commit":
            assert_binding(root)
            from .backup import automatic
            automatic(root, head(root))
        else:
            raise HarnessError("Unknown hook event")
        return 0
    except Exception as exc:
        print(f"Oasis {event}: {exc}", file=sys.stderr)
        if event == "post-commit":
            print("The source commit remains intact. Inspect backup status and run backup run after recovery.", file=sys.stderr)
            return 0
        return 1


def register(subparsers):
    parser = subparsers.add_parser("git", help="Inspect or explicitly activate managed source profiles")
    commands = parser.add_subparsers(dest="git_command", required=True)
    for name in ("status", "initialize", "activate", "rebind", "transition", "recover"):
        child = commands.add_parser(name)
        child.add_argument("--root", type=Path, required=True)
        if name in ("activate", "rebind"):
            child.add_argument("--profile", choices=PROFILES[1:], required=True)
            child.add_argument("--expected-head", required=True)
            child.set_defaults(func=lambda args, rebind=name == "rebind": activate(args.root, args.profile, args.expected_head, rebind=rebind))
        elif name == "transition":
            child.add_argument("--profile", choices=PROFILES[1:], required=True)
            child.add_argument("--expected-main", required=True)
            child.add_argument("--expected-test")
            child.set_defaults(func=lambda args: transition(args.root, args.profile, args.expected_main, args.expected_test))
        elif name == "initialize":
            child.set_defaults(func=lambda args: initialize(args.root))
        elif name == "recover":
            child.add_argument("--expected-head", required=True)
            child.set_defaults(func=lambda args: recover(args.root, args.expected_head))
        else:
            child.set_defaults(func=lambda args: status(args.root))
