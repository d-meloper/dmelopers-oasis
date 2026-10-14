"""Persistent project modes, Camel tasks and scoped one-shot native notices."""
from __future__ import annotations

import copy
import contextlib
import functools
import json
import math
import os
from pathlib import Path
import re
import time
import uuid

from . import sessions
from .common import HarnessError, atomic_write, contained, digest, operation_lock, read_json, write_json

MODES = {"pioneer": ("Pioneer",), "oasis": ("Oasis", "Cameleer")}
ROLE_PARENT = {"Pioneer": None, "Oasis": None, "Cameleer": None,
               "Developer": "Pioneer", "Camel": "Cameleer"}
TERMINAL = {"completed", "failed", "cancelled", "archived", "collected"}
COMPLETION_REMINDER = ("Before reporting completion, review this task's reusable experience once in the relevant existing skill reference: "
                       "consolidate useful new lessons, duplicates and demonstrably stale advice within the permitted edit scope; "
                       "respect read-only work and make no edit when there is nothing to change.")


def _completion_prompt(text):
    return text + "\n\n" + COMPLETION_REMINDER


@contextlib.contextmanager
def _open(factory, root, originator, *, channel=None):
    """Share production connections without changing injected factory contracts."""
    scope = sessions.command_scope(root, channel=channel or originator) if factory is sessions.command_server else contextlib.nullcontext()
    with scope, factory(originator) as server:
        yield server


def _task_channel(row):
    receipt = read_json(row["session_receipt"])
    return sessions.require_text(receipt.get("originator"), "Session originator")


def _arm_notifications(function):
    """Production commands leave observation to I/O, never a waiting model."""
    @functools.wraps(function)
    def command(*args, **kwargs):
        with sessions.deadline_scope(timeout=30):
            value = function(*args, **kwargs)
        if kwargs.get("factory", sessions.command_server) is sessions.command_server:
            from . import notifications
            try:
                root = Path(args[0] if args else kwargs["target"]).resolve()
                runtime = notifications.ensure_running(root) if _notification_pending(root, _tasks(root)) else notifications.status(root)
            except (HarnessError, OSError, ValueError) as exc:
                runtime = {"state": "needs_resume", "error": str(exc),
                           "instruction": "Preserve the accepted operation; use its existing resume command."}
            if isinstance(value, dict):
                value["notification_runtime"] = runtime
        return value
    return command


def effective_mode(project):
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
    from .installation import target_root
    root = target_root(target)
    project = read_json(contained(root, ".oasis/project.json"))
    if not isinstance(project, dict):
        raise HarnessError("Project configuration must be an object")
    effective_mode(project)
    return root, project


def _local(root, suffix):
    return contained(root, ".oasis/local/workflows/" + suffix)


def _state(root):
    path = _local(root, "state.json")
    if not path.exists():
        return {"schema_version": 1, "target": str(root), "generation": 0, "mode": None,
                "project_id": None, "roles": [], "history": [], "pending_operation": None}
    value = read_json(path)
    if (not isinstance(value, dict) or value.get("schema_version") != 1
            or not isinstance(value.get("target"), str)
            or sessions.canonical_root(value["target"]) != sessions.canonical_root(root)
            or not isinstance(value.get("roles"), list) or not isinstance(value.get("history"), list)
            or any(not isinstance(row, dict) for row in value.get("roles", []))):
        raise HarnessError("Invalid workflow state or target root")
    if (isinstance(value.get("generation"), bool) or not isinstance(value.get("generation"), int)
            or value["generation"] < 0 or value.get("mode") not in (None, *MODES)
            or not isinstance(value.get("unrelated", []), list)):
        raise HarnessError("Invalid workflow generation, mode or independent bindings")
    if any(not isinstance(row, dict) or not isinstance(row.get("thread_id"), str)
           for row in value.get("unrelated", [])):
        raise HarnessError("Independent workflow bindings must retain actual thread IDs")
    return value


def _basis(state, project):
    return {"generation": state["generation"], "mode": state["mode"], "project_id": state["project_id"],
            "roles_sha256": digest(state["roles"]), "selected_mode": effective_mode(project)}


def _binding(root, project_id):
    return {"target": str(root), "project_id": project_id}


def status(target):
    root, project = _root(target)
    value = _state(root)
    return {"selected_mode": effective_mode(project), "initialized_mode": value["mode"],
            "initialization_required": value["mode"] is None,
            "transition_required": value["mode"] is not None and effective_mode(project) != value["mode"],
            "pending_operation": value.get("pending_operation"), "roles": value["roles"]}


def _thread(server, identity, root, project_id, *, turns=False):
    sessions.require_text(identity, "Thread ID")
    thread = server.call("thread/read", {"threadId": identity, "includeTurns": turns})["thread"]
    sessions.check_thread_binding(thread, identity, _binding(root, project_id))
    return thread


def verify_binding(server, binding, root, project_id):
    if not isinstance(binding, dict) or not isinstance(binding.get("role"), str) or not binding["role"]:
        raise HarnessError("Workflow binding requires role text")
    return _thread(server, binding.get("thread_id"), root, project_id)


def _listing(server, root, *, archived):
    return {row["id"]: row for row in server.pages("thread/list", {
        "archived": archived, "cwd": str(root), "sourceKinds": sessions.SOURCES, "limit": 100})
        if sessions.canonical_root(row.get("cwd", "")) == sessions.canonical_root(root)}


def _bindings(server, root, identity, bindings):
    result = {}
    if not isinstance(bindings, list):
        raise HarnessError("Workflow bindings must be a list")
    for row in bindings:
        verify_binding(server, row, root, identity)
        key = row["thread_id"]
        if key in result and result[key] != row:
            raise HarnessError("Conflicting bindings for one thread ID")
        result[key] = copy.deepcopy(row)
    for role in {role for roles in MODES.values() for role in roles}:
        if sum(row.get("role") == role for row in result.values()) > 1:
            raise HarnessError(f"More than one {role} binding; preserve actual IDs and reconcile the intended role")
    return list(result.values())


def bound_pioneer(target, source_id, server=None):
    root, _ = _root(target)
    state = _state(root)
    binding = next((row for row in state["roles"] if row.get("role") == "Pioneer" and row.get("thread_id") == source_id), None)
    if not binding:
        raise HarnessError("No Pioneer binding for this thread ID")
    if server is not None:
        verify_binding(server, binding, root, state["project_id"])
    return source_id


def _prompt(role, context, language):
    skill = {"Pioneer": "oasis-pioneer", "Oasis": "oasis-maintenance", "Cameleer": "oasis-cameleer"}[role]
    text = f"You are the {role} for this project. Apply ${skill}. Preserve the saved unfinished work and wait for the next user request."
    if context:
        text += "\n\nProject context:\n" + (context if isinstance(context, str) else json.dumps(context, ensure_ascii=False, indent=2))
    return _completion_prompt(text)


def _role_skill(root, role):
    name = {"Pioneer": "oasis-pioneer", "Oasis": "oasis-maintenance", "Cameleer": "oasis-cameleer", "Camel": "oasis-camel"}.get(role)
    if not name:
        return None
    path = contained(root, f".agents/skills/{name}/SKILL.md")
    return {"name": name, "path": str(path)} if path.is_file() else None


def _receipt_path(value):
    operation = value.get("operation_id", "")
    if not isinstance(operation, str) or not re.fullmatch(r"oasis_workflow_[a-zA-Z0-9_]+", operation):
        raise HarnessError("Invalid workflow operation ID")
    return _local(Path(value["target"]), f"operations/{operation}/receipt.json")


def _read_receipt(path):
    value = read_json(path)
    if not isinstance(value, dict) or value.get("schema_version") != 1 or Path(path).resolve() != _receipt_path(value).resolve():
        raise HarnessError("Workflow receipt must remain in its bound project operation path")
    return value


def plan(target, mode=None, source_id=None, *, lane=None, context=None, bindings=None,
         task=None, language="ko", factory=sessions.command_server):
    root, project = _root(target)
    sessions.require_text(source_id, "Source thread ID")
    mode = mode or effective_mode(project)
    if not isinstance(mode, str) or mode not in MODES:
        raise HarnessError("Select pioneer or oasis")
    if task is not None:
        sessions.require_text(task, "Follow-on task")
    state = _state(root)
    if state.get("pending_operation"):
        return _read_receipt(state["pending_operation"])
    operation = "oasis_workflow_" + uuid.uuid4().hex
    with _open(factory, root, operation + "_plan") as server:
        identity, settings, _ = sessions.prepare(server, source_id, root)
        owned = _bindings(server, root, identity, state["roles"] + (bindings or []))
    mode_roles = {role for roles in MODES.values() for role in roles}
    independent = [row for row in owned if row.get("role") not in mode_roles]
    owned = [row for row in owned if row.get("role") in mode_roles]
    unrelated = {row["thread_id"]: row for row in state.get("unrelated", []) + independent}
    same = all(any(row.get("role") == role for row in owned) for role in MODES[mode])
    same = same and not any(row.get("role") in MODES["oasis" if mode == "pioneer" else "pioneer"] for row in owned)
    return {"schema_version": 1, "operation_id": operation, "target": str(root), "project_id": identity,
            "source_thread_id": source_id, "settings": settings, "mode": mode,
            "selected_mode_before": effective_mode(project), "primary_role": "Pioneer" if mode == "pioneer" else "Cameleer",
            "language": language, "context": context, "follow_on_task": _completion_prompt(task) if task is not None else None, "existing_roles": owned,
            "old_roles": [] if same else owned, "unrelated": list(unrelated.values()), "basis": _basis(state, project),
            "new_roles": [] if same else [{"role": role, "originator": operation + "_" + role.lower(),
                                           "prompt": _prompt(role, context, language)} for role in MODES[mode]],
            "same_mode": same}


