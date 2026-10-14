"""Workflow-scoped I/O owner. Never starts a server or asks a model to wait."""
from __future__ import annotations

import contextlib
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import uuid

from . import sessions
from .common import HarnessError, clean_environment, contained, digest, file_hash, is_reparse, read_json, write_json

DEFAULT_LIFETIME = 24 * 60 * 60
DEBOUNCE = 0.25
MAX_DELAY = 1.0
MIN_QUERY_INTERVAL = 5.0
IDLE_GRACE = 60.0


class _OwnerBusy(HarnessError):
    pass


class _CleanupError(HarnessError):
    pass


def _backend():
    # Persist a fingerprint, never an endpoint credential or account setting.
    endpoint = os.environ.get("OASIS_APP_SERVER_URL")
    home = sessions.canonical_root(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    if endpoint is not None:
        address, port, target, _ = sessions._LoopbackWebSocket.endpoint(endpoint)
        return digest({"backend": "websocket", "endpoint": [address, port, target], "codex_home": home})
    socket_path = os.environ.get("OASIS_APP_SERVER_SOCKET")
    executable = shutil.which("codex")
    return digest({"backend": "proxy", "socket": sessions.canonical_root(socket_path) if socket_path else None,
                   "codex_home": home, "executable": sessions.canonical_root(executable) if executable else None})


def _environment():
    # Child cwd is the package location, so resolve selected relative paths now.
    extra = {key: sessions.canonical_root(os.environ[key]) for key in ("CODEX_HOME", "OASIS_APP_SERVER_SOCKET")
             if os.environ.get(key)}
    return clean_environment(extra)


def _directory(root):
    return contained(root, ".oasis/local/notifications/" + _backend())


def _identity(pid):
    """PID reuse is not ownership: retain birth and actual executable identity."""
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return None
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel.GetProcessTimes.argtypes = (wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4))
            kernel.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD,
                                                         wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                return None
            try:
                created, ended, system, user = (wintypes.FILETIME() for _ in range(4))
                if not kernel.GetProcessTimes(handle, created, ended, system, user):
                    return None
                executable = ctypes.create_unicode_buffer(32768)
                length = wintypes.DWORD(len(executable))
                if not kernel.QueryFullProcessImageNameW(handle, 0, executable, ctypes.byref(length)):
                    return None
                return {"pid": pid, "birth": str((created.dwHighDateTime << 32) | created.dwLowDateTime),
                        "executable": os.path.normcase(executable.value)}
            finally:
                kernel.CloseHandle(handle)
        process = Path("/proc") / str(pid)
        # comm may contain spaces and parentheses; fields start after its last ')'.
        fields = (process / "stat").read_text().rsplit(")", 1)[1].split()
        return {"pid": pid, "birth": fields[19], "executable": str((process / "exe").resolve(strict=True))}
    except (OSError, ValueError, IndexError):
        return None


@contextlib.contextmanager
def _lock(path):
    """OS-held locks disappear with their owner; durable files are not leases."""
    if path.is_symlink() or is_reparse(path):
        raise HarnessError("Linked notification ownership files are not supported")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise _OwnerBusy("Notification owner is already active") from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextlib.contextmanager
def _wait_lock(path, timeout=5):
    deadline = time.monotonic() + sessions.remaining_timeout(timeout)
    while True:
        lock = _lock(path)
        try:
            lock.__enter__()
            break
        except _OwnerBusy:
            if time.monotonic() >= deadline:
                raise
            time.sleep(min(0.02, max(0, deadline - time.monotonic())))
    try:
        yield
    finally:
        lock.__exit__(None, None, None)


def _journal_stamp(root):
    try:
        return file_hash(contained(root, ".oasis/local/tasks/state.json"))
    except FileNotFoundError:
        return None


def _read(root):
    path = contained(_directory(root), "state.json")
    if not path.exists():
        return None
    row = read_json(path)
    if (not isinstance(row, dict) or row.get("schema_version") != 1
            or row.get("backend") != _backend()
            or not isinstance(row.get("target"), str)
            or sessions.canonical_root(row.get("target", "")) != sessions.canonical_root(root)
            or not isinstance(row.get("token"), str) or not isinstance(row.get("status"), str)
            or not isinstance(row.get("process"), dict)
            or isinstance(row.get("generation"), bool) or not isinstance(row.get("generation"), int)
            or row["generation"] < 1
            or isinstance(row.get("expires_at"), bool)
            or not isinstance(row.get("expires_at"), (int, float))
            or not math.isfinite(row["expires_at"])):
        raise HarnessError("Invalid notification ownership state; preserve it before recovery")
    process = row["process"]
    if ("pid" in process and (isinstance(process["pid"], bool) or not isinstance(process["pid"], int)
                              or process["pid"] <= 0)
            or any(key in process and not isinstance(process[key], str) for key in ("birth", "executable"))):
        raise HarnessError("Invalid notification process identity; preserve it before recovery")
    return row


