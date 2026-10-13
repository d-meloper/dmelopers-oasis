"""Persistent project modes, Camel tasks and scoped one-shot native notices."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
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
            or sessions.canonical_root(value.get("target", "")) != sessions.canonical_root(root)
            or not isinstance(value.get("roles"), list) or not isinstance(value.get("history"), list)
            or any(not isinstance(row, dict) for row in value.get("roles", []))):
        raise HarnessError("Invalid workflow state or target root")
    return value


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
    if (thread.get("id") != identity or sessions.canonical_root(thread.get("cwd", "")) != sessions.canonical_root(root)
            or thread.get("projectId") != project_id):
        raise HarnessError("Native thread belongs to another project/root")
    return thread


def verify_binding(server, binding, root, project_id):
    if not isinstance(binding, dict):
        raise HarnessError("Workflow binding must be an object")
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
         task=None, language="ko", factory=sessions.AppServer):
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
    with factory(operation + "_plan") as server:
        identity, settings, _ = sessions.prepare(server, source_id, root)
        owned = _bindings(server, root, identity, state["roles"] + (bindings or []))
    same = all(any(row.get("role") == role for row in owned) for role in MODES[mode])
    same = same and not any(row.get("role") in MODES["oasis" if mode == "pioneer" else "pioneer"] for row in owned)
    return {"schema_version": 1, "operation_id": operation, "target": str(root), "project_id": identity,
            "source_thread_id": source_id, "settings": settings, "mode": mode,
            "selected_mode_before": effective_mode(project), "primary_role": "Pioneer" if mode == "pioneer" else "Cameleer",
            "language": language, "context": context, "follow_on_task": _completion_prompt(task) if task is not None else None, "existing_roles": owned,
            "old_roles": [] if same else owned, "unrelated": state.get("unrelated", []),
            "new_roles": [] if same else [{"role": role, "originator": operation + "_" + role.lower(),
                                           "prompt": _prompt(role, context, language)} for role in MODES[mode]],
            "same_mode": same}


def start(reviewed, authority=None, factory=sessions.AppServer):
    value = read_json(reviewed) if isinstance(reviewed, (str, Path)) else copy.deepcopy(reviewed)
    path = _receipt_path(value)
    root, _ = _root(value["target"])
    with operation_lock(contained(root, ".oasis/local/operations.lock")):
        state = _state(root)
        if state.get("pending_operation") and Path(state["pending_operation"]).resolve() != path.resolve():
            raise HarnessError("Another mode operation is pending; resume that operation")
        if path.exists():
            value = _read_receipt(path)
        else:
            value.update(phase="metadata", actions=[], target_receipts=[])
            write_json(path, value)
            state["pending_operation"] = str(path)
            write_json(_local(root, "state.json"), state)
        return _advance(path, value, factory)


def _lifecycle_once(path, thread_id, server, root, *, restore=False, scoped=()):
    method = "thread/unarchive" if restore else "thread/archive"
    value = read_json(path) if Path(path).exists() else {"thread_id": thread_id, "state": "not_started", "method": method}
    if value.get("thread_id") != thread_id or value.get("method") != method:
        raise HarnessError("Lifecycle action path belongs to another operation")
    if value["state"] == "accepted":
        return value
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
    unfinished = unfinished_tasks(root) if value["old_roles"] else []
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
        if not receipt.get("thread_id") and receipt["phase"] != "prepared":
            found = sessions.inspect(target_path, factory)
            if not found.get("thread_id"):
                value["phase"] = "creation_uncertain"
                write_json(path, value)
                return _result(path, value)
            receipt["thread_id"] = found["thread_id"]
        sessions.create_metadata(target_path, receipt, factory)
        new_roles.append({"role": row["role"], "thread_id": receipt["thread_id"], "parent_thread_id": None})
        with factory(value["operation_id"]) as server:
            delivery = sessions.send_once(path.parent / (row["role"] + "-assign.json"), receipt["thread_id"], row["prompt"], server,
                                          skill=_role_skill(root, row["role"]))
        if delivery["state"] != "accepted":
            value["phase"] = "assignment_uncertain"
            write_json(path, value)
            return _result(path, value)
    roles = value["existing_roles"] if value["same_mode"] else new_roles
    primary = next(row["thread_id"] for row in roles if row.get("role") == value["primary_role"])
    value["primary_thread_id"] = primary
    scoped = {row["thread_id"] for row in value["old_roles"]}
    with factory(value["operation_id"]) as server:
        for row in value["old_roles"]:
            native = _thread(server, row["thread_id"], root, value["project_id"])
            if (native.get("status") or {}).get("type") not in (None, "idle", "notLoaded") and row["thread_id"] != value["source_thread_id"]:
                value["phase"] = "waiting_for_task"
                write_json(path, value)
                return _result(path, value)
            lifecycle = _lifecycle_once(path.parent / (digest(row["thread_id"]) + "-archive.json"),
                                        row["thread_id"], server, root, scoped=scoped)
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
        with factory(value["operation_id"]) as server:
            delivery = sessions.send_once(path.parent / "task.json", primary, value["follow_on_task"], server)
        if delivery["state"] != "accepted":
            value["phase"] = "task_uncertain"
            write_json(path, value)
            return _result(path, value)
    state["pending_operation"] = None
    write_json(_local(root, "state.json"), state)
    value["phase"] = "complete"
    write_json(path, value)
    return _result(path, value)


def inspect(path, factory=sessions.AppServer):
    """Read retained local state; inspection never sends a role prompt."""
    value = _read_receipt(path)
    return _result(Path(path).resolve(), value)


def resume(path, authority=None, factory=sessions.AppServer, *, begin_action=None):
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
    lines = ["# Camel tasks", "", "Updated when Cameleer assigns, collects or resumes work.", "",
             "| Camel chat | Goal | Stage / dependencies | Work / result | Result / checks |",
             "| --- | --- | --- | --- | --- |"]
    for row in state["tasks"]:
        identity = row.get("camel_thread_id")
        chat = f"[{identity}](codex://threads/{identity})" if identity else f"Creation pending ({row['id']})"
        waits = [d["condition"] for d in state["dependencies"] if d.get("consumer_thread_id") == identity and d.get("phase") == "waiting"]
        phase = row["phase"] + ("; waiting for " + ", ".join(waits) if waits else "")
        location = " / ".join(str(value) for value in (row.get("location"), row.get("result")) if value)
        summary = " / ".join(str(value) for value in (row.get("summary"), row.get("checks")) if value)
        if row["phase"] in TERMINAL:
            location = str(row.get("result") or "")
        lines.append("| " + " | ".join((chat, _cell(row["goal"]), _cell(phase), _cell(location), _cell(summary))) + " |")
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
    return row


def task_status(target, task_id=None, *, include_complete=False):
    state = _tasks(Path(target).resolve())
    if task_id:
        return copy.deepcopy(_task(state, task_id))
    return {"tasks": [row for row in state["tasks"] if include_complete or row.get("phase") not in TERMINAL]}


def _delivery_path(root, row, kind):
    return contained(root, f".oasis/local/tasks/{row['id']}/{row.get('cycle', 0)}-{kind}.json")


def _assign_delivery(root, row, server):
    delivery = sessions.send_once(_delivery_path(root, row, "assign"), row["camel_thread_id"], row["prompt"], server,
                                  planning=row.get("planning", False), skill=_role_skill(root, "Camel"))
    row["phase"] = "assigned" if delivery["state"] == "accepted" else delivery["state"]
    row["assignment_delivery"] = delivery
    return delivery


def assign(target, cameleer_id, goal, *, context=None, location=None, planning=False, title=None,
           request_id=None, factory=sessions.AppServer):
    root, _ = _root(target)
    sessions.require_text(cameleer_id, "Cameleer chat ID")
    sessions.require_text(goal, "Task goal")
    key = request_id or digest([cameleer_id, goal, context, location, planning, title])
    with operation_lock(contained(root, ".oasis/local/operations.lock")):
        state = _tasks(root)
        row = next((item for item in state["tasks"] if item.get("request_key") == key), None)
        if row is None:
            identity = uuid.uuid4().hex
            originator = "oasis_session_" + identity
            with factory(originator) as server:
                project_id, settings, source = sessions.prepare(server, cameleer_id, root)
                _thread(server, cameleer_id, root, project_id)
                selected_title = title or sessions.title_for("Camel", goal, source, sessions.discover(server, root, project_id))
            prompt = "Apply $oasis-camel to this assigned task. " + goal
            if context:
                prompt += "\n\n" + (context if isinstance(context, str) else json.dumps(context, ensure_ascii=False))
            prompt = _completion_prompt(prompt)
            row = {"id": identity, "request_key": key, "role": "Camel", "project_id": project_id, "cameleer_thread_id": cameleer_id,
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
            if not receipt.get("thread_id") and receipt["phase"] != "prepared":
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
            with factory("oasis_assign_" + row["id"]) as server:
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
    p.set_defaults(func=lambda args: task_status(args.target, args.task_id, include_complete=args.include_complete))
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
    p.set_defaults(func=lambda args: collect(args.target, args.task_id, result=args.result, checks=args.checks, merged_reference=args.merged_reference))
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
    p.add_argument("--request-id")
    p.set_defaults(func=lambda args: dependency_wait(args.target, args.producer_id, args.consumer_id, args.condition, request_id=args.request_id))
    p = commands.add_parser("dependency-finish")
    p.add_argument("--target", required=True)
    p.add_argument("--dependency-id", required=True)
    p.add_argument("--outcome", choices=("completed", "failed", "cancelled"), default="completed")
    p.add_argument("--result")
    p.add_argument("--message-file")
    p.set_defaults(func=lambda args: dependency_finish(args.target, args.dependency_id, outcome=args.outcome, result=args.result,
        message=Path(args.message_file).read_text(encoding="utf-8") if args.message_file else None))


def complete(target, task_id, message=None, *, result=None, checks=None, outcome="completed", factory=sessions.AppServer):
    if outcome not in ("completed", "failed", "cancelled"):
        raise HarnessError("Task outcome must be completed, failed or cancelled")
    root, _ = _root(target)
    with operation_lock(contained(root, ".oasis/local/operations.lock")):
        state = _tasks(root)
        row = _task(state, task_id)
        if not row.get("camel_thread_id"):
            raise HarnessError("Task has no resolved Camel chat ID")
        if not row.get("completion"):
            text = message or f"Task {outcome}: {row['goal']}. Checks: {checks or 'see Camel result'}. Result: {result or row['camel_thread_id']}. Please review, collect, merge and archive the completed work."
            sessions.require_text(text, "Completion message")
            row.update(phase=outcome, result=result, checks=checks, summary=message,
                       completion={"outcome": outcome, "text": text, "result_key": digest([row["id"], row.get("cycle", 0), outcome, result, checks, text])})
            write_json(_task_path(root), state)
        text = row["completion"]["text"]
        with factory("oasis_complete_" + row["id"]) as server:
            delivery = sessions.send_once(_delivery_path(root, row, "complete"), row["cameleer_thread_id"], text, server)
        row["completion"]["delivery"] = delivery
        write_json(_task_path(root), state)
        return copy.deepcopy(row)


def collect(target, task_id, *, result=None, checks=None, merge=None, merged_reference=None, factory=sessions.AppServer):
    """Collect a reviewed result; merge callbacks and native archives run once."""
    root, _ = _root(target)
    with operation_lock(contained(root, ".oasis/local/operations.lock")):
        state = _tasks(root)
        row = _task(state, task_id)
        completion = row.get("completion")
        if not completion:
            raise HarnessError("This task has no terminal result to collect")
        if row.get("collected_result_key") == completion["result_key"]:
            return copy.deepcopy(row)
        if result is not None:
            row["result"] = result
        if checks is not None:
            row["checks"] = checks
        if merged_reference is not None:
            row.update(merge_state="merged", result=merged_reference)
            write_json(_task_path(root), state)
        if completion["outcome"] != "completed":
            row["collected_result_key"] = completion["result_key"]
            write_json(_task_path(root), state)
            _render_tasks(root, state)
            return copy.deepcopy(row)
        if row.get("merge_state") in ("started", "uncertain"):
            if merged_reference is None:
                return {**copy.deepcopy(row), "phase": "merge_uncertain",
                        "instruction": "Inspect the retained merge outcome and resume with its actual merged reference."}
            row.update(merge_state="merged", result=merged_reference)
            write_json(_task_path(root), state)
        elif merge is not None and row.get("merge_state") != "merged":
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
        with factory("oasis_collect_" + row["id"]) as server:
            _thread(server, row["camel_thread_id"], root,
                    row.get("project_id") or read_json(row["session_receipt"])["project_id"])
            lifecycle = _lifecycle_once(_delivery_path(root, row, "archive"), row["camel_thread_id"], server, root,
                                       scoped={row["camel_thread_id"]})
        if lifecycle["state"] == "accepted":
            row.update(phase="archived", archived=True, collected_result_key=completion["result_key"])
        else:
            row["phase"] = "archive_uncertain"
        write_json(_task_path(root), state)
        _render_tasks(root, state)
        return copy.deepcopy(row)


def resume_task(target, task_id, message=None, *, planning=False, implementation=False, request_id=None, factory=sessions.AppServer):
    root, _ = _root(target)
    with operation_lock(contained(root, ".oasis/local/operations.lock")):
        state = _tasks(root)
        row = _task(state, task_id)
        if message is None and row.get("completion"):
            return copy.deepcopy(row)
        previous_archive = _delivery_path(root, row, "archive")
        if message is not None and not row.get("archived") and previous_archive.exists():
            archive_record = read_json(previous_archive)
            if archive_record.get("state") in ("accepted", "started", "uncertain"):
                with factory("oasis_restore_recover_" + row["id"]) as server:
                    archive_result = _lifecycle_once(previous_archive, row["camel_thread_id"], server, root,
                                                     scoped={row["camel_thread_id"]})
                if archive_result["state"] != "accepted":
                    return {**copy.deepcopy(row), "phase": "archive_uncertain",
                            "instruction": "Reconcile the retained archive outcome before delivering the follow-up."}
                row["archived"] = True
                write_json(_task_path(root), state)
        if not row.get("camel_thread_id"):
            receipt = read_json(row["session_receipt"])
            found = sessions.inspect(row["session_receipt"], factory)
            if not found.get("thread_id"):
                return {**copy.deepcopy(row), "phase": "creation_uncertain"}
            receipt["thread_id"] = found["thread_id"]
            sessions.create_metadata(row["session_receipt"], receipt, factory)
            row["camel_thread_id"] = found["thread_id"]
            write_json(_task_path(root), state)
        if message is None:
            with factory("oasis_resume_" + row["id"]) as server:
                _assign_delivery(root, row, server)
        else:
            sessions.require_text(message, "Follow-up request")
            request_key = request_id or digest([message, planning, implementation])
            if row.get("followup_key") == request_key and row.get("completion"):
                return copy.deepcopy(row)
            if row.get("followup_key") != request_key:
                row["history"].append({name: copy.deepcopy(row.get(name)) for name in ("cycle", "phase", "completion", "result", "checks")})
                row["cycle"] = row.get("cycle", 0) + 1
                row.update(followup_key=request_key, prompt=_completion_prompt(message), planning=planning, phase="resuming")
                for name in ("completion", "collected_result_key", "merge_state", "summary", "checks", "result"):
                    row.pop(name, None)
                write_json(_task_path(root), state)
            with factory("oasis_resume_" + row["id"]) as server:
                if row.get("archived"):
                    lifecycle = _lifecycle_once(_delivery_path(root, row, "restore"), row["camel_thread_id"], server, root, restore=True)
                    if lifecycle["state"] != "accepted":
                        return {**copy.deepcopy(row), "phase": "restore_uncertain"}
                    row["archived"] = False
                    write_json(_task_path(root), state)
                delivery = sessions.send_once(_delivery_path(root, row, "assign"), row["camel_thread_id"], row["prompt"], server,
                                              planning=planning, execution=implementation, skill=_role_skill(root, "Camel"))
                row.update(phase="assigned" if delivery["state"] == "accepted" else delivery["state"], assignment_delivery=delivery)
        row.pop("error", None)
        write_json(_task_path(root), state)
        _render_tasks(root, state)
        return copy.deepcopy(row)


def dependency_wait(target, producer_id, consumer_id, condition, *, request_id=None):
    root, _ = _root(target)
    for value, label in ((producer_id, "Producer chat ID"), (consumer_id, "Consumer chat ID"), (condition, "Dependency condition")):
        sessions.require_text(value, label)
    key = request_id or digest([producer_id, consumer_id, condition])
    with operation_lock(contained(root, ".oasis/local/operations.lock")):
        state = _tasks(root)
        row = next((row for row in state["dependencies"] if row.get("request_key") == key), None)
        if row is None:
            row = {"id": uuid.uuid4().hex, "request_key": key, "producer_thread_id": producer_id,
                   "consumer_thread_id": consumer_id, "condition": condition, "phase": "waiting"}
            state["dependencies"].append(row)
            write_json(_task_path(root), state)
        return {**copy.deepcopy(row), "end_turn": True}


def dependency_finish(target, dependency_id, *, outcome="completed", result=None, message=None, factory=sessions.AppServer):
    if outcome not in ("completed", "failed", "cancelled"):
        raise HarnessError("Dependency outcome must be completed, failed or cancelled")
    root, _ = _root(target)
    with operation_lock(contained(root, ".oasis/local/operations.lock")):
        state = _tasks(root)
        row = next((row for row in state["dependencies"] if row["id"] == dependency_id), None)
        if row is None:
            raise HarnessError("Unknown dependency ID")
        if row["phase"] == "waiting":
            row.update(phase=outcome, result=result, text=message or f"Dependency {outcome}: {row['condition']}. Result: {result or 'see producer chat ' + row['producer_thread_id']}.")
            write_json(_task_path(root), state)
        path = contained(root, f".oasis/local/tasks/dependencies/{row['id']}.json")
        with factory("oasis_dependency_" + row["id"]) as server:
            row["delivery"] = sessions.send_once(path, row["consumer_thread_id"], row["text"], server)
        write_json(_task_path(root), state)
        return copy.deepcopy(row)