def start(reviewed, authority=None, factory=sessions.command_server):
    value = read_json(reviewed) if isinstance(reviewed, (str, Path)) else copy.deepcopy(reviewed)
    path = _receipt_path(value)
    root, project = _root(value["target"])
    with operation_lock(contained(root, ".oasis/local/operations.lock")):
        state = _state(root)
        if state.get("pending_operation") and Path(state["pending_operation"]).resolve() != path.resolve():
            raise HarnessError("Another mode operation is pending; resume that operation")
        if path.exists():
            value = _read_receipt(path)
        else:
            if value.get("basis") is not None and value["basis"] != _basis(state, read_json(contained(root, ".oasis/project.json"))):
                raise HarnessError("Mode plan is stale; preserve current roles and prepare a fresh plan")
            value.update(phase="metadata", actions=[], target_receipts=[])
            write_json(path, value)
            state["pending_operation"] = str(path)
            write_json(_local(root, "state.json"), state)
        return _advance(path, value, factory)


def _lifecycle_once(path, thread_id, server, root, *, restore=False, scoped=(), expected_binding=None, native=None):
    method = "thread/unarchive" if restore else "thread/archive"
    value = read_json(path) if Path(path).exists() else {"thread_id": thread_id, "state": "not_started", "method": method}
    if value.get("thread_id") != thread_id or value.get("method") != method:
        raise HarnessError("Lifecycle action path belongs to another operation")
    if value["state"] == "accepted":
        return value
    if expected_binding is not None:
        native = native if native is not None else server.call("thread/read", {"threadId": thread_id, "includeTurns": False})["thread"]
        sessions.check_thread_binding(native, thread_id, expected_binding)
    if value["state"] in ("started", "uncertain"):
        if thread_id in _listing(server, root, archived=not restore):
            value["state"] = "accepted"
            write_json(path, value)
        return value
    if not restore:
        descendants = list(server.pages("thread/list", {"ancestorThreadId": thread_id, "archived": False,
                                                         "sourceKinds": sessions.SOURCES, "limit": 100}))
        if any(row.get("id") not in scoped for row in descendants):
            raise HarnessError("Native archive would include an unrelated descendant; preserve that chat")
    value["state"] = "started"
    write_json(path, value)
    try:
        server.call(method, {"threadId": thread_id})
        # A successful archive can omit descendants. Read back this exact ID;
        # each scoped descendant has its own lifecycle action.
        value["state"] = "accepted" if thread_id in _listing(server, root, archived=not restore) else "uncertain"
    except sessions.NativeError as exc:
        value.update(state="rejected", error=str(exc))
        write_json(path, value)
        raise
    except Exception as exc:
        value.update(state="uncertain", error=str(exc))
        write_json(path, value)
        raise
    write_json(path, value)
    return value


def _result(path, value):
    return {"phase": value["phase"], "mode": value["mode"], "receipt": str(path),
            "primary_thread_id": value.get("primary_thread_id"), "next_actions": [],
            "unfinished_tasks": value.get("unfinished_tasks", []),
            "navigation": {"thread_id": value["primary_thread_id"]} if value.get("primary_thread_id") else None}


def _advance(path, value, factory):
    root, _ = _root(value["target"])
    if value["phase"] == "complete":
        return _result(path, value)
    current_state = _state(root)
    if current_state.get("pending_operation") and Path(current_state["pending_operation"]).resolve() != Path(path).resolve():
        raise HarnessError("Another mode operation owns the current state; preserve its progress")
    if (value["operation_id"] in current_state["history"] and
            (current_state["mode"] != value["mode"] or current_state.get("primary_thread_id") != value.get("primary_thread_id"))):
        raise HarnessError("A later mode operation changed the roles; preserve its state")
    if value.get("basis") and value["operation_id"] not in current_state["history"] and not current_state.get("pending_operation"):
        if value["basis"] != _basis(current_state, read_json(contained(root, ".oasis/project.json"))):
            raise HarnessError("Mode operation state changed; preserve other writers before recovery")
    scoped_roles = {row["thread_id"] for row in value["old_roles"]}
    unfinished = [row for row in unfinished_tasks(root) if
                  not row.get("cameleer_thread_id") or row["cameleer_thread_id"] in scoped_roles] if scoped_roles else []
    if unfinished:
        value.update(phase="waiting_for_tasks", unfinished_tasks=unfinished)
        write_json(path, value)
        return _result(path, value)
    value.pop("unfinished_tasks", None)
    if not value["target_receipts"]:
        for row in value["new_roles"]:
            target_path = contained(root, f".oasis/local/sessions/{row['originator']}/receipt.json")
            receipt = {"schema_version": 1, "originator": row["originator"], "source_thread_id": value["source_thread_id"],
                       "target": str(root), "project_id": value["project_id"], "settings": value["settings"],
                       "title": row["role"], "role": row["role"], "parent_thread_id": None, "phase": "prepared"}
            if not target_path.exists():
                write_json(target_path, receipt)
            value["target_receipts"].append(str(target_path))
        write_json(path, value)
    new_roles = []
    for row, target_path in zip(value["new_roles"], value["target_receipts"]):
        receipt = read_json(target_path)
        if not receipt.get("thread_id") and receipt["phase"] not in sessions.CREATION_RETRYABLE:
            found = sessions.inspect(target_path, factory)
            if not found.get("thread_id"):
                value["phase"] = "creation_uncertain"
                write_json(path, value)
                return _result(path, value)
            receipt["thread_id"] = found["thread_id"]
        sessions.create_metadata(target_path, receipt, factory)
        new_roles.append({"role": row["role"], "thread_id": receipt["thread_id"], "parent_thread_id": None})
        with _open(factory, root, value["operation_id"], channel=row["originator"]) as server:
            delivery = sessions.send_once(path.parent / (row["role"] + "-assign.json"), receipt["thread_id"], row["prompt"], server,
                                          skill=_role_skill(root, row["role"]), expected_binding=_binding(root, value["project_id"]))
        if delivery["state"] != "accepted":
            value["phase"] = "assignment_uncertain"
            write_json(path, value)
            return _result(path, value)
    roles = value["existing_roles"] if value["same_mode"] else new_roles
    primary = next(row["thread_id"] for row in roles if row.get("role") == value["primary_role"])
    value["primary_thread_id"] = primary
    scoped = {row["thread_id"] for row in value["old_roles"]}
    with _open(factory, root, value["operation_id"]) as server:
        for row in value["old_roles"]:
            native = _thread(server, row["thread_id"], root, value["project_id"])
            if (native.get("status") or {}).get("type") not in (None, "idle", "notLoaded") and row["thread_id"] != value["source_thread_id"]:
                value["phase"] = "waiting_for_task"
                write_json(path, value)
                return _result(path, value)
            lifecycle = _lifecycle_once(path.parent / (digest(row["thread_id"]) + "-archive.json"),
                                        row["thread_id"], server, root, scoped=scoped,
                                        expected_binding=_binding(root, value["project_id"]), native=native)
            if lifecycle["state"] != "accepted":
                value["phase"] = "archive_uncertain"
                write_json(path, value)
                return _result(path, value)
    current = read_json(contained(root, ".oasis/project.json"))
    if effective_mode(current) not in (value["selected_mode_before"], value["mode"]):
        raise HarnessError("Another writer changed the selected mode; preserve its configuration")
    current.setdefault("extensions", {}).setdefault("workflow", {})["mode"] = value["mode"]
    write_json(contained(root, ".oasis/project.json"), current)
    state = _state(root)
    if value["operation_id"] not in state["history"]:
        state["generation"] += 0 if value["same_mode"] else 1
        state["history"].append(value["operation_id"])
    state.update(mode=value["mode"], project_id=value["project_id"], roles=roles, primary_thread_id=primary,
                 unrelated=value["unrelated"], pending_operation=str(path))
    write_json(_local(root, "state.json"), state)
    if value.get("follow_on_task"):
        with _open(factory, root, value["operation_id"]) as server:
            delivery = sessions.send_once(path.parent / "task.json", primary, value["follow_on_task"], server,
                                          expected_binding=_binding(root, value["project_id"]))
        if delivery["state"] != "accepted":
            value["phase"] = "task_uncertain"
            write_json(path, value)
            return _result(path, value)
    state["pending_operation"] = None
    write_json(_local(root, "state.json"), state)
    value["phase"] = "complete"
    write_json(path, value)
    return _result(path, value)


def inspect(path, factory=sessions.command_server):
    """Read retained local state; inspection never sends a role prompt."""
    value = _read_receipt(path)
    return _result(Path(path).resolve(), value)


def resume(path, authority=None, factory=sessions.command_server, *, begin_action=None):
    value = _read_receipt(path)
    with operation_lock(contained(value["target"], ".oasis/local/operations.lock")):
        return _advance(Path(path).resolve(), value, factory)


def _task_path(root):
    return contained(root, ".oasis/local/tasks/state.json")