def status(root):
    """Read-only diagnostics; this does not launch, renew or recover an owner."""
    root = Path(root).resolve()
    row = _read(root)
    if row is None:
        return {"status": "not_started", "next_action": "Run the pending task or dependency command to resume observation"}
    result = dict(row)
    process = row["process"]
    result["owner_verified"] = bool(process and _identity(process.get("pid", 0)) == process)
    if row["status"] in ("starting", "running") and not result["owner_verified"]:
        result["status"] = "recovery_required"
        result["next_action"] = "Run the pending task or dependency command; its next invocation reconciles retained state"
    elif row["status"] == "running" and result["owner_verified"] and row.get("ipc"):
        from . import shared_runtime
        current = shared_runtime.read_diagnostics(root, row)
        if current:
            result["diagnostics"] = current
    return result


def ensure_running(root, *, lifetime=DEFAULT_LIFETIME):
    """Start only this project's transient observer; injected workflows opt out."""
    if isinstance(lifetime, bool) or not isinstance(lifetime, (int, float)) or not math.isfinite(lifetime) or lifetime <= 0:
        raise HarnessError("Notification lifetime must be finite and positive")
    root = Path(root).resolve()
    directory = _directory(root)
    try:
        with _wait_lock(directory / "start.lock"):
            try:
                with _lock(directory / "owner.lock"):
                    pass
            except _OwnerBusy:
                return status(root)
            previous = _read(root)
            if previous and previous["status"] == "starting" and _identity(previous["process"].get("pid", 0)) == previous["process"]:
                return status(root)
            token = uuid.uuid4().hex
            now = time.time()
            from .shared_runtime import PROTOCOL
            row = {"schema_version": 1, "target": str(root), "backend": _backend(), "token": token,
                   "generation": (previous or {}).get("generation", 0) + 1,
                   "shared_protocol": PROTOCOL,
                   "status": "starting", "created_at": now, "expires_at": now + lifetime,
                   "process": {}, "next_action": "The I/O owner will observe pending transitions without model requests"}
            # The worker takes start.lock before reading this record, closing its startup race.
            write_json(directory / "state.json", row)
            command = [sys.executable, "-B", "-X", "utf8", "-m", "oasis_harness.notifications", str(root), token]
            try:
                child = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[1],
                                         env=_environment(), stdin=subprocess.DEVNULL,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
                                         start_new_session=os.name != "nt")
                row["process"] = _identity(child.pid) or {"pid": child.pid}
                write_json(directory / "state.json", row)
                # Reap only our child when it exits; no polling or parent-turn lease.
                threading.Thread(target=child.wait, name="oasis-notification-child", daemon=True).start()
            except OSError as exc:
                row.update(status="recovery_required", error=f"Observer launch failed: {type(exc).__name__}",
                           next_action="Run the pending task or dependency command to retry observer launch")
                write_json(directory / "state.json", row)
                return row
            return row
    except _OwnerBusy:
        return {"status": "recovery_required", "next_action": "Notification startup/shutdown lock did not release; run the pending command to resume"}


def _save(root, token, **updates):
    row = _read(root)
    if row is None or row["token"] != token:
        raise HarnessError("Notification generation changed; this observer no longer owns the journal")
    row.update(updates)
    write_json(_directory(root) / "state.json", row)
    return row


