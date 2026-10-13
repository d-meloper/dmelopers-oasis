"""Project mode preparation and native evidence reconciliation.

Messages, archiving and navigation belong to the authorized agent's supported
app tools. This adapter only creates session metadata and reads native evidence.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
import uuid

from . import sessions
from .common import HarnessError, contained, digest, file_hash, is_reparse, operation_lock, read_json, run, write_json

MODES = {"pioneer": ("Pioneer",), "oasis": ("Oasis", "Cameleer")}
ROLE_PARENT = {"Pioneer": None, "Oasis": None, "Cameleer": None,
               "Developer": "Pioneer", "Camel": "Cameleer", "Calf": "Camel"}
CONTEXT_KEYS = {"purpose", "status", "decisions", "commands", "checked", "unperformed", "open_work", "resume"}
SNAPSHOT_EXCLUDED = {".git", "node_modules", ".venv", "venv", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "__pycache__"}
ACKS = {
    "ko": {"Pioneer": "개척 모드 준비를 마쳤습니다. 다음 요청을 기다리겠습니다.",
           "Oasis": "오아시스 역할 준비를 마쳤습니다. 다음 요청을 기다리겠습니다.",
           "Cameleer": "오아시스 모드 준비를 마쳤습니다. 다음 요청을 기다리겠습니다."},
    "en": {"Pioneer": "Pioneer mode is ready. I will wait for the next request.",
           "Oasis": "The Oasis role is ready. I will wait for the next request.",
           "Cameleer": "Oasis mode is ready. I will wait for the next request."},
}


def effective_mode(project):
    """An installed legacy config retains operations until explicitly changed."""
    extensions = project.get("extensions", {})
    if not isinstance(extensions, dict):
        raise HarnessError("Project extensions must be an object")
    workflow = extensions.get("workflow", {})
    if not isinstance(workflow, dict):
        raise HarnessError("extensions.workflow must be an object")
    mode = workflow.get("mode", "oasis")
    if not isinstance(mode, str) or mode not in MODES:
        raise HarnessError("extensions.workflow.mode must be pioneer or oasis")
    return mode


def _root(target):
    from .installation import ADOPTER_MANUALS, ADOPTER_MODULES, target_root
    from .skills import DEFAULT_NAMES, check_core
    root = target_root(target)
    project = check_core(root)["project"]
    manifest_path = contained(root, ".oasis/install-manifest.json")
    if not manifest_path.is_file():
        raise HarnessError("Installation ownership is incomplete. Recover/apply the reviewed installation before initializing chats")
    manifest = read_json(manifest_path)
    managed = manifest.get("managed")
    if manifest.get("schema_version") != 1 or not isinstance(managed, dict):
        raise HarnessError("Installation manifest is invalid; preserve it for installation recovery")
    required = {".oasis/core.json", ".oasis/project.json", "AGENTS.md", "ProjectGuide.md", "tools/oasis.py"}
    required.update(".oasis/runtime/oasis_harness/" + name for name in ADOPTER_MODULES)
    required.update(".oasis/manual/" + name for name in ADOPTER_MANUALS)
    required.update(f".agents/skills/{name}/{leaf}" for name in DEFAULT_NAMES for leaf in ("SKILL.md", "agents/openai.yaml"))
    if not required.issubset(managed):
        raise HarnessError("Installed workflow/default-role ownership is incomplete; recover the reviewed installation before chat initialization")
    for relative, record in managed.items():
        if not isinstance(record, dict) or not record.get("sha256") or not record.get("base_sha256") or not contained(root, relative).is_file():
            raise HarnessError("An owned installation file is missing or its manifest is incomplete; recover installation before workflow actions")
    return root, project


def _local(root, suffix):
    return contained(root, ".oasis/local/workflows/" + suffix)


def _state(root):
    path = _local(root, "state.json")
    if not path.exists():
        return {"schema_version": 1, "target": str(root), "generation": 0, "mode": None,
                "project_id": None, "roles": [], "history": [], "pending_operation": None}
    value = read_json(path)
    if (value.get("schema_version") != 1 or sessions.canonical_root(value.get("target", "")) != sessions.canonical_root(root)
            or not isinstance(value.get("roles"), list) or not isinstance(value.get("history"), list)):
        raise HarnessError("Workflow state belongs to another root or is invalid; preserve it for recovery")
    return value


def status(target):
    root, project = _root(target)
    value = _state(root)
    return {"selected_mode": effective_mode(project), "initialized_mode": value["mode"],
            "initialization_required": value["mode"] is None,
            "transition_required": value["mode"] is not None and effective_mode(project) != value["mode"],
            "pending_operation": value.get("pending_operation"), "roles": value["roles"],
            "native_health": "not inspected", "selection_is_authority": False}


def source_snapshot(root):
    """Hash source/index state without checkout, staging or reading private logs."""
    def git_read(*args, check=True):
        return run(["git", "-c", "core.fsmonitor=false", "-C", str(root), *args],
                   check=check, env={"GIT_OPTIONAL_LOCKS": "0"})
    probe = git_read("rev-parse", "--show-toplevel", check=False)
    files = {}
    def walk_error(exc):
        raise HarnessError("Source inventory is unreadable; inspect the saved checkpoint before workflow actions") from exc
    for directory, names, leaves in os.walk(root, followlinks=False, onerror=walk_error):
        current = Path(directory)
        relative = current.relative_to(root).as_posix()
        names[:] = [name for name in names if name.casefold() not in SNAPSHOT_EXCLUDED
                    and not (relative == ".oasis" and name == "local")]
        for name in list(names):
            path = current / name
            if path.is_symlink() or is_reparse(path):
                raise HarnessError("Linked covered source needs a verified ownership adapter before workflow transition")
        for name in leaves:
            path = current / name
            if path == root / ".git":
                continue
            relative_file = path.relative_to(root).as_posix()
            if path.is_symlink() or is_reparse(path):
                raise HarnessError("Linked covered source needs a verified ownership adapter before workflow transition")
            elif path.is_file():
                files[relative_file] = file_hash(path)
    if probe.returncode:
        return {"git": False, "files": files, "excluded_directories": sorted(SNAPSHOT_EXCLUDED)}
    if sessions.canonical_root(probe.stdout.strip()) != sessions.canonical_root(root):
        raise HarnessError("Project is inside another Git root; review source ownership before transition")
    head = git_read("rev-parse", "--verify", "HEAD", check=False)
    index = git_read("rev-parse", "--git-path", "index").stdout.strip()
    index_path = Path(index) if Path(index).is_absolute() else root / index
    # No raw source bytes or credential values are retained in the journal.
    diff = git_read("diff", "--binary", "--no-ext-diff", "--no-textconv", "HEAD", check=False)
    if head.returncode:
        diff = git_read("diff", "--binary", "--no-ext-diff", "--no-textconv", "--cached")
    elif diff.returncode:
        raise HarnessError("Git source diff is unavailable; preserve its state before workflow actions")
    names = git_read("ls-files", "--others", "--exclude-standard", "-z").stdout.split("\0")
    untracked = {}
    for name in names:
        if (not name or name.startswith(".oasis/local/")
                or any(part.casefold() in SNAPSHOT_EXCLUDED for part in Path(name).parts[:-1])):
            continue
        path = contained(root, name)
        if path.is_file():
            untracked[name] = file_hash(path)
    return {"git": True, "head": head.stdout.strip() if not head.returncode else None,
            "index_sha256": file_hash(index_path) if index_path.is_file() else None,
            "diff_sha256": digest(diff.stdout.encode("utf-8")), "untracked": untracked, "files": files,
            "excluded_directories": sorted(SNAPSHOT_EXCLUDED)}


def _text_hash(text):
    return digest(text.encode("utf-8"))


def _caller(source_id):
    actual = os.environ.get("CODEX_THREAD_ID")
    if not source_id or (actual and actual != source_id):
        raise HarnessError("Use the actual caller thread ID; an alternate supplied ID grants no authority")


def _user_text(item):
    content = item.get("content")
    if not isinstance(content, list) or not content or any(part.get("type") != "text" or not isinstance(part.get("text"), str) for part in content):
        raise HarnessError("Initial assignment has unsupported non-text evidence; review it with a verified adapter")
    return "\n".join(part["text"] for part in content)


def _first_user(thread):
    if not isinstance(thread.get("turns"), list):
        raise HarnessError("Native complete turn history is unavailable; first-message verification is pending")
    for turn in thread["turns"]:
        for item in turn.get("items", []):
            if item.get("type") == "userMessage":
                return turn, item, _user_text(item)
    return None


def _thread(server, identity, root, project_id, *, turns=True):
    thread = server.call("thread/read", {"threadId": identity, "includeTurns": turns})["thread"]
    if (thread.get("id") != identity or sessions.canonical_root(thread.get("cwd", "")) != sessions.canonical_root(root)
            or thread.get("projectId") != project_id):
        raise HarnessError("Native thread identity, project and root must match the workflow binding")
    return thread


def _idle(thread):
    return (thread.get("status") or {}).get("type") in ("idle", "notLoaded")


def _listing(server, root, *, archived):
    return {row["id"]: row for row in server.pages("thread/list", {
        "archived": archived, "cwd": str(root), "sourceKinds": sessions.SOURCES, "limit": 100})
        if sessions.canonical_root(row.get("cwd", "")) == sessions.canonical_root(root)}


def verify_binding(server, binding, root, project_id):
    if (not isinstance(binding.get("role"), str) or binding["role"] not in (*ROLE_PARENT, "Unrelated")
            or not isinstance(binding.get("thread_id"), str) or not binding["thread_id"]
            or not isinstance(binding.get("first_user_message_sha256"), str)):
        raise HarnessError("A role needs a scoped ID and reviewed native first-message hash; a title is insufficient")
    thread = _thread(server, binding["thread_id"], root, project_id)
    first = _first_user(thread)
    if not first or _text_hash(first[2]) != binding["first_user_message_sha256"]:
        raise HarnessError("Native initial assignment differs from the reviewed role binding")
    return thread


def _bindings(server, root, identity, bindings):
    result, seen = [], set()
    active = _listing(server, root, archived=False)
    archived = _listing(server, root, archived=True)
    if not isinstance(bindings, list) or any(not isinstance(row, dict) for row in bindings):
        raise HarnessError("Workflow bindings must be a list of reviewed role objects")
    for row in bindings:
        if row.get("thread_id") in seen:
            if row in result:
                continue
            raise HarnessError("Conflicting duplicate workflow role binding")
        seen.add(row.get("thread_id"))
        if row.get("thread_id") not in active:
            if row.get("thread_id") not in archived:
                raise HarnessError("Bound chat is neither active nor provably archived; reconcile native identity before any creation")
            verify_binding(server, row, root, identity)
            continue
        verify_binding(server, row, root, identity)
        result.append(copy.deepcopy(row))
    indexed = {row["thread_id"]: row for row in result}
    for row in result:
        parent_role = ROLE_PARENT.get(row["role"])
        parent_id = row.get("parent_thread_id")
        if parent_role and (parent_id not in indexed or indexed[parent_id]["role"] != parent_role):
            raise HarnessError("Connected worker binding has no matching scoped parent role")
        if not parent_role and parent_id is not None:
            raise HarnessError("A primary role cannot acquire an invented parent binding")
    for role in ("Pioneer", "Oasis", "Cameleer"):
        if sum(row["role"] == role for row in result) > 1:
            raise HarnessError("Multiple active bindings for one primary role need owner reconciliation")
    return result


def _linked_receipts(server, root, identity, bindings):
    """Creation receipts identify possible linked workers, never their titles."""
    result = list(bindings)
    indexed = {row["thread_id"]: row for row in result}
    active = _listing(server, root, archived=False)
    receipts = [read_json(path) for path in contained(root, ".oasis/local/sessions").glob("*/receipt.json")]
    while True:
        added = False
        for receipt in receipts:
            thread_id = receipt.get("thread_id")
            if thread_id in indexed:
                continue
            parent = receipt.get("parent_thread_id") or receipt.get("source_thread_id")
            parent_role = indexed.get(parent, {}).get("role")
            expected = {"Pioneer": "Developer", "Cameleer": "Camel", "Camel": "Calf"}.get(parent_role)
            role = receipt.get("role")
            potential = expected and (role == expected or not role)
            if not potential:
                continue
            if receipt.get("project_id") != identity or sessions.canonical_root(receipt.get("target", "")) != sessions.canonical_root(root):
                raise HarnessError("Linked worker receipt has a different project/root; reconcile exact ownership")
            if receipt.get("phase") == "archived":
                if thread_id in active:
                    raise HarnessError("A linked worker was reactivated after its archived receipt; reconcile its actual scope with the owner")
                if thread_id and thread_id in _listing(server, root, archived=True):
                    continue
                raise HarnessError("Archived linked worker receipt has no native archive evidence; retain it for recovery")
            if not thread_id or receipt.get("phase") != "ready":
                raise HarnessError("A linked worker creation is incomplete; inspect/resume its retained session receipt before transition")
            if thread_id not in active:
                if thread_id not in _listing(server, root, archived=True):
                    raise HarnessError("Linked worker has no resolved active/archive identity; retain it for recovery")
                continue
            marker = receipt.get("assignment_marker")
            thread = _thread(server, thread_id, root, identity)
            first = _first_user(thread)
            if (role != expected or not marker or not receipt.get("authority_reference")
                    or not first or not first[2].startswith(marker + "\n")):
                raise HarnessError("Linked worker lacks a verified native role assignment; supply its reviewed first-message binding or resume assignment")
            row = {"role": role, "thread_id": thread_id, "parent_thread_id": parent,
                   "first_user_message_sha256": _text_hash(first[2]), "session_originator": receipt["originator"]}
            result.append(row)
            indexed[thread_id] = row
            added = True
        if not added:
            return _bindings(server, root, identity, result)


def _checkpoints(server, root, identity, roles, source_id):
    for row in roles:
        thread = verify_binding(server, row, root, identity)
        if not _idle(thread) and row["thread_id"] != source_id:
            raise HarnessError("A connected writer has not reached a saved checkpoint. Wait for its work/save, then prepare a fresh workflow plan; no targets were created")


def bound_pioneer(target, source_id, server=None):
    root, project = _root(target)
    state = _state(root)
    if effective_mode(project) != "pioneer" or state["mode"] != "pioneer" or state.get("pending_operation"):
        raise HarnessError("Developer delegation requires an initialized Pioneer workflow without a pending transition")
    binding = next((row for row in state["roles"] if row.get("role") == "Pioneer" and row.get("thread_id") == source_id), None)
    if not binding:
        raise HarnessError("Actual caller is not the bound Pioneer; a matching title grants no delegation authority")
    if server is not None:
        verify_binding(server, binding, root, state["project_id"])
    return source_id


def _descendants(server, identity):
    return list(server.pages("thread/list", {"ancestorThreadId": identity, "archived": False,
                                           "sourceKinds": sessions.SOURCES, "limit": 100}))


def _archive_guard(server, root, identity, old_roles):
    scoped = {row["thread_id"] for row in old_roles}
    descendants = {}
    for row in old_roles:
        children = _descendants(server, row["thread_id"])
        if any(child.get("id") not in scoped or child.get("projectId") != identity
               or sessions.canonical_root(child.get("cwd", "")) != sessions.canonical_root(root) for child in children):
            raise HarnessError("Archiving would cascade to an unscoped descendant; inspect exact ownership before proceeding")
        descendants[row["thread_id"]] = {child["id"] for child in children}
    return descendants


def _prompt(operation, role, context, language):
    marker = f"[OASIS_WORKFLOW {operation} {role}]"
    skill = {"Pioneer": "oasis-pioneer", "Oasis": "oasis-maintenance", "Cameleer": "oasis-cameleer"}[role]
    if language == "ko":
        lines = [marker, f"이 프로젝트의 {role} 역할을 맡습니다. ${skill} 지침을 적용하세요.",
                 "아래 인계 내용은 현재 목적과 저장된 작업 상태입니다. 미완료 작업을 완료·취소하거나 자동으로 재개하지 마세요.",
                 "Camel/Calf 질문과 결과는 소유자가 수동으로 전달합니다. 다른 역할의 메시지를 자동 전달하지 마세요.",
                 "지금은 읽기와 도구 실행 없이 다음 문장만 답하고 다음 소유자 요청을 기다리세요:", ACKS[language][role]]
    else:
        lines = [marker, f"You are assigned the {role} role for this project. Apply ${skill}.",
                 "The handover records the current purpose and saved work. Preserve unfinished work without completing, cancelling or automatically resuming it.",
                 "The owner manually relays Camel/Calf questions and results. Do not forward other roles' messages automatically.",
                 "For this first turn, perform no reads or tools. Reply only with the following sentence, then wait for the owner's next request:", ACKS[language][role]]
    if context:
        import json
        lines += ["", json.dumps(context, ensure_ascii=False, sort_keys=True, indent=2)]
    return "\n".join(lines)


def _sealed(value, key):
    result = copy.deepcopy(value)
    result[key] = digest(result)
    return result


def _check_seal(value, key):
    expected = value.get(key)
    actual = {name: item for name, item in value.items() if name != key}
    if not expected or digest(actual) != expected:
        raise HarnessError("Reviewed workflow plan bytes changed; prepare a new exact plan")


def plan(target, mode=None, source_id=None, *, lane=None, context=None, bindings=None,
         task=None, language="ko", factory=sessions.AppServer):
    root, project = _root(target)
    _caller(source_id)
    mode = mode or effective_mode(project)
    if not isinstance(mode, str) or mode not in MODES or not isinstance(language, str) or language not in ACKS:
        raise HarnessError("Select pioneer|oasis and the owner's supported language ko|en")
    context = context or {}
    if not isinstance(context, dict) or set(context) - CONTEXT_KEYS:
        raise HarnessError("Use only purpose/status/decisions/commands/checked/unperformed/open_work/resume context; role messages stay local")
    if task is not None and (not isinstance(task, str) or not task.strip()):
        raise HarnessError("An explicit follow-on task must be nonempty text")
    state = _state(root)
    if bindings is not None and not isinstance(bindings, list):
        raise HarnessError("Workflow bindings must be a list of reviewed role objects")
    if state.get("pending_operation"):
        raise HarnessError(f"Resume the retained pending workflow operation: {state['pending_operation']}")
    operation = "oasis_workflow_" + uuid.uuid4().hex
    readiness = sessions.source_readiness(root, lane)
    with factory(operation + "_plan") as server:
        identity, settings, source = sessions.prepare(server, source_id, root)
        if state.get("project_id") not in (None, identity):
            raise HarnessError("Saved workflow project binding changed; inspect actual project ownership")
        reviewed_bindings = _bindings(server, root, identity, state["roles"] + state.get("unrelated", []) + (bindings or []))
        unrelated = [row for row in reviewed_bindings if row["role"] == "Unrelated"]
        owned = [row for row in reviewed_bindings if row["role"] != "Unrelated"]
        owned = _linked_receipts(server, root, identity, owned)
        caller_role = next((row["role"] for row in owned if row["thread_id"] == source_id), None)
        if mode == "oasis" and caller_role in ("Camel", "Calf"):
            raise HarnessError("Camel/Calf cannot deliver context or results to Cameleer through a workflow transition; use owner manual relay")
        primary = "Pioneer" if mode == "pioneer" else "Cameleer"
        same = all(any(row["role"] == role for row in owned) for role in MODES[mode])
        # An operator-reviewed legacy binding can establish an existing healthy
        # role set; titles alone cannot silently reuse or replace chats.
        same = same and not any(row["role"] in MODES["oasis" if mode == "pioneer" else "pioneer"] for row in owned)
        old = [] if same else owned
        if old and not context.get("status"):
            raise HarnessError("Record the saved checkpoint status and exact unfinished/resume work before transitioning")
        if old:
            _checkpoints(server, root, identity, old, source_id)
            _archive_guard(server, root, identity, old)
        named = [row for row in sessions.discover(server, root, identity)
                 if row.get("name") in MODES[mode] and row["id"] not in {item["thread_id"] for item in owned + unrelated}]
        if named:
            raise HarnessError("Unbound existing role-titled chats need exact owner-reviewed bindings before creating duplicates")
        targets = [] if same else [{"role": role, "originator": operation + "_" + role.lower(),
                                   "prompt": _prompt(operation, role, context, language), "ack": ACKS[language][role]}
                                  for role in MODES[mode]]
    value = {"schema_version": 1, "operation_id": operation, "target": str(root), "project_id": identity,
             "source_thread_id": source_id, "settings": settings, "source_readiness": readiness,
             "source_snapshot": source_snapshot(root), "project_sha256": digest(project),
             "state_sha256": digest(state), "selected_mode_before": effective_mode(project),
             "mode": mode, "primary_role": primary, "language": language,
             "context": context, "follow_on_task": task, "existing_roles": owned, "old_roles": old,
             "unrelated": unrelated,
             "new_roles": targets, "same_mode": same,
             "native_lifecycle_executor": "authorized agent using supported app tools",
             "authority_independently_verified": False}
    return _sealed(value, "plan_sha256")


def _receipt_path(value):
    operation = value.get("operation_id", "")
    if not operation.startswith("oasis_workflow_") or not operation[15:].isalnum():
        raise HarnessError("Invalid workflow operation ID")
    return _local(Path(value["target"]), f"operations/{operation}/receipt.json")


def _read_receipt(path):
    value = read_json(path)
    if Path(path).resolve() != _receipt_path(value).resolve() or value.get("schema_version") != 1:
        raise HarnessError("Workflow receipts must remain in their bound project's private operation path")
    _root(value["target"])
    return value


def _verify_source(value):
    sessions.refresh_readiness(value)
    if source_snapshot(Path(value["target"])) != value["source_snapshot"]:
        raise HarnessError("Source/index state changed after the checkpoint; preserve it and reconcile the retained operation")


def _action(kind, operation, identity, **kwargs):
    return {"id": f"{operation}:{kind}:{identity}", "kind": kind, "thread_id": identity,
            "attempt": "not_started", "observed": False, **kwargs}


def start(reviewed, authority, factory=sessions.AppServer):
    reviewed = read_json(reviewed) if isinstance(reviewed, (str, Path)) else copy.deepcopy(reviewed)
    _check_seal(reviewed, "plan_sha256")
    if not authority:
        raise HarnessError("Workflow start needs the actual owner's concrete initialization or mode-switch request")
    _caller(reviewed["source_thread_id"])
    root, project = _root(reviewed["target"])
    path = _receipt_path(reviewed)
    with operation_lock(contained(root, ".oasis/local/operations.lock")):
        state = _state(root)
        if state.get("pending_operation"):
            if Path(state["pending_operation"]).resolve() == path.resolve():
                return _advance(path, _read_receipt(path), factory)
            raise HarnessError("Another workflow operation is pending; resume it without creating new chats")
        if path.exists():
            return _advance(path, _read_receipt(path), factory)
        if digest(project) != reviewed["project_sha256"] or digest(state) != reviewed["state_sha256"]:
            raise HarnessError("Project/workflow state drifted after review; do not overwrite it")
        _verify_source(reviewed)
        with factory(reviewed["operation_id"] + "_start") as server:
            identity, settings, _ = sessions.prepare(server, reviewed["source_thread_id"], root)
            if identity != reviewed["project_id"] or settings != reviewed["settings"]:
                raise HarnessError("Actual caller project/settings changed after workflow review")
            current_roles = _linked_receipts(server, root, identity, _bindings(server, root, identity, reviewed["existing_roles"]))
            _bindings(server, root, identity, reviewed["unrelated"])
            if current_roles != reviewed["existing_roles"]:
                raise HarnessError("Connected worker scope changed after plan review; checkpoint and prepare a new exact plan before creation")
            _checkpoints(server, root, identity, reviewed["old_roles"], reviewed["source_thread_id"])
            _archive_guard(server, root, identity, reviewed["old_roles"])
        value = {**reviewed, "phase": "metadata", "authority_reference": authority,
                 "actions": [], "target_receipts": [], "observations": {}}
        for row in reviewed["new_roles"]:
            receipt = {"schema_version": 1, "originator": row["originator"], "source_thread_id": reviewed["source_thread_id"],
                       "target": str(root), "project_id": reviewed["project_id"], "settings": reviewed["settings"],
                       "title": row["role"], "role": row["role"], "parent_thread_id": None,
                       "source_readiness": reviewed["source_readiness"], "phase": "prepared",
                       "authority_reference": authority, "authority_independently_verified": False}
            target_path = contained(root, f".oasis/local/sessions/{row['originator']}/receipt.json")
            write_json(target_path, receipt)
            value["target_receipts"].append(str(target_path))
        write_json(path, value)
        state["pending_operation"] = str(path)
        write_json(_local(root, "state.json"), state)
        return _advance(path, value, factory)


def _metadata(path, value, factory):
    for target_path in value["target_receipts"]:
        receipt = read_json(target_path)
        if receipt["phase"] == "ready":
            continue
        if not receipt.get("thread_id") and receipt["phase"] != "prepared":
            found = sessions.inspect(target_path, factory)
            if not found.get("thread_id"):
                raise HarnessError("Target creation outcome is uncertain; retain the operation and inspect native identity without retry")
            receipt["thread_id"] = found["thread_id"]
            write_json(target_path, receipt)
        sessions.create_metadata(target_path, receipt, factory)
    if value["actions"]:
        return
    for row, target_path in zip(value["new_roles"], value["target_receipts"]):
        receipt = read_json(target_path)
        value["actions"].append(_action("assign", value["operation_id"], receipt["thread_id"],
                                       role=row["role"], prompt=row["prompt"], ack=row["ack"]))
    for row in value["old_roles"]:
        value["actions"].append(_action("archive", value["operation_id"], row["thread_id"], role=row["role"]))
    value["phase"] = "standby"
    write_json(path, value)


def _new_bindings(value):
    if value["same_mode"]:
        return value["existing_roles"]
    return [{"role": action["role"], "thread_id": action["thread_id"], "parent_thread_id": None,
             "first_user_message_sha256": _text_hash(action["prompt"]), "operation_id": value["operation_id"]}
            for action in value["actions"] if action["kind"] == "assign"]


def _observe_assignment(server, action, value):
    thread = _thread(server, action["thread_id"], value["target"], value["project_id"])
    actual_settings = sessions.inherited_settings(sessions.latest_settings(thread["path"]))
    if actual_settings != value["settings"]:
        raise HarnessError("New role settings drifted; preserve them and reconcile before archiving any predecessor")
    first = _first_user(thread)
    if not first:
        return False
    turn, _, prompt = first
    if prompt != action["prompt"]:
        raise HarnessError("New role received a different first message; do not overwrite or replay the role assignment")
    if turn.get("status") != "completed" or not _idle(thread):
        return False
    allowed = {"userMessage", "agentMessage", "reasoning"}
    if any(item.get("type") not in allowed for record in thread["turns"] for item in record.get("items", [])):
        raise HarnessError("Initial role standby used tools or other actions; retain predecessors for review")
    messages = [item.get("text") for item in turn.get("items", []) if item.get("type") == "agentMessage"]
    if messages != [action["ack"]] or len(thread["turns"]) != 1:
        raise HarnessError("Native first-turn standby differs from the exact waiting acknowledgement")
    action.update(observed=True, evidence={"turn_id": turn.get("id"), "first_user_message_sha256": _text_hash(prompt),
                                          "ack_sha256": _text_hash(action["ack"]), "tool_free": True})
    return True


def _finalize(path, value):
    root, project = _root(value["target"])
    state = _state(root)
    if state.get("pending_operation") not in (str(path), None):
        raise HarnessError("Another workflow writer owns state; retain both operations")
    mode = effective_mode(project)
    if mode not in (value["selected_mode_before"], value["mode"]):
        raise HarnessError("Another explicit mode selection changed during transition; preserve it for owner reconciliation")
    value["phase"] = "committing"
    write_json(path, value)
    if mode != value["mode"] or "mode" not in project["extensions"].get("workflow", {}):
        project["extensions"].setdefault("workflow", {})["mode"] = value["mode"]
        write_json(contained(root, ".oasis/project.json"), project)
    roles = _new_bindings(value)
    primary = next(row["thread_id"] for row in roles if row["role"] == value["primary_role"])
    if value["operation_id"] not in state["history"]:
        state["generation"] += 0 if value["same_mode"] else 1
        state["history"].append(value["operation_id"])
    state.update(mode=value["mode"], project_id=value["project_id"], roles=roles, primary_thread_id=primary,
                 unrelated=value["unrelated"],
                 pending_operation=str(path) if value.get("follow_on_task") else None)
    write_json(_local(root, "state.json"), state)
    if value.get("follow_on_task") and not any(action["kind"] == "task" for action in value["actions"]):
        marker = f"[OASIS_WORKFLOW_TASK {value['operation_id']}]"
        value["actions"].append(_action("task", value["operation_id"], primary,
                                       prompt=marker + "\n" + value["follow_on_task"]))
    value.update(phase="task_pending" if value.get("follow_on_task") else "complete", primary_thread_id=primary)
    write_json(path, value)


def _observe_task(server, action, value):
    thread = _thread(server, action["thread_id"], value["target"], value["project_id"])
    matches = [(turn, item) for turn in thread.get("turns", []) for item in turn.get("items", [])
               if item.get("type") == "userMessage" and _user_text(item) == action["prompt"]]
    if len(matches) > 1:
        raise HarnessError("Follow-on task appears more than once; retain duplicate-delivery evidence")
    if not matches:
        return False
    action.update(observed=True, evidence={"turn_id": matches[0][0].get("id"), "message_sha256": _text_hash(action["prompt"])})
    return True


def _result(path, value, actions):
    return {"phase": value["phase"], "mode": value["mode"], "receipt": str(path),
            "primary_thread_id": value.get("primary_thread_id"), "next_actions": actions,
            "authority_independently_verified": False,
            "navigation": ({"thread_id": value["primary_thread_id"],
                            "oasis_thread_id": next((row["thread_id"] for row in _new_bindings(value) if row["role"] == "Oasis"), None)}
                           if value.get("primary_thread_id") else None)}


def _completed_evidence(server, value):
    state = _state(Path(value["target"]))
    if value["operation_id"] not in state["history"]:
        raise HarnessError("A local completed marker has no committed workflow state; reconcile native evidence")
    for action in value["actions"]:
        if action["kind"] != "assign":
            continue
        thread = _thread(server, action["thread_id"], value["target"], value["project_id"])
        first = _first_user(thread)
        if not first or first[2] != action["prompt"] or first[0].get("status") != "completed":
            raise HarnessError("Completed operation has no matching native first role turn")
        items = first[0].get("items", [])
        if (any(item.get("type") not in {"userMessage", "agentMessage", "reasoning"} for item in items)
                or [item.get("text") for item in items if item.get("type") == "agentMessage"] != [action["ack"]]):
            raise HarnessError("Completed operation has no verified native initial standby")
    active = _listing(server, value["target"], archived=False)
    archived = _listing(server, value["target"], archived=True)
    for row in value["old_roles"]:
        if row["thread_id"] in active or row["thread_id"] not in archived:
            raise HarnessError("Completed operation's predecessor archive is no longer supported by native evidence")
        verify_binding(server, row, value["target"], value["project_id"])
    for action in value["actions"]:
        if action["kind"] == "task" and not _observe_task(server, action, value):
            raise HarnessError("Completed operation has no native follow-on task delivery evidence")


def _pending(action):
    if action["attempt"] == "started":
        return {**action, "outcome": "uncertain", "retry_allowed": False,
                "instruction": "Inspect native evidence; do not replay this attempted action"}
    return {**action, "outcome": "not_started", "retry_allowed": False,
            "instruction": "Record --begin-action for this exact ID, then use the authorized supported app tool once"}


def _advance(path, value, factory, *, create=True):
    if value["phase"] == "complete":
        with factory(value["operation_id"] + "_completed_inspect") as server:
            _completed_evidence(server, value)
        return _result(path, value, [])
    state = _state(Path(value["target"]))
    pending = state.get("pending_operation")
    if pending != str(path):
        committed_here = (pending is None and value["phase"] in ("committing", "task_pending")
                          and state["history"] and state["history"][-1] == value["operation_id"]
                          and state["mode"] == value["mode"] and state["roles"] == _new_bindings(value))
        orphan_before_claim = (pending is None and value["phase"] == "metadata"
                               and digest(state) == value["state_sha256"])
        if orphan_before_claim and create:
            state["pending_operation"] = str(path)
            write_json(_local(Path(value["target"]), "state.json"), state)
        elif orphan_before_claim:
            return _result(path, value, [{"kind": "state_claim", "instruction": "Resume this retained receipt under the owner's scope to recover the interrupted local operation claim"}])
        elif not committed_here:
            raise HarnessError("Another workflow operation owns current state; no metadata, message or archive action may proceed")
    if value["phase"] not in ("committing", "task_pending"):
        _verify_source(value)
    if value["phase"] == "metadata":
        if not create:
            return _result(path, value, [{"kind": "metadata", "instruction": "Resume the same retained receipt to reconcile/create metadata only"}])
        _metadata(path, value, factory)
    if value["phase"] not in ("committing", "task_pending"):
        _verify_source(value)
    with factory(value["operation_id"] + "_inspect") as server:
        if value["phase"] == "task_pending":
            action = next(row for row in value["actions"] if row["kind"] == "task")
            if not _observe_task(server, action, value):
                write_json(path, value)
                return _result(path, value, [_pending(action)])
            state = _state(Path(value["target"]))
            if state.get("pending_operation") not in (str(path), None):
                raise HarnessError("Pending task belongs to another operation; preserve current workflow state")
            state["pending_operation"] = None
            write_json(_local(Path(value["target"]), "state.json"), state)
            value["phase"] = "complete"
            write_json(path, value)
            return _result(path, value, [])
        waiting = []
        for action in value["actions"]:
            if action["kind"] == "assign" and not _observe_assignment(server, action, value):
                waiting.append(_pending(action))
        write_json(path, value)
        if waiting:
            return _result(path, value, waiting)
        active = _listing(server, value["target"], archived=False)
        archived = _listing(server, value["target"], archived=True)
        if value["old_roles"]:
            current_old = _linked_receipts(server, Path(value["target"]), value["project_id"], value["old_roles"])
            planned_ids = {row["thread_id"] for row in value["old_roles"]}
            if any(row["thread_id"] not in planned_ids for row in current_old):
                raise HarnessError("A new connected worker changed the reviewed archive scope; preserve all chats and reconcile the retained operation")
        archives = [row for row in value["actions"] if row["kind"] == "archive"]
        for action in archives:
            if action["thread_id"] in archived and action["thread_id"] not in active:
                _thread(server, action["thread_id"], value["target"], value["project_id"], turns=False)
                action.update(observed=True, evidence={"archived_list": True})
            elif action["thread_id"] not in active:
                raise HarnessError("Predecessor is neither active nor provably archived; outcome remains uncertain")
            elif action.get("observed"):
                raise HarnessError("An archived predecessor was reactivated during transition; preserve it for reconciliation")
        remaining = [row for row in archives if not row["observed"]]
        if remaining:
            value["phase"] = "archive"
            descendants = _archive_guard(server, value["target"], value["project_id"], value["old_roles"])
            ready = []
            for action in remaining:
                thread = _thread(server, action["thread_id"], value["target"], value["project_id"])
                # The authorized caller may still be finishing its own handover
                # turn. Other active writers must reach their saved checkpoint.
                if not _idle(thread) and action["thread_id"] != value["source_thread_id"]:
                    continue
                if not descendants[action["thread_id"]]:
                    ready.append(_pending(action))
            write_json(path, value)
            if not ready:
                return _result(path, value, [{"kind": "checkpoint", "instruction": "Wait for connected writers to reach a saved checkpoint; preserve unfinished work"}])
            return _result(path, value, ready)
    _finalize(path, value)
    return _advance(path, value, factory, create=False) if value["phase"] == "task_pending" else _result(path, value, [])


def inspect(path, factory=sessions.AppServer):
    value = _read_receipt(path)
    with operation_lock(contained(value["target"], ".oasis/local/operations.lock")):
        return _advance(Path(path).resolve(), value, factory, create=False)


def resume(path, authority, factory=sessions.AppServer, *, begin_action=None):
    if not authority:
        raise HarnessError("Resume only under the actual owner's existing workflow request")
    value = _read_receipt(path)
    with operation_lock(contained(value["target"], ".oasis/local/operations.lock")):
        result = _advance(Path(path).resolve(), value, factory)
        if not begin_action:
            return result
        action = next((row for row in result["next_actions"] if row.get("id") == begin_action), None)
        if not action or action["attempt"] != "not_started" or action.get("observed"):
            raise HarnessError("Action is not currently eligible, or its outcome is already uncertain; never replay it")
        current = read_json(path)
        entry = next(row for row in current["actions"] if row["id"] == begin_action)
        entry["attempt"] = "started"
        entry["attempt_authority_reference"] = authority
        write_json(path, current)
        return {**result, "begun_action": {**action, "attempt": "started"},
                "instruction": "Use this exact supported native action once, then inspect; recording an attempt proves no delivery"}


def register(subparsers):
    parser = subparsers.add_parser("workflow", help="Prepare/reconcile persistent project modes; native messages/archive use authorized app tools")
    commands = parser.add_subparsers(dest="workflow_command", required=True)
    p = commands.add_parser("status")
    p.add_argument("--target", required=True)
    p.set_defaults(func=lambda args: status(args.target))
    p = commands.add_parser("plan")
    p.add_argument("--target", required=True)
    p.add_argument("--mode", choices=tuple(MODES))
    p.add_argument("--source-thread-id", default=os.environ.get("CODEX_THREAD_ID"))
    p.add_argument("--lane", choices=("main", "test"))
    p.add_argument("--context-file")
    p.add_argument("--bindings-file")
    p.add_argument("--task-file")
    p.add_argument("--language", choices=tuple(ACKS), default="ko")
    p.add_argument("--output", help="Retain a new reviewed plan under .oasis/local; refuses an existing destination")
    def command(args):
        if args.output and Path(args.output).exists():
            raise HarnessError("Workflow plan output already exists; preserve it and select a new filename")
        if args.output and not Path(args.output).resolve().is_relative_to(contained(args.target, ".oasis/local")):
            raise HarnessError("Retain the plan under the target's .oasis/local directory so it does not change source checkpoint bytes")
        value = plan(args.target, args.mode, args.source_thread_id, lane=args.lane,
                     context=read_json(args.context_file) if args.context_file else None,
                     bindings=read_json(args.bindings_file) if args.bindings_file else None,
                     task=Path(args.task_file).read_text(encoding="utf-8") if args.task_file else None,
                     language=args.language)
        if args.output:
            write_json(args.output, value)
        return value
    p.set_defaults(func=command)
    p = commands.add_parser("start")
    p.add_argument("plan")
    p.add_argument("--authority", required=True)
    p.set_defaults(func=lambda args: start(args.plan, args.authority))
    p = commands.add_parser("inspect")
    p.add_argument("receipt")
    p.set_defaults(func=lambda args: inspect(args.receipt))
    p = commands.add_parser("resume")
    p.add_argument("receipt")
    p.add_argument("--authority", required=True)
    p.add_argument("--begin-action")
    p.set_defaults(func=lambda args: resume(args.receipt, args.authority, begin_action=args.begin_action))