def _tasks(root):
    path = _task_path(root)
    if not path.exists():
        return {"schema_version": 1, "tasks": [], "dependencies": []}
    value = read_json(path)
    if (not isinstance(value, dict) or value.get("schema_version") != 1
            or not isinstance(value.get("tasks"), list) or not isinstance(value.get("dependencies"), list)
            or any(not isinstance(row, dict) or ("phase" in row and not isinstance(row["phase"], str))
                   for row in value.get("tasks", []) + value.get("dependencies", []))):
        raise HarnessError("Invalid task state; preserve it for recovery")
    identities = set()
    for kind in ("tasks", "dependencies"):
        for row in value[kind]:
            for key in ("id", "camel_thread_id", "cameleer_thread_id", "producer_thread_id", "consumer_thread_id", "goal", "condition"):
                if row.get(key) is not None:
                    sessions.require_text(row[key], f"Task/dependency {key}")
            if row.get("id"):
                if row["id"] in identities:
                    raise HarnessError("Duplicate task/dependency ID; preserve state")
                identities.add(row["id"])
            if "cycle" in row and (isinstance(row["cycle"], bool) or not isinstance(row["cycle"], int) or row["cycle"] < 0):
                raise HarnessError("Task cycle must be a nonnegative integer")
            if "history" in row and (not isinstance(row["history"], list) or any(not isinstance(item, dict) for item in row["history"])):
                raise HarnessError("Task history must contain objects")
            if row.get("completion") is not None and not isinstance(row["completion"], dict):
                raise HarnessError("Task completion must be an object")
            if row.get("native_turn") is not None and not isinstance(row["native_turn"], dict):
                raise HarnessError("Task native turn evidence must be an object")
            for key in ("delivery", "unsubmitted_notice"):
                if row.get(key) is not None and not isinstance(row[key], dict):
                    raise HarnessError(f"Task/dependency {key} must be an object")
            missing = row.get("unsubmitted_notice") or {}
            if not isinstance(missing.get("delivery", {}), dict):
                raise HarnessError("Task unsubmitted_notice.delivery must be an object")
            if row.get("producer_turn_id") is not None:
                sessions.require_text(row["producer_turn_id"], "Dependency producer_turn_id")
            for key in ("consumer_binding", "producer_binding"):
                binding = row.get(key)
                if binding is not None and (not isinstance(binding, dict) or not isinstance(binding.get("task_id"), str)
                        or type(binding.get("cycle")) is not int or binding["cycle"] < 0):
                    raise HarnessError(f"Dependency {key} requires task_id and nonnegative cycle")
            assignment = row.get("assignment_binding")
            if assignment is not None and (not isinstance(assignment, dict) or not isinstance(assignment.get("task_id"), str)
                    or type(assignment.get("cycle")) is not int or assignment["cycle"] < 0 or row.get("purpose") != "assignment"):
                raise HarnessError("Dependency assignment_binding requires task_id, nonnegative cycle and assignment purpose")
            continuations = row.get("dependency_continuations", [])
            if not isinstance(continuations, list) or any(not isinstance(item, dict)
                    or not isinstance(item.get("dependency_id"), str) or not isinstance(item.get("delivery"), dict)
                    or not isinstance(item["delivery"].get("turn_id"), str) for item in continuations):
                raise HarnessError("Task dependency_continuations require identified native delivery turns")
            if row.get("completion"):
                completion = row["completion"]
                if completion.get("outcome") not in ("completed", "failed", "cancelled"):
                    raise HarnessError("Invalid task completion outcome")
                for key in ("text", "result_key"):
                    sessions.require_text(completion.get(key), f"Completion {key}")
            if kind == "dependencies" and row.get("phase") == "waiting":
                for key in ("id", "producer_thread_id", "consumer_thread_id", "condition"):
                    sessions.require_text(row.get(key), f"Waiting dependency {key}")
    return value


def unfinished_tasks(target):
    """Read local current and legacy links without contacting or changing chats."""
    root = Path(target).resolve()
    current = _tasks(root)
    known = {row.get("camel_thread_id"): row for row in current["tasks"] if row.get("camel_thread_id")}
    pending = [copy.deepcopy(row) for row in current["tasks"] if row.get("phase") not in TERMINAL]
    for path in contained(root, ".oasis/local/sessions").glob("*/receipt.json"):
        row = read_json(path)
        if not isinstance(row, dict):
            raise HarnessError("Legacy session record must be an object")
        identity = row.get("thread_id")
        if not identity or row.get("role") not in ("Camel", "Calf") or identity in known:
            continue
        if row.get("phase") in TERMINAL:
            known[identity] = row
            continue
        # Ready metadata alone is not evidence of assigned unfinished work.
        if row.get("phase") in ("prepared", "ready") and not any(row.get(key) for key in
                ("handoff_delivered", "task", "goal", "unfinished_work")):
            continue
        known[identity] = row
        pending.append({"camel_thread_id": identity, "role": row["role"], "phase": row.get("phase", "unknown"),
                        "goal": row.get("goal", row.get("title", "Legacy task")), "record": str(path)})
    workflow_path = _local(root, "state.json")
    if workflow_path.exists():
        legacy_state = read_json(workflow_path)
        if not isinstance(legacy_state, dict) or not isinstance(legacy_state.get("roles", []), list):
            raise HarnessError("Legacy workflow state must contain role objects")
        for row in legacy_state.get("roles", []):
            if not isinstance(row, dict):
                raise HarnessError("Legacy workflow role must be an object")
            identity = row.get("thread_id")
            if identity and row.get("role") in ("Camel", "Calf") and identity not in known and row.get("phase") not in TERMINAL:
                known[identity] = row
                pending.append({"camel_thread_id": identity, "role": row["role"], "phase": row.get("phase", "unknown"),
                                "goal": row.get("goal", "Legacy task"), "record": str(workflow_path)})
    markdown = contained(root, ".oasis/state/tasks.md")
    if markdown.exists():
        for line in markdown.read_text(encoding="utf-8").splitlines():
            match = re.search(r"\[[^\]]+\]\(codex://threads/([^)#?]+)[^)]*\)", line)
            if not match or match[1] in known:
                continue
            columns = [part.strip() for part in line.split("|")[1:-1]]
            phase = columns[2].split(";", 1)[0] if len(columns) > 2 else "unknown"
            if phase not in TERMINAL:
                pending.append({"camel_thread_id": match[1], "phase": phase,
                                "goal": columns[1] if len(columns) > 1 else "Existing task", "record": str(markdown)})
    return pending