def _relevant(events, watches, targets, journal, *, waiting_for_writer=False):
    changed, journal_changed = set(), False
    if not isinstance(events, list):
        raise HarnessError("Native notification batch must be a list")
    for event in events:
        if not isinstance(event, dict):
            raise HarnessError("Native notification must be an object")
        params = event.get("params", {})
        if event.get("method") not in ("fs/changed", "turn/completed", "thread/status/changed", "item/completed"):
            continue
        if not isinstance(params, dict):
            raise HarnessError("Native transition parameters must be an object")
        if event.get("method") == "fs/changed":
            watched = watches.get(params.get("watchId"))
            if watched is None:
                continue
            if watched["thread_id"] is None:
                if watched.get("event_kind") == "unlock" and not waiting_for_writer:
                    continue
                paths = params.get("changedPaths", [])
                expected = watched.get("event_path", str(journal))
                journal_changed |= any(sessions.canonical_root(path) == sessions.canonical_root(expected)
                                       for path in paths if isinstance(path, str))
            else:
                if not targets.get(watched["thread_id"], {}).get("event_covered"):
                    changed.add(watched["thread_id"])
        else:
            identity = params.get("threadId")
            expected = targets.get(identity)
            if expected is None:
                continue
            turn = params.get("turn", {})
            if event["method"] == "thread/status/changed":
                status = params.get("status") or {}
                if not isinstance(status, dict):
                    raise HarnessError("Native thread status transition must be an object")
                if not (expected.get("idle_only") or expected.get("awaiting_idle")) or status.get("type") not in ("idle", "notLoaded"):
                    continue
            elif event["method"] == "item/completed":
                item = params.get("item") or {}
                if not isinstance(item, dict):
                    raise HarnessError("Native completed item must be an object")
                if (params.get("turnId") != expected.get("turn_id")
                        or item.get("type") != "agentMessage" or item.get("phase") != "final_answer"):
                    continue
            else:
                if not isinstance(turn, dict):
                    raise HarnessError("Native completed turn must be an object")
                if expected.get("turn_id") and turn.get("id") != expected["turn_id"]:
                    continue
            changed.add(identity)
    return changed, journal_changed


def _watch(server, watches, targets, journal):
    operation = journal.parent.parent / "operations.lock"
    desired = {str(journal.parent): {"thread_id": None, "path": str(journal.parent), "event_path": str(journal)},
               str(operation.parent): {"thread_id": None, "path": str(operation.parent), "event_path": str(operation),
                                      "event_kind": "unlock"}}
    desired.update({row["path"]: row for row in targets.values() if not row.get("event_covered")})
    added = set()
    for watch_id, row in list(watches.items()):
        if row["path"] not in desired:
            server.call("fs/unwatch", {"watchId": watch_id})
            del watches[watch_id]
    present = {row["path"] for row in watches.values()}
    for path, row in desired.items():
        if path in present:
            continue
        watch_id = "oasis-notify-" + uuid.uuid4().hex
        answer = server.call("fs/watch", {"watchId": watch_id, "path": path})
        if sessions.canonical_root(answer.get("path", "")) != sessions.canonical_root(path):
            raise HarnessError("Notification watch returned a different path")
        watches[watch_id] = row
        added.add(row["thread_id"])
    return added


def _busy(exc):
    return isinstance(exc, HarnessError) and "Operation is already locked:" in str(exc)


