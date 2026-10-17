"""Read-only binding plans and journaled, metadata-only bootstrap recovery."""
from __future__ import annotations

from . import sessions
from .common import HarnessError, digest, read_json, write_json


def inspect(server, root, thread_id, backend, *, project_id=None, thread=None):
    if backend not in ("app-server", "desktop"):
        raise HarnessError("Project binding backend must be explicit")
    sessions.require_text(thread_id, "Project binding thread ID")
    project_id = project_id or sessions.project_id(server, root)
    thread = thread if thread is not None else server.call("thread/read", {"threadId": thread_id, "includeTurns": False})["thread"]
    binding = {"target": str(root), "project_id": project_id}
    state = sessions.thread_binding_state(thread, thread_id, binding)
    if state not in ("bound", "unassigned"):
        sessions.check_thread_binding(thread, thread_id, binding)
    return {**binding, "thread_id": thread_id, "backend": backend,
            "previous_project_id": thread["projectId"], "state": state}


def _read(server, check):
    if sessions.project_id(server, check["target"]) != check["project_id"]:
        raise HarnessError("Project binding catalog changed; prepare a fresh initialization plan")
    thread = server.call("thread/read", {"threadId": check["thread_id"], "includeTurns": False})["thread"]
    state = sessions.thread_binding_state(thread, check["thread_id"], check)
    if state not in ("bound", "unassigned"):
        sessions.check_thread_binding(thread, check["thread_id"], check)
    if state == "unassigned" and check["state"] == "bound":
        raise HarnessError("Project membership was removed after planning; prepare a fresh initialization plan")
    return thread, state


def apply(path, check, server):
    """Send at most once; subsequent calls reconcile the actual stored value."""
    fingerprint = digest(check)
    journal = read_json(path) if path.exists() else {"schema_version": 1, "plan_sha256": fingerprint, "state": "prepared"}
    if journal.get("plan_sha256") != fingerprint:
        raise HarnessError("Project binding recovery belongs to another reviewed plan")
    thread, state = _read(server, check)
    if state == "bound" and journal["state"] in ("prepared", "accepted"):
        return {"state": "accepted", "backend": check["backend"], "thread_id": check["thread_id"],
                "receipt": str(path) if path.exists() else None}
    if state == "unassigned" and journal["state"] == "accepted":
        raise HarnessError("Accepted project binding changed; inspect newer work before another initialization")
    if state == "unassigned" and journal["state"] == "prepared":
        settings, _ = sessions._actual_settings(server, check["thread_id"], thread=thread)
        params = {"threadId": check["thread_id"], "projectId": check["project_id"]}
        journal.update(state="issued", binding=check, before_project_id=None, settings_before=settings,
                       rpc={"method": "thread/metadata/update", "params": params, "outcome": "issued"})
        write_json(path, journal)
        try:
            response = server.call("thread/metadata/update", params)
            returned = response.get("thread") if isinstance(response, dict) else None
            journal["rpc"].update(outcome="returned", thread_id=returned.get("id") if isinstance(returned, dict) else None,
                                  project_id=returned.get("projectId") if isinstance(returned, dict) else None)
        except Exception as exc:
            journal["error"] = str(exc)
            journal["rpc"]["outcome"] = "rejected" if isinstance(exc, sessions.NativeError) else "uncertain"
            if getattr(exc, "code", None) in (-32601, -32602):
                journal["rejection_code"] = exc.code
        write_json(path, journal)
        try:
            thread, state = _read(server, check)
        except Exception as exc:
            journal.update(state="uncertain", readback_error=str(exc))
            write_json(path, journal)
            return {**journal, "receipt": str(path), "instruction": "Resume this retained initialization to re-read the existing chat; do not repeat its metadata mutation."}
    journal["observed_project_id"] = thread["projectId"]
    if state == "bound":
        settings, _ = sessions._actual_settings(server, check["thread_id"], thread=thread)
        journal["settings_after"] = settings
        if settings != journal.get("settings_before"):
            journal["state"] = "settings_changed"
            write_json(path, journal)
            raise HarnessError("Project metadata readback found changed model/permission selections; preserve them and inspect the binding receipt")
        journal["state"] = "accepted"
        journal.pop("instruction", None)
    else:
        journal["state"] = "unsupported" if journal.get("rejection_code") in (-32601, -32602) else "not_applied"
        journal["instruction"] = (
            "The existing chat is still unassigned. Inspect the retained receipt and this host's thread/metadata/update projectId support. "
            "Repair its App Server membership through a supported existing host, verify thread/read, then resume this initialization. "
            "Desktop membership uses its own project ID; moving the sidebar chat alone does not verify App Server membership."
            if check["backend"] == "app-server" else
            "The existing chat is still unassigned in Desktop. Use its supported move_thread_to_project with the matching Desktop project ID, "
            "verify actual projectId in list_threads, then resume this retained initialization. App Server membership is checked separately."
        ) + " No request is replayed and no alternate host is started."
    write_json(path, journal)
    return {**journal, "receipt": str(path)}