def _cell(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _render_tasks(root, state):
    lines = ["# Camel tasks", "", "Updated when work or dependency state changes.", "",
             "| Camel chat | Goal | Stage / dependencies | Work / result | Result / checks |",
             "| --- | --- | --- | --- | --- |"]
    for row in state["tasks"]:
        identity = row.get("camel_thread_id")
        chat = f"[{identity}](codex://threads/{identity})" if identity else f"Creation pending ({row.get('id', 'unresolved')})"
        waits = [d["condition"] for d in state["dependencies"] if d.get("consumer_thread_id") == identity
                 and d.get("phase") == "waiting" and _dependency_current(state, d)]
        phase = row.get("phase", "unknown") + ("; waiting for " + ", ".join(waits) if waits else "")
        notice = _notice(root, row) if row.get("completion") else None
        if notice and notice["state"] != "accepted":
            phase += "; completion notice " + notice["state"]
        for dependency in state["dependencies"]:
            if (_dependency_current(state, dependency) and dependency.get("consumer_thread_id") == identity
                    and dependency.get("phase") in ("completed", "failed", "cancelled")):
                notice = _notice(root, dependency, dependency=True)
                if notice["state"] != "accepted":
                    phase += "; dependency notice " + notice["state"]
        location = " / ".join(str(value) for value in (row.get("location"), row.get("result")) if value)
        summary = " / ".join(str(value) for value in (row.get("summary"), row.get("checks")) if value)
        if row.get("phase") in TERMINAL:
            location = str(row.get("result") or "")
        lines.append("| " + " | ".join((chat, _cell(row.get("current_goal", row.get("goal", "Existing task"))), _cell(phase), _cell(location), _cell(summary))) + " |")
    path = contained(root, ".oasis/state/tasks.md")
    block = "<!-- oasis-tasks:start -->\n" + "\n".join(lines) + "\n<!-- oasis-tasks:end -->"
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    begin, end = original.find("<!-- oasis-tasks:start -->"), original.find("<!-- oasis-tasks:end -->")
    if begin >= 0 and end >= begin:
        updated = original[:begin] + block + original[end + len("<!-- oasis-tasks:end -->"):]
    else:
        updated = original.rstrip() + ("\n\n" if original.strip() else "") + block + "\n"
    atomic_write(path, updated)


def _task(state, task_id):
    row = next((row for row in state["tasks"] if row.get("id") == task_id or row.get("camel_thread_id") == task_id), None)
    if row is None:
        raise HarnessError("Unknown task ID or Camel chat ID")
    sessions.require_text(row.get("id"), "Resolved task ID")
    return row


def _notice(root, row, *, dependency=False):
    path = contained(root, f".oasis/local/tasks/dependencies/{row['id']}.json") if dependency else _delivery_path(root, row, "complete")
    delivery = read_json(path) if path.exists() else row.get("delivery", {}) if dependency else row.get("completion", {}).get("delivery", {})
    if not isinstance(delivery, dict):
        raise HarnessError("Completion delivery must be an object")
    state = delivery.get("state", "not_started")
    action = {"command": "workflow dependency-finish", "dependency_id": row["id"]} if dependency else {"command": "workflow complete", "task_id": row["id"]}
    return {"state": state, "receipt": str(path),
            **({"resume": action} if state != "accepted" else {})}


def _cycles(dependencies):
    waiting = [row for row in dependencies if row.get("phase") == "waiting"]
    graph, reverse = {}, {}
    for row in waiting:
        source, destination = row["consumer_thread_id"], row["producer_thread_id"]
        graph.setdefault(source, set()).add(destination)
        graph.setdefault(destination, set())
        reverse.setdefault(destination, set()).add(source)
        reverse.setdefault(source, set())
    visited, order = set(), []
    for node in graph:
        stack = [(node, False)]
        while stack:
            current, returning = stack.pop()
            if returning:
                order.append(current)
            elif current not in visited:
                visited.add(current)
                stack.append((current, True))
                stack.extend((neighbor, False) for neighbor in graph[current] if neighbor not in visited)
    visited, warnings = set(), []
    for node in reversed(order):
        component, stack = set(), [node]
        while stack:
            current = stack.pop()
            if current not in visited:
                visited.add(current)
                component.add(current)
                stack.extend(reverse[current] - visited)
        if len(component) > 1 or component and node in graph[node]:
            links = [row for row in waiting if row["consumer_thread_id"] in component and row["producer_thread_id"] in component]
            warnings.append({"kind": "dependency_cycle", "dependency_ids": [row["id"] for row in links],
                             "conditions": [row["condition"] for row in links], "advisory_only": True})
    return warnings


def task_status(target, task_id=None, *, include_complete=False, summary=False):
    root = Path(target).resolve()
    state = _tasks(root)
    if summary:
        rows = [_task(state, task_id)] if task_id else state["tasks"]
        tasks = []
        for row in rows:
            notice = _notice(root, row) if row.get("completion") else None
            pending_collection = bool(row.get("completion") and row["completion"].get("outcome") == "completed"
                                      and row.get("collected_result_key") != row["completion"].get("result_key"))
            if not (task_id or include_complete or row.get("phase") not in TERMINAL
                    or pending_collection or notice and notice["state"] != "accepted"):
                continue
            entry = {key: copy.deepcopy(row.get(key)) for key in ("id", "camel_thread_id", "cameleer_thread_id", "phase", "location", "result", "checks")}
            entry["goal"] = row.get("current_goal", row.get("goal"))
            if notice:
                entry["completion_notice"] = notice
            if pending_collection:
                entry["collection"] = row.get("phase") if (row.get("native_turn") or {}).get("state") not in (None, "ready") else "awaiting_review"
            if row.get("native_turn"):
                entry["native_turn"] = copy.deepcopy(row["native_turn"])
            tasks.append(entry)
        dependencies = []
        for row in state["dependencies"]:
            if not _dependency_current(state, row):
                if include_complete:
                    dependencies.append({"id": row["id"], "phase": "superseded", "condition": row["condition"]})
                continue
            notice = _notice(root, row, dependency=True) if row.get("phase") in ("completed", "failed", "cancelled") else None
            if include_complete or row.get("phase") == "waiting" or notice and notice["state"] != "accepted":
                entry = {key: copy.deepcopy(row.get(key)) for key in
                         ("id", "producer_thread_id", "consumer_thread_id", "condition", "phase", "result")}
                if notice:
                    entry["terminal_notice"] = notice
                dependencies.append(entry)
        from . import notifications
        return {"tasks": tasks, "dependencies": dependencies,
                "warnings": _cycles([row for row in state["dependencies"] if _dependency_current(state, row)]),
                "notification_runtime": notifications.status(root)}
    if task_id:
        return copy.deepcopy(_task(state, task_id))
    return {"tasks": [row for row in state["tasks"] if include_complete or row.get("phase") not in TERMINAL]}


def _delivery_path(root, row, kind):
    return contained(root, f".oasis/local/tasks/{row['id']}/{row.get('cycle', 0)}-{kind}.json")


def _assign_delivery(root, row, server):
    delivery = sessions.send_once(_delivery_path(root, row, "assign"), row["camel_thread_id"], row["prompt"], server,
                                  planning=row.get("planning", False), skill=_role_skill(root, "Camel"),
                                  expected_binding=_binding(root, _task_project(row)))
    row["phase"] = "assigned" if delivery["state"] == "accepted" else delivery["state"]
    row["assignment_delivery"] = delivery
    return delivery


def _task_project(row):
    return row.get("project_id") or read_json(row["session_receipt"])["project_id"]


def _render_after_failure(root, state, error):
    try:
        _render_tasks(root, state)
    except (HarnessError, OSError, ValueError, KeyError) as refresh:
        error.add_note(f"Task table refresh failed: {refresh}. Preserve the retained action before retrying.")


def _request_match(row, sha, fields, *, hash_field="input_sha256"):
    if row.get(hash_field) is not None:
        if row[hash_field] != sha:
            raise HarnessError("Request ID already belongs to different inputs; preserve the original action")
    elif any(key in row and row[key] != value for key, value in fields.items()):
        raise HarnessError("Legacy request ID has different recorded inputs; preserve the original action")


@_arm_notifications
def assign(target, cameleer_id, goal, *, context=None, location=None, planning=False, title=None,
           request_id=None, factory=sessions.command_server):
    root, _ = _root(target)
    sessions.require_text(cameleer_id, "Cameleer chat ID")
    sessions.require_text(goal, "Task goal")
    if request_id is not None:
        sessions.require_text(request_id, "Request ID")
    if not isinstance(planning, bool):
        raise HarnessError("Planning selection must be a boolean")
    if location is not None:
        sessions.require_text(location, "Assigned work location")
    sha = digest([cameleer_id, goal, context, location, planning, title])
    key = request_id or sha
    with operation_lock(contained(root, ".oasis/local/operations.lock")):
        state = _tasks(root)
        row = next((item for item in state["tasks"] if item.get("request_key") == key), None)
        if row is not None:
            _request_match(row, sha, {"cameleer_thread_id": cameleer_id, "goal": goal,
                                    "location": location or str(root), "planning": planning})
        if row is None:
            identity = uuid.uuid4().hex
            originator = "oasis_session_" + identity
            with _open(factory, root, originator) as server:
                project_id, settings, source = sessions.prepare(server, cameleer_id, root)
                _thread(server, cameleer_id, root, project_id)
                selected_title = title or sessions.title_for("Camel", goal, source, sessions.discover(server, root, project_id))
            prompt = "Apply $oasis-camel to this assigned task. " + goal
            if context:
                prompt += "\n\n" + (context if isinstance(context, str) else json.dumps(context, ensure_ascii=False))
            prompt += "\n\nAssigned work location: " + (location or str(root))
            prompt = _completion_prompt(prompt)
            row = {"id": identity, "request_key": key, "input_sha256": sha, "role": "Camel", "project_id": project_id, "cameleer_thread_id": cameleer_id,
                   "camel_thread_id": None, "goal": goal, "prompt": prompt, "planning": planning,
                   "location": location or str(root), "phase": "creating", "cycle": 0, "history": []}
            receipt = {"schema_version": 1, "originator": originator, "target": str(root), "project_id": project_id,
                       "source_thread_id": cameleer_id, "parent_thread_id": cameleer_id, "role": "Camel",
                       "settings": settings, "title": selected_title, "phase": "prepared"}
            row["session_receipt"] = str(contained(root, f".oasis/local/sessions/{originator}/receipt.json"))
            state["tasks"].append(row)
            write_json(row["session_receipt"], receipt)
            write_json(_task_path(root), state)
        if row["phase"] in TERMINAL:
            return copy.deepcopy(row)
        try:
            receipt = read_json(row["session_receipt"])
            if not receipt.get("thread_id") and receipt["phase"] not in sessions.CREATION_RETRYABLE:
                found = sessions.inspect(row["session_receipt"], factory)
                if not found.get("thread_id"):
                    row["phase"] = "creation_uncertain"
                    write_json(_task_path(root), state)
                    _render_tasks(root, state)
                    return copy.deepcopy(row)
                receipt["thread_id"] = found["thread_id"]
            sessions.create_metadata(row["session_receipt"], receipt, factory)
            row["camel_thread_id"] = receipt["thread_id"]
            write_json(_task_path(root), state)
            with _open(factory, root, "oasis_assign_" + row["id"], channel=_task_channel(row)) as server:
                _assign_delivery(root, row, server)
            row.pop("error", None)
        except Exception as exc:
            row.update(phase="assignment_uncertain", error=str(exc))
            write_json(_task_path(root), state)
            _render_tasks(root, state)
            raise HarnessError(f"Task {row['id']} is retained; recover only this assignment: {exc}") from exc
        write_json(_task_path(root), state)
        _render_tasks(root, state)
        return copy.deepcopy(row)


def register(subparsers):
    parser = subparsers.add_parser("workflow", help="Project modes, actual Camel IDs and terminal notices")
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
    p.add_argument("--language", choices=("ko", "en"), default="ko")
    p.add_argument("--output")
    def command(args):
        value = plan(args.target, args.mode, args.source_thread_id, lane=args.lane,
                     context=read_json(args.context_file) if args.context_file else None,
                     bindings=read_json(args.bindings_file) if args.bindings_file else None,
                     task=Path(args.task_file).read_text(encoding="utf-8") if args.task_file else None, language=args.language)
        if args.output:
            destination = Path(args.output)
            if destination.exists() or not destination.resolve().is_relative_to(contained(args.target, ".oasis/local")):
                raise HarnessError("Choose an unused plan output under the target's .oasis/local directory")
            write_json(destination, value)
        return value
    p.set_defaults(func=command)
    p = commands.add_parser("start")
    p.add_argument("plan")
    p.add_argument("--authority", help="Legacy request reference")
    p.set_defaults(func=lambda args: start(args.plan, args.authority))
    p = commands.add_parser("inspect")
    p.add_argument("receipt")
    p.set_defaults(func=lambda args: inspect(args.receipt))
    p = commands.add_parser("resume")
    p.add_argument("receipt")
    p.add_argument("--authority", help="Legacy request reference")
    p.add_argument("--begin-action", help="Legacy action hint")
    p.set_defaults(func=lambda args: resume(args.receipt, args.authority, begin_action=args.begin_action))
    p = commands.add_parser("assign")
    p.add_argument("--target", required=True)
    p.add_argument("--cameleer-id", default=os.environ.get("CODEX_THREAD_ID"))
    p.add_argument("--goal", required=True)
    p.add_argument("--context-file")
    p.add_argument("--location")
    p.add_argument("--title")
    p.add_argument("--plan", action="store_true")
    p.add_argument("--request-id")
    p.set_defaults(func=lambda args: assign(args.target, args.cameleer_id, args.goal,
        context=Path(args.context_file).read_text(encoding="utf-8") if args.context_file else None,
        location=args.location, planning=args.plan, title=args.title, request_id=args.request_id))
    p = commands.add_parser("tasks")
    p.add_argument("--target", required=True)
    p.add_argument("--task-id")
    p.add_argument("--include-complete", action="store_true")
    p.add_argument("--summary", action="store_true", help="Compact work, pending notices and dependency warnings")
    p.set_defaults(func=lambda args: task_status(args.target, args.task_id, include_complete=args.include_complete, summary=args.summary))
    p = commands.add_parser("complete")
    p.add_argument("--target", required=True)
    p.add_argument("--task-id", required=True)
    p.add_argument("--message-file")
    p.add_argument("--result")
    p.add_argument("--checks")
    p.add_argument("--outcome", choices=("completed", "failed", "cancelled"), default="completed")
    p.set_defaults(func=lambda args: complete(args.target, args.task_id,
        Path(args.message_file).read_text(encoding="utf-8") if args.message_file else None,
        result=args.result, checks=args.checks, outcome=args.outcome))
    p = commands.add_parser("collect")
    p.add_argument("--target", required=True)
    p.add_argument("--task-id", required=True)
    p.add_argument("--result")
    p.add_argument("--checks")
    p.add_argument("--merged-reference")
    p.add_argument("--timeout", type=float, default=30, help="Total connection, RPC, wait and cleanup budget in seconds")
    p.set_defaults(func=lambda args: collect(args.target, args.task_id, result=args.result, checks=args.checks, merged_reference=args.merged_reference, timeout=args.timeout))
    p = commands.add_parser("task-resume")
    p.add_argument("--target", required=True)
    p.add_argument("--task-id", required=True)
    p.add_argument("--message-file")
    choice = p.add_mutually_exclusive_group()
    choice.add_argument("--plan", action="store_true")
    choice.add_argument("--implementation", action="store_true")
    p.add_argument("--request-id")
    p.set_defaults(func=lambda args: resume_task(args.target, args.task_id,
        Path(args.message_file).read_text(encoding="utf-8") if args.message_file else None,
        planning=args.plan, implementation=args.implementation, request_id=args.request_id))
    p = commands.add_parser("dependency-wait")
    p.add_argument("--target", required=True)
    p.add_argument("--producer-id", required=True)
    p.add_argument("--consumer-id", required=True)
    p.add_argument("--condition", required=True)
    p.add_argument("--purpose", choices=("assignment", "partial"), help="Reuse assignment completion, or wait for a distinct partial result/resource")
    p.add_argument("--request-id")
    p.set_defaults(func=lambda args: dependency_wait(args.target, args.producer_id, args.consumer_id, args.condition, request_id=args.request_id, purpose=args.purpose))
    p = commands.add_parser("dependency-finish")
    p.add_argument("--target", required=True)
    p.add_argument("--dependency-id", required=True)
    p.add_argument("--outcome", choices=("completed", "failed", "cancelled"), default="completed")
    p.add_argument("--result")
    p.add_argument("--message-file")
    p.set_defaults(func=lambda args: dependency_finish(args.target, args.dependency_id, outcome=args.outcome, result=args.result,
        message=Path(args.message_file).read_text(encoding="utf-8") if args.message_file else None))


@_arm_notifications
def complete(target, task_id, message=None, *, result=None, checks=None, outcome="completed", factory=sessions.command_server):
    if outcome not in ("completed", "failed", "cancelled"):
        raise HarnessError("Task outcome must be completed, failed or cancelled")
    root, _ = _root(target)
    with operation_lock(contained(root, ".oasis/local/operations.lock")):
        state = _tasks(root)
        row = _task(state, task_id)
        if not row.get("camel_thread_id"):
            raise HarnessError("Task has no resolved Camel chat ID")
        if row.get("completion") and _notice(root, row)["state"] == "accepted":
            return copy.deepcopy(row)
        if not row.get("completion"):
            text = message or f"Task {outcome}: {row['goal']}. Checks: {checks or 'see Camel result'}. Result: {result or row['camel_thread_id']}. Please review, collect, merge and archive the completed work."
            sessions.require_text(text, "Completion message")
            row.update(phase="awaiting_terminal", result=result, checks=checks, summary=message,
                       completion={"outcome": outcome, "text": text, "result_key": digest([row["id"], row.get("cycle", 0), outcome, result, checks, text])})
            write_json(_task_path(root), state)
        try:
            with _open(factory, root, "oasis_complete_" + row["id"], channel=_task_channel(row)) as server:
                _thread(server, row["cameleer_thread_id"], root, _task_project(row))
                snapshot, _ = _terminal_snapshot(root, row, server)
                row["native_turn"] = snapshot
                _deliver_completion(root, row, snapshot, server, explicit=True)
        except Exception as exc:
            write_json(_task_path(root), state)
            _render_after_failure(root, state, exc)
            raise
        write_json(_task_path(root), state)
        _render_tasks(root, state)
        return copy.deepcopy(row)


def _deliver_notice(root, row, recipient, text, path, server, *, explicit=False):
    retained = read_json(path) if path.exists() else {}
    if retained.get("state") == "accepted":
        return retained
    native = _thread(server, recipient, root, row.get("project_id") or _task_project(row))
    # An uncertain send may already have started a recipient turn. Reconcile it
    # even while active, but never inject a second message or steer that turn.
    if retained.get("state") in ("started", "uncertain"):
        return sessions.send_once(path, recipient, text, server,
                                  expected_binding=_binding(root, row.get("project_id") or _task_project(row)))
    if retained.get("state") == "rejected" and not explicit:
        return retained
    if (native.get("status") or {}).get("type") not in ("idle", "notLoaded"):
        return {"state": "pending_recipient", "thread_id": recipient}
    return sessions.send_once(path, recipient, text, server,
                              expected_binding=_binding(root, row.get("project_id") or _task_project(row)))


def _deliver_completion(root, row, snapshot, server, *, explicit=False):
    completion = row["completion"]
    path = _delivery_path(root, row, "complete")
    if snapshot["state"] not in ("ready", "failed", "cancelled"):
        if _notice(root, row)["state"] != "accepted":
            completion["delivery"] = {"state": "pending_terminal"}
            row["phase"] = "terminal_unverified" if snapshot["state"] == "unverified" else "awaiting_terminal"
        return
    actual = snapshot["state"] if snapshot["state"] in ("failed", "cancelled") else completion["outcome"]
    if not row.get("archived"):
        row["phase"] = actual
    # The submission is immutable. A native failure overrides its claimed success
    # only in the notice/outcome used for collection, not in the original text.
    text = completion["text"] if actual == completion["outcome"] else (
        f"Task {actual}: {row.get('current_goal', row['goal'])}. "
        f"Submitted result: {row.get('result') or row['camel_thread_id']}. Resume this same task for corrections.")
    completion["native_outcome"] = actual
    completion["delivery"] = _deliver_notice(root, row, row["cameleer_thread_id"], text, path, server, explicit=explicit)


def _terminal_snapshot(root, row, server):
    native = _thread(server, row["camel_thread_id"], root, _task_project(row))
    try:
        page = sessions._history_page(server.call("thread/turns/list", {"threadId": row["camel_thread_id"],
            "itemsView": "full", "sortDirection": "desc", "limit": 1}), "thread/turns/list")
        turns = page["data"]
    except sessions.NativeError as exc:
        if exc.code != -32601:
            raise
        turns = sessions._full_turns(server, row["camel_thread_id"])[-1:]
    continuation = row.get("dependency_continuations") or []
    delivery = continuation[-1]["delivery"] if continuation else row.get("assignment_delivery", {})
    if not isinstance(delivery, dict):
        raise HarnessError("Assignment delivery must be an object")
    if not delivery.get("turn_id"):
        path = _delivery_path(root, row, "assign")
        if path.exists():
            delivery = read_json(path)
            if not isinstance(delivery, dict):
                raise HarnessError("Retained assignment delivery must be an object")
    tracked = delivery.get("turn_id")
    if not turns:
        return {"state": "pending", "id": tracked, "status": None, "final_available": False}, native
    turn = turns[0]
    sessions.require_text(turn.get("id"), "Native assignment turn ID")
    if not isinstance(turn.get("items"), list):
        raise HarnessError("Native turn final items are unavailable")
    if not tracked:
        # Legacy links need actual assignment evidence, never an arbitrary idle turn.
        if any(item.get("type") == "userMessage" and (
                delivery.get("message_id") and item.get("clientId") == delivery["message_id"]
                or row.get("prompt") and sessions._message_text(item) == row["prompt"])
                for item in turn["items"] if isinstance(item, dict)):
            tracked = turn["id"]
        else:
            return {"state": "unverified", "id": None, "status": turn.get("status"), "final_available": False}, native
    if turn["id"] != tracked:
        return {"state": "unverified", "id": tracked, "status": None, "final_available": False,
                "reason": "New native work exists beyond this assignment; preserve its chat and task link"}, native
    status = turn.get("status")
    if not isinstance(status, str):
        raise HarnessError("Native assignment turn status must be text")
    final = next((item for item in reversed(turn["items"]) if isinstance(item, dict)
                  and item.get("type") == "agentMessage" and item.get("phase") == "final_answer"
                  and isinstance(item.get("text"), str) and item["text"].strip()), None)
    state = "failed" if status == "failed" else "cancelled" if status == "interrupted" else "pending"
    thread_status = native.get("status") or {}
    if not isinstance(thread_status, dict):
        raise HarnessError("Native thread status must be an object")
    if status == "completed" and final and thread_status.get("type") in ("idle", "notLoaded"):
        state = "ready"
    return {"state": state, "id": tracked, "status": status, "final_available": final is not None,
            **({"final_message_id": final.get("id")} if final else {})}, native


def _await_terminal(root, row, server, timeout):
    deadline = time.monotonic() + timeout
    snapshot, native = _terminal_snapshot(root, row, server)
    if snapshot["state"] != "pending" or timeout == 0 or not callable(getattr(server, "wait_events", None)):
        return snapshot
    covered = _event_covered(server, row["camel_thread_id"])
    path = sessions.require_text(native.get("path"), "Native rollout watch path")
    if not covered and not Path(path).is_absolute():
        raise HarnessError("Native rollout watch requires an absolute path")
    watch_id, watching, failure = "oasis_collect_" + uuid.uuid4().hex, False, None
    try:
        if not covered:
            try:
                response = server.call("fs/watch", {"watchId": watch_id, "path": path})
            except sessions.NativeError as exc:
                if exc.code != -32601:
                    raise
                return snapshot
            watching = True
            if not isinstance(response, dict) or not isinstance(response.get("path"), str) or sessions.canonical_root(response["path"]) != sessions.canonical_root(path):
                raise HarnessError("Native filesystem watch returned another rollout path")
            # Close the filesystem registration race for legacy connections only.
            snapshot, _ = _terminal_snapshot(root, row, server)
        last_read, first_dirty, last_dirty, terminal_event = time.monotonic(), None, None, False
        while snapshot["state"] == "pending" and time.monotonic() < deadline:
            now = time.monotonic()
            due = min(last_dirty + .25, first_dirty + 1) if first_dirty is not None else deadline
            due = max(due, last_read + (0 if terminal_event else 5)) if first_dirty is not None else due
            events = server.wait_events(max(0, min(deadline, due) - now))
            changed = not covered and any(event.get("method") == "fs/changed" and isinstance(event.get("params"), dict)
                          and event["params"].get("watchId") == watch_id for event in events)
            terminal_event |= any(event.get("method") == "turn/completed"
                and isinstance(event.get("params"), dict)
                and event["params"].get("threadId") == row["camel_thread_id"]
                and isinstance(event["params"].get("turn"), dict)
                and event["params"]["turn"].get("id") == snapshot.get("id") for event in events)
            terminal_event |= snapshot.get("status") in ("completed", "failed", "interrupted") and any(
                event.get("method") == "thread/status/changed" and isinstance(event.get("params"), dict)
                and event["params"].get("threadId") == row["camel_thread_id"]
                and (event["params"].get("status") or {}).get("type") in ("idle", "notLoaded") for event in events)
            changed = changed or terminal_event
            if changed:
                now = time.monotonic()
                first_dirty = first_dirty if first_dirty is not None else now
                last_dirty = now
            now = time.monotonic()
            if first_dirty is not None and now >= max(min(last_dirty + .25, first_dirty + 1), last_read + (0 if terminal_event else 5)):
                snapshot, _ = _terminal_snapshot(root, row, server)
                last_read, first_dirty, last_dirty, terminal_event = time.monotonic(), None, None, False
            elif not events and first_dirty is None:
                break
        # Persistence may have completed at the wait boundary without a delivered event.
        if snapshot["state"] == "pending":
            snapshot, _ = _terminal_snapshot(root, row, server)
        return snapshot
    except Exception as exc:
        failure = exc
        raise
    finally:
        if watching:
            try:
                server.call("fs/unwatch", {"watchId": watch_id})
            except (HarnessError, OSError, ValueError, KeyError) as exc:
                if failure is None:
                    raise
                failure.add_note(f"Native watch cleanup failed: {exc}; connection closure releases this scoped watch")


def _collection_boundary(root, state, row, snapshot):
    row["native_turn"] = snapshot
    if snapshot["state"] == "ready":
        return None
    row["phase"] = snapshot["state"] if snapshot["state"] in ("failed", "cancelled") else "terminal_unverified" if snapshot["state"] == "unverified" else "awaiting_terminal"
    write_json(_task_path(root), state)
    _render_tasks(root, state)
    return {**copy.deepcopy(row), "instruction": snapshot.get("reason") or
            "Keep this Camel available. Resume this same collection only after its actual assignment turn completes naturally with final output; use task-resume for failed or interrupted work."}


def _collection_identity(root, row):
    assignment = _delivery_path(root, row, "assign")
    return digest([{key: row.get(key) for key in ("id", "cycle", "camel_thread_id", "cameleer_thread_id", "prompt", "assignment_delivery", "dependency_continuations")},
                   (row.get("completion") or {}).get("result_key"), _task_project(row),
                   read_json(assignment) if assignment.exists() else None])


def collect(target, task_id, *, result=None, checks=None, merge=None, merged_reference=None,
            factory=sessions.command_server, wait_timeout=30, timeout=30):
    try:
        with sessions.deadline_scope(timeout=timeout):
            return _collect(target, task_id, result=result, checks=checks, merge=merge,
                            merged_reference=merged_reference, factory=factory, wait_timeout=wait_timeout)
    except sessions.DeadlineExceeded:
        # No new native action after expiry. Durable merge/archive receipts remain
        # authoritative; reading status does not retry any uncertain mutation.
        row = task_status(target, task_id)
        return {**row, "collection_timeout": True,
                "instruction": "Native operation deadline expired. Preserve this task and resume the same collection from its retained receipts."}


def _collect(target, task_id, *, result=None, checks=None, merge=None, merged_reference=None, factory=sessions.command_server, wait_timeout=30):
    """Collect a reviewed result; merge callbacks and native archives run once."""
    root, _ = _root(target)
    if isinstance(wait_timeout, bool) or not isinstance(wait_timeout, (int, float)) or not math.isfinite(wait_timeout) or wait_timeout < 0:
        raise HarnessError("Collection event wait timeout must be finite and nonnegative")
    lock = contained(root, ".oasis/local/operations.lock")
    with operation_lock(lock):
        state = _tasks(root)
        row = _task(state, task_id)
        completion = row.get("completion")
        if not completion:
            raise HarnessError("This task has no terminal result to collect")
        if row.get("collected_result_key") == completion["result_key"]:
            return copy.deepcopy(row)
        if completion["outcome"] != "completed":
            if result is not None:
                row["result"] = result
            if checks is not None:
                row["checks"] = checks
            if merged_reference is not None:
                row.update(merge_state="merged", result=merged_reference)
            row["collected_result_key"] = completion["result_key"]
            write_json(_task_path(root), state)
            _render_tasks(root, state)
            return copy.deepcopy(row)
        identity, captured = _collection_identity(root, row), copy.deepcopy(row)
    # Native final output may arrive later. Independent task notices must retain
    # access to the project state throughout this connection-scoped I/O wait.
    with _open(factory, root, "oasis_collect_" + captured["id"], channel=_task_channel(captured)) as server:
        snapshot = _await_terminal(root, captured, server, min(wait_timeout, max(0, sessions.remaining_timeout() - 1)))
        with operation_lock(lock):
            state = _tasks(root)
            row = _task(state, task_id)
            if _collection_identity(root, row) != identity:
                return {**copy.deepcopy(row), "collection": "collection_changed",
                        "instruction": "The assignment or result changed during the native wait. Review the current task before collecting it; prior merge inputs were not applied."}
            sessions.remaining_timeout()
            completion = row["completion"]
            if row.get("collected_result_key") == completion["result_key"]:
                return copy.deepcopy(row)
            if result is not None:
                row["result"] = result
            if checks is not None:
                row["checks"] = checks
            boundary = _collection_boundary(root, state, row, snapshot)
            if boundary is not None:
                return boundary
            if merged_reference is not None:
                row.update(merge_state="merged", result=merged_reference)
                write_json(_task_path(root), state)
            if row.get("merge_state") in ("started", "uncertain"):
                if merged_reference is None:
                    return {**copy.deepcopy(row), "phase": "merge_uncertain",
                            "instruction": "Inspect the retained merge outcome and resume with its actual merged reference."}
                row.update(merge_state="merged", result=merged_reference)
                write_json(_task_path(root), state)
            elif merge is not None and row.get("merge_state") != "merged":
                sessions.remaining_timeout()
                row["merge_state"] = "started"
                write_json(_task_path(root), state)
                try:
                    reference = merge(copy.deepcopy(row))
                    row.update(merge_state="merged", result=reference if reference is not None else row.get("result"))
                    write_json(_task_path(root), state)
                except Exception as exc:
                    row.update(merge_state="uncertain", error=str(exc))
                    write_json(_task_path(root), state)
                    raise
            boundary = _collection_boundary(root, state, row, _terminal_snapshot(root, row, server)[0])
            if boundary is not None:
                return boundary
            native = _thread(server, row["camel_thread_id"], root, _task_project(row))
            if (native.get("status") or {}).get("type") not in ("idle", "notLoaded"):
                return _collection_boundary(root, state, row, {**row["native_turn"], "state": "pending",
                    "reason": "Native work became active before archive; preserve this Camel and resume collection after its final output."})
            lifecycle = _lifecycle_once(_delivery_path(root, row, "archive"), row["camel_thread_id"], server, root,
                                       scoped={row["camel_thread_id"]}, expected_binding=_binding(root, _task_project(row)), native=native)
            if lifecycle["state"] == "accepted":
                row.update(phase="archived", archived=True, collected_result_key=completion["result_key"])
            else:
                row["phase"] = "archive_uncertain"
            write_json(_task_path(root), state)
            _render_tasks(root, state)
            return copy.deepcopy(row)


@_arm_notifications
def resume_task(target, task_id, message=None, *, planning=False, implementation=False, request_id=None, factory=sessions.command_server):
    root, _ = _root(target)
    if not isinstance(planning, bool) or not isinstance(implementation, bool) or planning and implementation:
        raise HarnessError("Choose either planning or implementation follow-up")
    if request_id is not None:
        sessions.require_text(request_id, "Follow-up request ID")
    with operation_lock(contained(root, ".oasis/local/operations.lock")):
        state = _tasks(root)
        row = _task(state, task_id)
        if message is None and row.get("completion"):
            return copy.deepcopy(row)
        if message is not None:
            sessions.require_text(message, "Follow-up request")
            sha = digest([message, planning, implementation])
            request_key = request_id or sha
            if row.get("followup_key") == request_key:
                _request_match(row, sha, {"planning": planning, "execution": implementation}, hash_field="followup_input_sha256")
                if row.get("followup_input_sha256") is None:
                    saved_prompt = row.get("prompt", "")
                    suffix = "\n\n" + COMPLETION_REMINDER
                    if isinstance(saved_prompt, str) and saved_prompt.endswith(suffix) and saved_prompt[:-len(suffix)] != message:
                        raise HarnessError("Legacy request ID has different recorded message inputs")
                    saved_delivery = row.get("assignment_delivery", {})
                    if isinstance(saved_delivery, dict) and "execution" in saved_delivery and saved_delivery["execution"] != implementation:
                        raise HarnessError("Legacy request ID has different recorded implementation selection")
                if row.get("completion"):
                    return copy.deepcopy(row)
            for previous in row.get("history", []):
                if previous.get("followup_key") == request_key:
                    _request_match(previous, sha, {}, hash_field="followup_input_sha256")
                    return {"id": row["id"], "camel_thread_id": row["camel_thread_id"],
                            "current_cycle": row.get("cycle", 0), **copy.deepcopy(previous)}
        previous_archive = _delivery_path(root, row, "archive")
        if message is not None and not row.get("archived") and previous_archive.exists():
            archive_record = read_json(previous_archive)
            if archive_record.get("state") in ("accepted", "started", "uncertain"):
                with _open(factory, root, "oasis_restore_recover_" + row["id"], channel=_task_channel(row)) as server:
                    archive_result = _lifecycle_once(previous_archive, row["camel_thread_id"], server, root,
                                                     scoped={row["camel_thread_id"]}, expected_binding=_binding(root, _task_project(row)))
                if archive_result["state"] != "accepted":
                    return {**copy.deepcopy(row), "phase": "archive_uncertain",
                            "instruction": "Reconcile the retained archive outcome before delivering the follow-up."}
                row["archived"] = True
                write_json(_task_path(root), state)
        if not row.get("camel_thread_id"):
            receipt = read_json(row["session_receipt"])
            if receipt.get("phase") != "creation_rejected":
                found = sessions.inspect(row["session_receipt"], factory)
                if not found.get("thread_id"):
                    return {**copy.deepcopy(row), "phase": "creation_uncertain"}
                receipt["thread_id"] = found["thread_id"]
            sessions.create_metadata(row["session_receipt"], receipt, factory)
            row["camel_thread_id"] = receipt["thread_id"]
            write_json(_task_path(root), state)
        if message is None:
            with _open(factory, root, "oasis_resume_" + row["id"], channel=_task_channel(row)) as server:
                _assign_delivery(root, row, server)
        else:
            if row.get("followup_key") != request_key:
                row["history"].append({name: copy.deepcopy(row.get(name)) for name in
                    ("cycle", "phase", "completion", "result", "checks", "current_goal", "followup_key", "followup_input_sha256", "native_turn", "unsubmitted_notice", "dependency_continuations")})
                row["cycle"] = row.get("cycle", 0) + 1
                row.update(followup_key=request_key, followup_input_sha256=sha, prompt=_completion_prompt(message),
                           current_goal=message.strip().splitlines()[0], planning=planning, execution=implementation, phase="resuming")
                for name in ("completion", "collected_result_key", "merge_state", "summary", "checks", "result", "native_turn", "unsubmitted_notice", "dependency_continuations"):
                    row.pop(name, None)
                write_json(_task_path(root), state)
            with _open(factory, root, "oasis_resume_" + row["id"], channel=_task_channel(row)) as server:
                native = _thread(server, row["camel_thread_id"], root, _task_project(row))
                if row.get("archived"):
                    lifecycle = _lifecycle_once(_delivery_path(root, row, "restore"), row["camel_thread_id"], server, root, restore=True,
                                                expected_binding=_binding(root, _task_project(row)), native=native)
                    if lifecycle["state"] != "accepted":
                        return {**copy.deepcopy(row), "phase": "restore_uncertain"}
                    row["archived"] = False
                    write_json(_task_path(root), state)
                delivery = sessions.send_once(_delivery_path(root, row, "assign"), row["camel_thread_id"], row["prompt"], server,
                                              planning=planning, execution=implementation, skill=_role_skill(root, "Camel"),
                                              expected_binding=_binding(root, _task_project(row)))
                row.update(phase="assigned" if delivery["state"] == "accepted" else delivery["state"], assignment_delivery=delivery)
        row.pop("error", None)
        write_json(_task_path(root), state)
        _render_tasks(root, state)
        return copy.deepcopy(row)


@_arm_notifications
def dependency_wait(target, producer_id, consumer_id, condition, *, request_id=None, purpose=None, factory=sessions.command_server):
    root, _ = _root(target)
    if request_id is not None:
        sessions.require_text(request_id, "Dependency request ID")
    for value, label in ((producer_id, "Producer chat ID"), (consumer_id, "Consumer chat ID"), (condition, "Dependency condition")):
        sessions.require_text(value, label)
    if producer_id == consumer_id:
        raise HarnessError("A dependency needs different producer and consumer chat IDs")
    if purpose not in (None, "assignment", "partial"):
        raise HarnessError("Dependency purpose must be assignment or partial")
    sha = digest([producer_id, consumer_id, condition])
    with operation_lock(contained(root, ".oasis/local/operations.lock")):
        state = _tasks(root)
        producer_task = next((task for task in state["tasks"] if task.get("camel_thread_id") == producer_id), None)
        shared = bool(producer_task and producer_task.get("cameleer_thread_id") == consumer_id and purpose != "partial")
        if purpose == "assignment" and producer_task is None:
            raise HarnessError("Assignment waiting requires an existing assigned producer")
        if shared:
            sha = digest([producer_id, consumer_id, condition, "assignment", producer_task["id"], producer_task.get("cycle", 0)])
        elif purpose == "assignment":
            sha = digest([producer_id, consumer_id, condition, purpose, producer_task["id"], producer_task.get("cycle", 0)])
        consumer = next((task for task in state["tasks"] if task.get("camel_thread_id") == consumer_id), None)
        binding = {"task_id": consumer["id"], "cycle": consumer.get("cycle", 0)} if consumer else None
        key = request_id or (digest([sha, binding]) if binding else sha)
        row = next((row for row in state["dependencies"] if row.get("request_key") == key), None)
        if row is not None:
            _request_match(row, sha, {"producer_thread_id": producer_id, "consumer_thread_id": consumer_id, "condition": condition})
            if "consumer_binding" in row and row["consumer_binding"] != binding:
                raise HarnessError("Dependency request belongs to another task cycle; preserve its original action")
        if row is None:
            if shared:
                row = {"id": uuid.uuid4().hex, "request_key": key, "input_sha256": sha,
                       "producer_thread_id": producer_id, "consumer_thread_id": consumer_id,
                       "condition": condition, "purpose": "assignment", "phase": "shared_assignment",
                       "assignment_binding": {"task_id": producer_task["id"], "cycle": producer_task.get("cycle", 0)},
                       "consumer_binding": binding}
                state["dependencies"].append(row)
                write_json(_task_path(root), state)
                _render_tasks(root, state)
                return _assignment_wait(state, row)
            with _open(factory, root, "oasis_dependency_register", channel=_task_channel(producer_task) if producer_task else None) as server:
                project_id = sessions.project_id(server, root)
                producer = _thread(server, producer_id, root, project_id)
                _thread(server, consumer_id, root, project_id)
                try:
                    latest = sessions._history_page(server.call("thread/turns/list", {
                        "threadId": producer_id, "itemsView": "notLoaded", "sortDirection": "desc", "limit": 1}), "thread/turns/list")["data"]
                except sessions.NativeError as exc:
                    if exc.code != -32601:
                        raise
                    latest = []
            row = {"id": uuid.uuid4().hex, "request_key": key, "input_sha256": sha, "producer_thread_id": producer_id,
                   "consumer_thread_id": consumer_id, "condition": condition, "phase": "waiting",
                   "purpose": purpose or "partial",
                   "project_id": project_id, "producer_turn_id": latest[0]["id"] if latest else None,
                   "consumer_binding": binding}
            if purpose == "assignment":
                row["producer_binding"] = {"task_id": producer_task["id"], "cycle": producer_task.get("cycle", 0)}
            state["dependencies"].append(row)
            write_json(_task_path(root), state)
        _render_tasks(root, state)
        if row.get("assignment_binding"):
            return _assignment_wait(state, row)
        return {**copy.deepcopy(row), "end_turn": True}


@_arm_notifications
def dependency_finish(target, dependency_id, *, outcome="completed", result=None, message=None, factory=sessions.command_server):
    if outcome not in ("completed", "failed", "cancelled"):
        raise HarnessError("Dependency outcome must be completed, failed or cancelled")
    root, _ = _root(target)
    with operation_lock(contained(root, ".oasis/local/operations.lock")):
        state = _tasks(root)
        row = next((row for row in state["dependencies"] if row["id"] == dependency_id), None)
        if row is None:
            raise HarnessError("Unknown dependency ID")
        if not _dependency_current(state, row):
            return {**copy.deepcopy(row), "phase": "superseded", "instruction": "Preserve this previous task cycle; no notice was sent."}
        if row.get("assignment_binding"):
            return _assignment_wait(state, row)
        if row["phase"] in ("completed", "failed", "cancelled") and _notice(root, row, dependency=True)["state"] == "accepted":
            return copy.deepcopy(row)
        if row["phase"] == "waiting":
            row.update(phase=outcome, result=result, text=message or f"Dependency {outcome}: {row['condition']}. Result: {result or 'see producer chat ' + row['producer_thread_id']}.")
            write_json(_task_path(root), state)
        path = contained(root, f".oasis/local/tasks/dependencies/{row['id']}.json")
        try:
            consumer_task = next((task for task in state["tasks"] if task.get("camel_thread_id") == row["consumer_thread_id"]), None)
            with _open(factory, root, "oasis_dependency_" + row["id"], channel=_task_channel(consumer_task) if consumer_task else None) as server:
                project_id = row.get("project_id") or sessions.project_id(server, root)
                _thread(server, row["producer_thread_id"], root, project_id)
                row["project_id"] = project_id
                row["delivery"] = _deliver_notice(root, row, row["consumer_thread_id"], row["text"], path, server, explicit=True)
                _dependency_continuation(state, row)
        except Exception as exc:
            _render_after_failure(root, state, exc)
            raise
        write_json(_task_path(root), state)
        _render_tasks(root, state)
        return copy.deepcopy(row)


def _dependency_current(state, dependency):
    producer = dependency.get("producer_binding")
    if producer is not None and not any(task.get("id") == producer["task_id"] and task.get("cycle", 0) == producer["cycle"]
            and task.get("camel_thread_id") == dependency["producer_thread_id"] for task in state["tasks"]):
        return False
    assignment = dependency.get("assignment_binding")
    if assignment is not None and not any(task.get("id") == assignment["task_id"]
            and task.get("cycle", 0) == assignment["cycle"]
            and task.get("camel_thread_id") == dependency["producer_thread_id"]
            and task.get("cameleer_thread_id") == dependency["consumer_thread_id"] for task in state["tasks"]):
        return False
    binding = dependency.get("consumer_binding")
    if binding is None:
        return True
    return any(task.get("id") == binding["task_id"] and task.get("cycle", 0) == binding["cycle"]
               and task.get("camel_thread_id") == dependency["consumer_thread_id"] for task in state["tasks"])


def _assignment_wait(state, dependency):
    """An alias of the existing subscription, never another native message."""
    task = _task(state, dependency["assignment_binding"]["task_id"])
    completion = task.get("completion") or {}
    delivery = completion.get("delivery") or {}
    resolved = delivery.get("state") == "accepted" or task.get("collected_result_key") == completion.get("result_key") is not None
    return {**copy.deepcopy(dependency), "phase": completion.get("native_outcome", completion.get("outcome", "waiting")) if resolved else "waiting",
            "result_key": completion.get("result_key"), "result": task.get("result"),
            "delivery": copy.deepcopy(delivery), "subscription": "assignment", "end_turn": not resolved,
            "instruction": "Use the existing assignment notice, then review and collect. No dependency-finish is needed. Use --purpose partial for a distinct result or resource."}


def _dependency_continuation(state, dependency):
    delivery = dependency.get("delivery") or {}
    binding = dependency.get("consumer_binding")
    if not binding or delivery.get("state") != "accepted" or not delivery.get("turn_id"):
        return
    task = _task(state, binding["task_id"])
    continuations = task.setdefault("dependency_continuations", [])
    if not any(row["dependency_id"] == dependency["id"] for row in continuations):
        continuations.append({"dependency_id": dependency["id"], "delivery": copy.deepcopy(delivery)})
        task["phase"] = "assigned"


def _dependency_pending(state, dependency):
    if not _dependency_current(state, dependency):
        return False
    if dependency.get("assignment_binding"):
        return _assignment_wait(state, dependency)["end_turn"]
    return dependency.get("phase") == "waiting" or dependency.get("delivery", {}).get("state") != "accepted"


def notification_targets(root, server):
    """Read registered paths without delivering a notification."""
    state, targets = _tasks(root), {}
    for row in state["tasks"]:
        if row.get("camel_thread_id") and row.get("assignment_delivery") and not row.get("archived"):
            native = _thread(server, row["camel_thread_id"], root, _task_project(row))
            targets[native["id"]] = {"thread_id": native["id"], "path": native["path"]}
    return list(targets.values())


def _notification_pending(root, state):
    for row in state["tasks"]:
        if row.get("archived") or not row.get("camel_thread_id") or not row.get("assignment_delivery"):
            continue
        if row.get("completion"):
            if _notice(root, row)["state"] != "accepted":
                return True
        elif row.get("unsubmitted_notice", {}).get("delivery", {}).get("state") != "accepted":
            return True
    return any(not row.get("assignment_binding") and _dependency_current(state, row) and row.get("delivery", {}).get("state") != "accepted"
               for row in state["dependencies"])


class _ObservationReads:
    """One read phase only; never crosses the subsequent writer boundary."""
    def __init__(self, server):
        self.server, self.reads = server, {}

    def call(self, method, params):
        if method not in ("thread/read", "thread/turns/list", "project/list"):
            return self.server.call(method, params)
        key = (method, digest(params))
        if key not in self.reads:
            self.reads[key] = self.server.call(method, params)
        return copy.deepcopy(self.reads[key])

    def __getattr__(self, name):
        return getattr(self.server, name)


def _event_covered(server, identity):
    covered = getattr(server, "event_covered", None)
    return bool(callable(covered) and covered(identity))


def notification_step(root, server, *, changed_threads=None, cache=None):
    """Observe exact registered work, then reconcile one notice per transition.

    Readers run outside the writer lock. Revalidated identities protect late
    results; the existing send journal protects accepted and ambiguous effects.
    The process owns no model work, integration, archive or host lifecycle.
    """
    root = Path(root).resolve()
    cache = cache if cache is not None else {}
    state = _tasks(root)
    observations, targets = {}, {}
    reads = _ObservationReads(server)

    def native(identity, project, *, idle_only=False, turn_id=None):
        key = ("thread", identity, project)
        if key not in cache or changed_threads is None or identity in changed_threads:
            cache[key] = _thread(reads, identity, root, project)
        thread = cache[key]
        if isinstance(thread.get("path"), str):
            previous = targets.get(identity, {})
            targets[identity] = {**previous, "thread_id": identity, "path": thread["path"],
                                 "event_covered": _event_covered(server, identity),
                                 "idle_only": previous.get("idle_only", False) or idle_only}
            if turn_id and not previous.get("turn_id"):
                targets[identity]["turn_id"] = turn_id
        return thread

    for row in state["tasks"]:
        identity = row.get("camel_thread_id")
        completion = row.get("completion") or {}
        if (not identity or not row.get("assignment_delivery") or row.get("archived")
                or row.get("phase") in ("creating", "creation_uncertain", "assignment_uncertain")):
            continue
        if completion and _notice(root, row)["state"] == "accepted":
            continue
        missing = row.get("unsubmitted_notice") or {}
        if not completion and missing.get("delivery", {}).get("state") == "accepted":
            continue
        signature = _collection_identity(root, row)
        key = ("task", row["id"], signature)
        if key not in cache or changed_threads is None or identity in changed_threads:
            cache[key] = _terminal_snapshot(root, row, reads)
        snapshot, thread = cache[key]
        cache[("thread", identity, _task_project(row))] = thread
        targets[identity] = {"thread_id": identity, "path": thread["path"], "turn_id": snapshot.get("id"),
                             "cycle": row.get("cycle", 0), "event_covered": _event_covered(server, identity),
                             "awaiting_idle": snapshot.get("status") in ("completed", "failed", "interrupted")}
        observations[row["id"]] = (signature, snapshot)
        waiting_dependency = any(dependency.get("consumer_thread_id") == identity
            and _dependency_pending(state, dependency) for dependency in state["dependencies"])
        if snapshot["state"] in ("failed", "cancelled") or snapshot["state"] == "ready" and (completion or not waiting_dependency):
            native(row["cameleer_thread_id"], _task_project(row), idle_only=True)
    for row in state["dependencies"]:
        if row.get("assignment_binding") or not _dependency_current(state, row):
            continue
        if row.get("delivery", {}).get("state") == "accepted":
            continue
        project = row.get("project_id") or sessions.project_id(reads, root)
        native(row["producer_thread_id"], project, turn_id=row.get("producer_turn_id"))
        if row.get("phase") == "waiting" and row.get("producer_turn_id"):
            key = ("dependency", row["id"], row["producer_turn_id"])
            if key not in cache or changed_threads is None or row["producer_thread_id"] in changed_threads:
                turns = sessions._history_page(reads.call("thread/turns/list", {
                    "threadId": row["producer_thread_id"], "itemsView": "notLoaded", "sortDirection": "desc", "limit": 1}), "thread/turns/list")["data"]
                cache[key] = turns[0] if turns else {}
            turn = cache[key]
            if turn.get("id") == row["producer_turn_id"] and turn.get("status") in ("failed", "interrupted"):
                observations[row["id"]] = (digest(row), "failed" if turn["status"] == "failed" else "cancelled")
        if row.get("phase") != "waiting" or row["id"] in observations:
            native(row["consumer_thread_id"], project, idle_only=True)

    needs_writer = any(not isinstance(observed[1], dict) or observed[1]["state"] != "pending"
                       for observed in observations.values())
    needs_writer |= any(not row.get("assignment_binding") and _dependency_current(state, row) and row.get("phase") in ("completed", "failed", "cancelled")
                        and row.get("delivery", {}).get("state") != "accepted" for row in state["dependencies"])
    if not needs_writer:
        # Pending native work changes no task intent and has no notice to send.
        # In particular, do not compete with a foreground complete() just to
        # persist a diagnostic pending snapshot. Its journal event will reconcile
        # a real transition, still through the unchanged writer boundary below.
        return {"pending": _notification_pending(root, state), "targets": list(targets.values()),
                "journal_digest": digest(state),
                "next_action": "Use workflow task-resume or dependency-finish for the retained operation; do not poll from a model."}

    with operation_lock(contained(root, ".oasis/local/operations.lock")):
        current = _tasks(root)
        before = digest(current)
        for row in current["tasks"]:
            observation = observations.get(row["id"])
            if not observation or _collection_identity(root, row) != observation[0]:
                continue
            snapshot = observation[1]
            row["native_turn"] = snapshot
            if not row.get("completion") and snapshot["state"] in ("failed", "cancelled"):
                outcome = snapshot["state"]
                text = f"Task {outcome}: {row.get('current_goal', row['goal'])}. Result: {row['camel_thread_id']}. Resume this same task for corrections."
                row["completion"] = {"outcome": outcome, "text": text,
                    "result_key": digest([row["id"], row.get("cycle", 0), snapshot["id"], outcome]), "native_only": True}
            if row.get("completion"):
                _deliver_completion(root, row, snapshot, server)
            elif snapshot["state"] == "ready" and any(dependency.get("consumer_thread_id") == row["camel_thread_id"]
                    and _dependency_pending(current, dependency)
                    for dependency in current["dependencies"]):
                row["phase"] = "waiting_dependency"
            elif snapshot["state"] == "ready":
                row["phase"] = "terminal_unsubmitted"
                notice = row.setdefault("unsubmitted_notice", {"text":
                    f"Task ended without a submitted result: {row.get('current_goal', row['goal'])}. Review {row['camel_thread_id']} and recover this same task."})
                notice["delivery"] = _deliver_notice(root, row, row["cameleer_thread_id"], notice["text"],
                    _delivery_path(root, row, "unsubmitted"), server)
        for row in current["dependencies"]:
            if row.get("assignment_binding") or not _dependency_current(current, row):
                continue
            observed = observations.get(row["id"])
            if observed and digest(row) == observed[0] and row.get("phase") == "waiting":
                row.update(phase=observed[1], text=f"Dependency {observed[1]}: {row['condition']}. Producer turn ended; resume the blocked portion with the retained result.")
            if row.get("phase") in ("completed", "failed", "cancelled") and row.get("delivery", {}).get("state") != "accepted":
                project = row.get("project_id") or sessions.project_id(server, root)
                _thread(server, row["producer_thread_id"], root, project)
                row["project_id"] = project
                row["delivery"] = _deliver_notice(root, row, row["consumer_thread_id"], row["text"],
                    contained(root, f".oasis/local/tasks/dependencies/{row['id']}.json"), server)
                _dependency_continuation(current, row)
        if digest(current) != before:
            write_json(_task_path(root), current)
            _render_tasks(root, current)
    pending = _notification_pending(root, current)
    return {"pending": pending, "targets": list(targets.values()), "journal_digest": digest(current),
            "next_action": "Use workflow task-resume or dependency-finish for the retained operation; do not poll from a model."}