def _observe(root, server, deadline, step, stop_guard=None, *, runtime=None):
    journal = contained(root, ".oasis/local/tasks/state.json")
    journal.parent.mkdir(parents=True, exist_ok=True)
    if not callable(getattr(server, "wait_events", None)):
        raise sessions.NativeError("fs/watch", {"code": -32601, "message": "Event observation unavailable"})
    cache, watches, targets = {}, {}, {}
    changed, dirty, last_step = None, True, -math.inf
    primary = None
    waiting_for_writer = False
    pending, consumed, idle_since = True, None, None
    reason = "initial"
    last_query, deferred = {}, {}

    def fallback_due(identity):
        row = deferred[identity]
        return max(min(row["first"] + MAX_DELAY, row["last"] + DEBOUNCE),
                   last_query.get(identity, -math.inf) + MIN_QUERY_INTERVAL)

    def transitions(events):
        fallback, journal_event = _relevant([event for event in events if event.get("method") == "fs/changed"],
            watches, targets, journal, waiting_for_writer=waiting_for_writer)
        native, _ = _relevant([event for event in events if event.get("method") != "fs/changed"],
            watches, targets, journal, waiting_for_writer=waiting_for_writer)
        now = time.monotonic()
        for identity in fallback - native:
            row = deferred.setdefault(identity, {"first": now, "last": now})
            row["last"] = now
        for identity in native:
            deferred.pop(identity, None)
        if any(event.get("method") == "oasis/shared/activity" for event in events) and _journal_stamp(root) != consumed:
            journal_event = True
        return native, journal_event

    def due_fallbacks():
        ready = {identity for identity in deferred if fallback_due(identity) <= time.monotonic()}
        for identity in ready:
            del deferred[identity]
        return ready

    try:
        while time.monotonic() < deadline:
            if dirty:
                consumed = _journal_stamp(root)
                record = getattr(server, "record_reconciliation", None)
                if callable(record):
                    record(reason)
                try:
                    with sessions.deadline_scope(timeout=min(30, max(0, deadline - time.monotonic()))):
                        result = step(root, server, changed_threads=changed, cache=cache)
                    waiting_for_writer = False
                except HarnessError as exc:
                    if not _busy(exc):
                        raise
                    # The writer's durable journal event is the next retry trigger.
                    result = {"pending": True, "targets": list(targets.values())}
                    waiting_for_writer = True
                queried = set(targets) if changed is None else changed
                last_step, dirty, changed = time.monotonic(), False, set()
                pending = result["pending"]
                if not pending and runtime is None:
                    if stop_guard is not None and not stop_guard(consumed):
                        changed, dirty = None, True
                        reason = "shutdown_changed"
                        continue
                    return "stopped", result.get("next_action", "All registered notifications are resolved")
                if pending:
                    idle_since = None
                elif idle_since is None:
                    idle_since = time.monotonic()
                previous = targets
                targets = {row["thread_id"]: row for row in result.get("targets", [])} if pending else {}
                for identity in queried | (targets.keys() - previous.keys()):
                    last_query[identity] = last_step
                    deferred.pop(identity, None)
                for identity in set(deferred) - targets.keys():
                    del deferred[identity]
                with sessions.deadline_scope(timeout=min(30, max(0, deadline - time.monotonic()))):
                    added = _watch(server, watches, targets, journal)
                if added:
                    changed, dirty = added - {None}, True
                    reason = "registration"
                    continue  # One post-registration read closes the event-registration race.
            ready = due_fallbacks()
            if ready:
                changed, dirty, reason = ready, True, "fallback_change"
                continue
            until = min([deadline, *(fallback_due(identity) for identity in deferred)])
            if not pending and runtime is not None:
                if runtime.busy():
                    idle_since = time.monotonic()
                else:
                    until = min(until, max(idle_since, runtime.last_activity) + IDLE_GRACE)
                    if time.monotonic() >= until:
                        if stop_guard is None or stop_guard(consumed):
                            return "stopped", "All registered work is resolved; shared connection idle grace ended"
                        changed, dirty = None, True
                        reason = "shutdown_changed"
                        idle_since = time.monotonic()
                        continue
            events = server.wait_events(max(0, until - time.monotonic()))
            if not events and time.monotonic() >= until:
                continue
            if not events:
                raise HarnessError("Native event connection ended before a transition; reconcile once")
            native, journal_changed = transitions(events)
            if not native and not journal_changed:
                continue
            changed.update(native)
            native_change = bool(native)
            first, latest = time.monotonic(), time.monotonic()
            # Coalesce actual input only. This timer never queries native/model status.
            while True:
                now = time.monotonic()
                due = min(first + MAX_DELAY, latest + DEBOUNCE)
                if now >= min(due, deadline):
                    break
                batch = server.wait_events(max(0, min(due, deadline) - now))
                if not batch and time.monotonic() < min(due, deadline):
                    raise HarnessError("Native event connection ended while merging transitions; reconcile once")
                more, journal_event = transitions(batch)
                native_change |= bool(more)
                if more or journal_event:
                    changed.update(more)
                    latest = time.monotonic()
            changed.update(due_fallbacks())
            dirty = True
            reason = "native_transition" if native_change else "fallback_change" if changed else "journal_change"
        return "expired", "Observation lifetime ended; run the pending task or dependency command to reconcile and resume"
    except BaseException as exc:
        primary = exc
        raise
    finally:
        errors = []
        if time.monotonic() < deadline:
            with sessions.deadline_scope(timeout=min(1, deadline - time.monotonic())):
                for watch_id in watches:
                    try:
                        server.call("fs/unwatch", {"watchId": watch_id})
                    except HarnessError as exc:
                        errors.append(str(exc))
        if errors:
            if primary is None:
                raise _CleanupError("Notification cleanup failed; retained tasks can be resumed: " + errors[0])
            # A dead channel often rejects unwatch too. Preserve that evidence
            # without hiding the primary connection loss and its one recovery.
            primary.notification_cleanup_error = errors[0]


def run(root, token, *, factory=None, step=None):
    """Own one bounded connection; one reconnect, no mutation replay or model waits."""
    from . import workflows
    root = Path(root).resolve()
    directory = _directory(root)
    production = factory is None
    factory = factory or sessions.command_server
    step = step or workflows.notification_step
    shutdown = contextlib.ExitStack()
    try:
        with shutdown, _lock(directory / "owner.lock"):
            # Parent writes the child's verified identity while holding start.lock.
            start_until = time.monotonic() + 5
            while True:
                try:
                    with _lock(directory / "start.lock"):
                        row = _read(root)
                    break
                except _OwnerBusy:
                    if time.monotonic() >= start_until:
                        return {"status": "recovery_required", "next_action": "Observer startup lock did not release"}
                    time.sleep(0.02)
            if row is None or row["token"] != token:
                return {"status": "superseded"}
            identity = _identity(os.getpid())
            claimed = row["process"]
            if (identity is None or claimed.get("pid") != os.getpid()
                    or any(key in claimed and claimed[key] != identity[key] for key in ("birth", "executable"))):
                return _save(root, token, status="recovery_required", next_action="Observer process identity could not be verified")
            row = _save(root, token, status="running", process=identity)
            deadline = time.monotonic() + max(0, row["expires_at"] - time.time())
            if time.monotonic() >= deadline:
                return _save(root, token, status="expired", next_action="Observation lifetime ended; run the pending task or dependency command to reconcile and resume")
            cleanup_errors = []
            closing = False
            runtime_owner = None

            def stop_guard(consumed):
                nonlocal closing
                candidate = contextlib.ExitStack()
                try:
                    candidate.enter_context(_wait_lock(directory / "start.lock"))
                    if _journal_stamp(root) != consumed:
                        candidate.close()
                        return False
                    if runtime_owner is not None and not runtime_owner.begin_shutdown():
                        candidate.close()
                        return False
                    # Release owner.lock before this startup/shutdown barrier.
                    shutdown.callback(candidate.close)
                    closing = True
                    return True
                except BaseException:
                    candidate.close()
                    raise

            for attempt in range(2):
                diagnostics = {}
                try:
                    with sessions.deadline_scope(deadline=deadline):
                        if production:
                            from . import shared_runtime
                            with contextlib.closing(shared_runtime.Pool()) as pool:
                                with shared_runtime.Host(root, token, row["generation"], pool) as runtime_owner:
                                    _save(root, token, ipc=runtime_owner.descriptor(), connection_mode="shared")
                                    server = pool.facade("oasis-notifications")
                                    try:
                                        final, action = _observe(root, server, deadline, step, stop_guard, runtime=runtime_owner)
                                    finally:
                                        diagnostics = pool.diagnostics()
                        else:
                            with factory("oasis-notifications") as server:
                                final, action = _observe(root, server, deadline, step, stop_guard)
                            diagnostics = {"connection_mode": "direct"}
                    return _save(root, token, status=final, next_action=action, reconnects=attempt,
                                 cleanup_errors=cleanup_errors, diagnostics=diagnostics)
                except HarnessError as exc:
                    if getattr(exc, "notification_cleanup_error", None):
                        cleanup_errors.append(exc.notification_cleanup_error)
                    unsupported = isinstance(exc, sessions.NativeError) and exc.code == -32601
                    if unsupported or closing or isinstance(exc, _CleanupError) or attempt == 1 or time.monotonic() >= deadline:
                        expired = isinstance(exc, sessions.DeadlineExceeded) and time.monotonic() >= deadline
                        return _save(root, token, status="expired" if expired else "unsupported" if unsupported else "recovery_required",
                                     error=str(exc), reconnects=attempt,
                                     cleanup_errors=cleanup_errors, diagnostics=diagnostics,
                                     next_action="Run the pending task or dependency command to reconcile retained state; do not poll with a model")
    except _OwnerBusy:
        return {"status": "already_running"}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Internal observer requires a project path and generation token")
    try:
        run(sys.argv[1], sys.argv[2])
    except HarnessError:
        # Operational details stay in private state, never public model prompts.
        raise SystemExit(1)
