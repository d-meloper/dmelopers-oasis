"""Bounded local command leases in the existing transient notification owner.

Only byte frames cross IPC. This module neither starts an App Server nor owns
another process; the notification owner supplies its lifetime and generation.
"""
from __future__ import annotations

from collections import deque
import contextlib
import hashlib
import hmac
import json
import math
from multiprocessing.connection import Client as PipeClient, Listener
import os
from pathlib import Path
import queue
import sys
import threading
import time
import uuid

from . import sessions
from .common import HarnessError, digest

PROTOCOL = 1
MAX_BYTES = 64 * 1024 * 1024
MAX_CLIENTS = 32
IDLE_SECONDS = 60
_READ_METHODS = frozenset(("thread/read", "thread/list", "thread/turns/list", "thread/items/list"))


def runtime_identity(root):
    from . import notifications
    modules = ("sessions.py", "shared_runtime.py", "notifications.py", "workflows.py", "desktop_tools.py", "desktop_sessions.py")
    source = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in modules}
    return digest({"protocol": PROTOCOL, "root": sessions.canonical_root(root), "backend": notifications._backend(root),
                   "python": sessions.canonical_root(sys.executable), "version": list(sys.version_info[:3]),
                   "package": sessions.__version__, "source": source})


def _encode(value):
    try:
        result = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise HarnessError("Shared command is not bounded JSON") from None
    if len(result) > MAX_BYTES:
        raise HarnessError("Shared command frame exceeds the supported size")
    return result


def _decode(value):
    def fields(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = item
        return result
    try:
        result = json.loads(value.decode("utf-8"), object_pairs_hook=fields,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Invalid number")))
    except (UnicodeError, ValueError, RecursionError):
        raise HarnessError("Shared command returned invalid UTF-8 JSON") from None
    if not isinstance(result, dict):
        raise HarnessError("Shared command frame must be an object")
    return result


def _bounded(action, timeout, *, late_close=False, cancel=None):
    """Bound pipe open/write/read without changing another caller's connection."""
    result = queue.Queue(maxsize=1)
    expired = threading.Event()
    def run():
        try:
            value = action()
            if expired.is_set() and late_close:
                value.close()
            result.put_nowait((True, value))
        except BaseException as exc:
            result.put_nowait((False, exc))
    threading.Thread(target=run, name="oasis-shared-io", daemon=True).start()
    try:
        success, value = result.get(timeout=max(0, timeout))
    except queue.Empty:
        expired.set()
        if cancel is not None:
            with contextlib.suppress(OSError):
                cancel()
        raise sessions.DeadlineExceeded("Shared command deadline expired; reconcile retained receipts before another mutation") from None
    if not success:
        raise value
    return value


def _same_user(connection, *, server_side):
    if os.name != "nt":
        # Non-Windows endpoints live in the caller-owned private project folder.
        return True
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    peer = wintypes.ULONG()
    method = kernel.GetNamedPipeClientProcessId if server_side else kernel.GetNamedPipeServerProcessId
    method.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG))
    method.restype = wintypes.BOOL
    if not method(connection.fileno(), ctypes.byref(peer)):
        return False
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    advapi.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
    advapi.GetTokenInformation.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                          ctypes.POINTER(wintypes.DWORD))
    advapi.GetLengthSid.argtypes = (ctypes.c_void_p,)
    advapi.GetLengthSid.restype = wintypes.DWORD
    def sid(pid):
        process = kernel.OpenProcess(0x1000, False, pid)
        if not process:
            return None
        token = wintypes.HANDLE()
        try:
            if not advapi.OpenProcessToken(process, 8, ctypes.byref(token)):
                return None
            needed = wintypes.DWORD()
            advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
            buffer = ctypes.create_string_buffer(needed.value)
            if not advapi.GetTokenInformation(token, 1, buffer, needed, ctypes.byref(needed)):
                return None
            address = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
            return ctypes.string_at(address, advapi.GetLengthSid(address))
        finally:
            if token:
                kernel.CloseHandle(token)
            kernel.CloseHandle(process)
    actual, expected = sid(peer.value), sid(os.getpid())
    return actual is not None and expected is not None and hmac.compare_digest(actual, expected)


class Pool:
    """Originator-preserving upstreams with one aggregate native event reader."""
    def __init__(self, factory=None):
        self.factory = factory or sessions.observer_server
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.channels = {}
        self.creating = {}
        self.subscriptions = {}
        self.events = deque()
        self.event_bytes = 0
        self.event_error = None
        self.closed = False
        self.leases = 0
        self.pending_count = 0
        self.last_activity = time.monotonic()
        self.inflight = {}
        self.counts = {}
        self.ipc_requests = 0
        self.coalesced_reads = 0
        self.reconciliations = {}
        self.listeners = set()
        self.active_turns = set()
        self.completed_turns = deque(maxlen=4096)
        self.issued_turns = {}
        self.starting_turns = {}
        self.idle_marks = {}
        self.lifetime_requests = {}
        self.lifetime_workers = {}
        self.lifetime_failures = set()

    def notify_activity(self):
        with self.changed:
            self.last_activity = time.monotonic()
            # One pending activity signal is sufficient for any number of leases.
            if not any(value.get("method") == "oasis/shared/activity" for value in self.events):
                self.events.append({"method": "oasis/shared/activity", "params": {}})
            self.changed.notify_all()

    def acquire(self):
        with self.lock:
            if self.closed:
                raise HarnessError("Shared connection owner has ended")
            self.leases += 1
            self.notify_activity()

    def release(self):
        with self.lock:
            self.leases = max(0, self.leases - 1)
            self.notify_activity()

    def busy(self):
        with self.lock:
            return bool(self.leases or self.pending_count or self.creating or self.active_turns or self.lifetime_workers)

    def record_reconciliation(self, reason):
        with self.lock:
            self.reconciliations[reason] = self.reconciliations.get(reason, 0) + 1

    def facade(self, originator="oasis-notifications", *, read_epoch=None):
        return _Facade(self, originator, read_epoch=read_epoch)

    def event_covered(self, thread_id):
        with self.lock:
            channel = self.subscriptions.get(thread_id)
            return bool(channel in self.channels and self.channels[channel].get("alive"))

    subscribed = event_covered

    def listen(self, originator):
        listener = _Events(originator)
        with self.lock:
            if self.closed:
                raise HarnessError("Shared event owner has ended")
            self.listeners.add(listener)
        return listener

    def unlisten(self, listener):
        with self.lock:
            self.listeners.discard(listener)
        listener.inbox.end("Shared command event lease ended")

    def _finish_turn(self, key):
        self.active_turns.discard(key)
        self.issued_turns.pop(key, None)
        self.completed_turns.append(key)
        if not any(item[0] == key[0] for item in self.issued_turns):
            self.idle_marks.pop(key[0], None)
            self.lifetime_failures.discard(key[0])

    def _idle_check(self, originator, thread_id, status):
        keys = frozenset(key for key, channel in self.issued_turns.items()
                         if key[0] == thread_id and channel == originator and key in self.active_turns)
        if not keys:
            return
        if status == "active":
            self.idle_marks.pop(thread_id, None)
            return
        if status not in ("idle", "notLoaded") or self.idle_marks.get(thread_id) == keys:
            return
        self.idle_marks[thread_id] = keys
        self.lifetime_requests[thread_id] = originator, keys
        if thread_id not in self.lifetime_workers:
            worker = threading.Thread(target=self._verify_issued, args=(thread_id,), daemon=True,
                                      name="oasis-issued-turn-boundary")
            self.lifetime_workers[thread_id] = worker
            worker.start()

    def _verify_issued(self, thread_id):
        # A global idle signal precedes durable terminal data on some backends.
        # One event-driven debounce is not a status-query loop.
        time.sleep(0.25)
        while True:
            with self.changed:
                request = self.lifetime_requests.pop(thread_id, None)
                if self.closed or request is None:
                    self.lifetime_workers.pop(thread_id, None)
                    if self.closed:
                        self.changed.notify_all()
                    else:
                        self.notify_activity()
                    return
            originator, keys = request
            with self.lock:
                if not any(key in self.active_turns for key in keys):
                    continue
            try:
                self.record_reconciliation("issued_turn_idle")
                with sessions.deadline_scope(timeout=5):
                    page = self.call(originator, "thread/turns/list", {
                        "threadId": thread_id, "itemsView": "notLoaded", "sortDirection": "desc", "limit": 100}, timeout=5)
                    sessions._history_page(page, "thread/turns/list")
                with self.lock:
                    found = {(thread_id, turn["id"]) for turn in page["data"] if isinstance(turn.get("id"), str)}
                    if any(key in self.active_turns and key not in found for key in keys):
                        self.lifetime_failures.add(thread_id)
                    else:
                        self.lifetime_failures.discard(thread_id)
            except (HarnessError, OSError):
                with self.lock:
                    if not self.closed:
                        self.lifetime_failures.add(thread_id)
            # A second pass requires a distinct idle transition/new turn that
            # arrived during I/O; unchanged idle notifications are coalesced.

    def _turn_event(self, event, originator=None):
        method, params = event.get("method"), event.get("params", {})
        if method == "thread/status/changed" and isinstance(params, dict):
            status = params.get("status")
            if isinstance(status, dict):
                thread_id, state = params.get("threadId"), status.get("type")
                pending = self.starting_turns.get((originator, thread_id), {})
                for token in pending:
                    pending[token] = state
                self._idle_check(originator, thread_id, state)
            return
        if method not in ("turn/started", "turn/completed") or not isinstance(params, dict):
            return
        thread_id, turn = params.get("threadId"), params.get("turn")
        turn_id = turn.get("id") if isinstance(turn, dict) else None
        if not isinstance(thread_id, str) or not isinstance(turn_id, str):
            return
        key = (thread_id, turn_id)
        before = key in self.active_turns
        if method == "turn/completed":
            self._finish_turn(key)
        elif thread_id in self.subscriptions and key not in self.completed_turns:
            self.active_turns.add(key)
        if before != (key in self.active_turns):
            self.notify_activity()

    def _turn_response(self, method, params, value, *, channel=None):
        if not isinstance(value, dict):
            return
        if method == "turn/start":
            turn = value.get("turn") or {}
            if not isinstance(turn, dict):
                return
            key = (params.get("threadId"), turn.get("id"))
            if all(isinstance(item, str) and item for item in key):
                if turn.get("status") in ("completed", "failed", "interrupted"):
                    self._finish_turn(key)
                elif key not in self.completed_turns:
                    self.active_turns.add(key)
                    if channel is not None and key[0] not in self.subscriptions:
                        self.issued_turns[key] = channel
                        self.idle_marks.pop(key[0], None)
        elif method == "thread/read":
            thread = value.get("thread") or {}
            if not isinstance(thread, dict):
                return
            status = thread.get("status") or {}
            if not isinstance(status, dict) or status.get("type") not in ("idle", "notLoaded"):
                return
            for turn in thread.get("turns") or []:
                if (isinstance(turn, dict) and isinstance(turn.get("id"), str)
                        and turn.get("status") in ("completed", "failed", "interrupted")):
                    self._finish_turn((thread.get("id"), turn.get("id")))
        elif method == "thread/turns/list" and isinstance(value.get("data"), list):
            for turn in value["data"]:
                if (isinstance(turn, dict) and isinstance(turn.get("id"), str)
                        and turn.get("status") in ("completed", "failed", "interrupted")):
                    key = (params.get("threadId"), turn.get("id"))
                    if key in self.active_turns:
                        self._finish_turn(key)
                        self.notify_activity()

    def _initialize(self, originator, ready):
        token = sessions._operation_deadline.set(None)
        try:
            server = self.factory(originator)
            with self.lock:
                if self.closed:
                    server.close()
                    raise HarnessError("Shared connection owner ended during initialization")
                row = {"server": server, "alive": True}
                self.channels[originator] = row
                ready["server"] = server
                reader = threading.Thread(target=self._events, args=(originator, server), daemon=True,
                                          name="oasis-shared-native-events")
                row["reader"] = reader
                reader.start()
        except BaseException as exc:
            ready["error"] = exc
        finally:
            sessions._operation_deadline.reset(token)
            with self.changed:
                self.creating.pop(originator, None)
                ready["done"].set()
                self.changed.notify_all()

    def _server(self, originator, deadline):
        with self.lock:
            if self.closed:
                raise HarnessError("Shared connection owner has ended")
            if originator in self.channels:
                return self.channels[originator]["server"]
            ready = self.creating.get(originator)
            if ready is None:
                ready = {"done": threading.Event()}
                self.creating[originator] = ready
                worker = threading.Thread(target=self._initialize, args=(originator, ready), daemon=True,
                                          name="oasis-shared-initialize")
                ready["thread"] = worker
                worker.start()
        if not ready["done"].wait(max(0, deadline - time.monotonic())):
            raise sessions.DeadlineExceeded("Shared upstream initialization deadline expired")
        if "error" in ready:
            raise ready["error"]
        return ready["server"]

    def _events(self, originator, server):
        try:
            while not self.closed:
                batch = server.wait_events(30)
                with self.changed:
                    for value in batch:
                        self._turn_event(value, originator)
                        size = len(_encode(value))
                        if len(self.events) >= 4096 or self.event_bytes + size > MAX_BYTES:
                            raise HarnessError("Shared native event buffer overflow")
                        self.events.append(value)
                        self.event_bytes += size
                        for listener in self.listeners:
                            if originator in listener.channels and listener.inbox.state == "connected":
                                try:
                                    listener.inbox.notification(value, size)
                                except HarnessError as exc:
                                    listener.inbox.end(str(exc), failed=True, event_error=True)
                    if batch:
                        self.changed.notify_all()
                if not batch:
                    diagnostics = getattr(server, "diagnostics", lambda: {})()
                    if diagnostics.get("state") in ("closed", "failed"):
                        raise HarnessError("Shared native event connection ended; reconcile retained work")
        except (OSError, HarnessError) as exc:
            with self.changed:
                if not self.closed:
                    self.channels[originator]["alive"] = False
                    self.event_error = str(exc)
                    for listener in self.listeners:
                        if originator in listener.channels:
                            listener.inbox.end(str(exc), failed=True, event_error=True)
                    self.changed.notify_all()

    def call(self, originator, method, params, timeout=30, *, read_epoch=None, listener=None):
        timeout = sessions.remaining_timeout(timeout)
        deadline = time.monotonic() + timeout
        sessions.require_text(originator, "Shared upstream originator")
        sessions.require_text(method, "Shared RPC method")
        if not isinstance(params, dict):
            raise HarnessError("Shared RPC params must be an object")
        with self.lock:
            # An observed/loaded thread belongs to its actual originating client.
            channel = self.subscriptions.get(params.get("threadId"), originator)
            if listener is not None:
                listener.channels.add(channel)
            self.pending_count += 1
            self.notify_activity()
        try:
            server = self._server(channel, deadline)
            # A writer-boundary validation never joins a prior observation.
            # Only callers explicitly sharing one observation epoch may join.
            key = ((read_epoch, channel, method, _encode(params))
                   if isinstance(read_epoch, str) and read_epoch and method in _READ_METHODS else None)
            with self.lock:
                pending = self.inflight.get(key) if key is not None else None
                leader = pending is None
                if leader:
                    pending = {"done": threading.Event()}
                    if key is not None:
                        self.inflight[key] = pending
                else:
                    self.coalesced_reads += 1
            if not leader:
                if not pending["done"].wait(max(0, deadline - time.monotonic())):
                    raise sessions.DeadlineExceeded("Shared read deadline expired")
                if "error" in pending:
                    raise pending["error"]
                return pending["value"]
            try:
                start_token = None
                with self.lock:
                    counts = self.counts.setdefault(channel, {})
                    counts[method] = counts.get(method, 0) + 1
                    if method == "turn/start" and isinstance(params.get("threadId"), str):
                        start_token = object()
                        self.starting_turns.setdefault((channel, params["threadId"]), {})[start_token] = None
                with sessions.deadline_scope(deadline=deadline):
                    value = server.call(method, params, timeout=sessions.remaining_timeout(timeout, deadline=deadline))
                with self.lock:
                    if method in ("thread/start", "thread/resume"):
                        thread = value.get("thread") if isinstance(value, dict) else None
                        identity = thread.get("id") if isinstance(thread, dict) else None
                        identity = identity or (params.get("threadId") if method == "thread/resume" else None)
                        if isinstance(identity, str) and identity:
                            self.subscriptions[identity] = channel
                    self._turn_response(method, params, value, channel=channel)
                    if start_token is not None:
                        state = self.starting_turns[(channel, params["threadId"])].get(start_token)
                        self._idle_check(channel, params["threadId"], state)
                    pending["value"] = value
                return value
            except BaseException as exc:
                pending["error"] = exc
                raise
            finally:
                with self.lock:
                    if start_token is not None:
                        starting = self.starting_turns[(channel, params["threadId"])]
                        starting.pop(start_token, None)
                        if not starting:
                            del self.starting_turns[(channel, params["threadId"])]
                    if key is not None:
                        self.inflight.pop(key, None)
                    pending["done"].set()
        finally:
            with self.lock:
                self.pending_count -= 1
                self.notify_activity()

    def wait_events(self, timeout=30):
        timeout = sessions.remaining_timeout(timeout)
        with self.changed:
            self.changed.wait_for(lambda: self.events or self.event_error or self.closed, timeout=timeout)
            if self.event_error is not None and not self.events:
                error, self.event_error = self.event_error, None
                raise HarnessError(error)
            values = list(self.events)
            self.events.clear()
            self.event_bytes = 0
            return values

    def drain_events(self):
        return self.wait_events(0)

    def diagnostics(self):
        with self.lock:
            native = {}
            for channel, row in self.channels.items():
                report = getattr(row["server"], "diagnostics", lambda: {})()
                sent = report.get("rpc_by_method", {})
                if report.get("rpc_by_method_complete") is True:
                    counts = sent
                else:
                    # Injected fixtures may report only initialization, or no
                    # send diagnostics. Keep their established attempt fallback.
                    counts = {**self.counts.get(channel, {})}
                    if "initialize" in sent:
                        counts["initialize"] = sent["initialize"]
                for method, count in counts.items():
                    native[method] = native.get(method, 0) + count
            return {"connection_mode": "shared", "connections": len(self.channels), "leases": self.leases,
                    "pending_calls": self.pending_count, "native_rpc_by_method": native,
                    "ipc_requests": self.ipc_requests, "coalesced_reads": self.coalesced_reads,
                    "covered_threads": len(self.subscriptions), "active_turns": len(self.active_turns),
                    "lifetime_checks": len(self.lifetime_workers), "lifetime_recovery_required": len(self.lifetime_failures),
                    "reconciliations": dict(self.reconciliations)}

    def close(self):
        with self.changed:
            if self.closed:
                return
            self.closed = True
            servers = [row["server"] for row in self.channels.values()]
            readers = [row["reader"] for row in self.channels.values()]
            readers.extend(row["thread"] for row in self.creating.values())
            readers.extend(self.lifetime_workers.values())
            for listener in self.listeners:
                listener.inbox.end("Shared native owner closed")
            self.changed.notify_all()
        # An expired task budget cannot prevent releasing owned handles. This
        # independent cleanup scope cannot create or replay a native operation.
        previous = sessions._operation_deadline.set(None)
        try:
            with sessions.deadline_scope(timeout=1) as deadline:
                for server in servers:
                    with contextlib.suppress(OSError, HarnessError):
                        server.close()
                for reader in readers:
                    if reader is not threading.current_thread():
                        reader.join(timeout=max(0, deadline - time.monotonic()))
        finally:
            sessions._operation_deadline.reset(previous)


class _Events:
    def __init__(self, originator):
        self.channels = {originator}
        self.inbox = sessions._RpcInbox()

    def wait(self, timeout):
        with self.inbox.changed:
            if not self.inbox.events and self.inbox.state == "connected":
                self.inbox.changed.wait_for(lambda: self.inbox.events or self.inbox.state != "connected", timeout=timeout)
            if self.inbox.events:
                # Preserve the last accepted terminal batch before surfacing EOF.
                result = list(self.inbox.events)
                self.inbox.events.clear()
                self.inbox.event_bytes = 0
                return result
            return self.inbox.drain()


class _Facade:
    @property
    def desktop_managed(self):
        return sessions.desktop_selected() or self.originator.startswith("oasis_desktop_")

    @property
    def source_id(self):
        return os.environ.get("CODEX_THREAD_ID")

    def __init__(self, pool, originator, *, read_epoch=None):
        self.pool, self.originator = pool, originator
        self.read_epoch = read_epoch
        self.closed = False

    def call(self, method, params, timeout=30):
        return self.pool.call(self.originator, method, params, timeout, read_epoch=self.read_epoch)

    def observation(self):
        """One explicitly bounded read phase, never reuse across a writer lock."""
        return self.pool.facade(self.originator, read_epoch=uuid.uuid4().hex)

    def wait_events(self, timeout=30):
        return self.pool.wait_events(timeout)

    def drain_events(self):
        return self.pool.drain_events()

    def subscribed(self, thread_id):
        return self.pool.event_covered(thread_id)

    event_covered = subscribed

    def diagnostics(self):
        return self.pool.diagnostics()

    def record_reconciliation(self, reason):
        self.pool.record_reconciliation(reason)

    def pages(self, method, params, *, timeout=30):
        yield from _pages(self, method, params, timeout=timeout)

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _pages(server, method, params, *, timeout=30):
    deadline = time.monotonic() + sessions.remaining_timeout(timeout)
    seen = set()
    while True:
        page = sessions._history_page(server.call(method, params, timeout=sessions.remaining_timeout(timeout, deadline=deadline)), method)
        yield from page["data"]
        cursor = page.get("nextCursor")
        if not cursor:
            return
        if cursor in seen:
            raise HarnessError("Repeated Codex pagination cursor; discovery is incomplete")
        seen.add(cursor)
        params = {**params, "cursor": cursor}


def _error(exc):
    result = {"kind": "deadline" if isinstance(exc, sessions.DeadlineExceeded) else "harness", "message": str(exc)}
    if isinstance(exc, sessions.NativeError):
        result.update(kind="native", method=exc.method, error=exc.error)
    return result


def _raise_error(value):
    if value.get("kind") == "native":
        raise sessions.NativeError(value["method"], value["error"])
    if value.get("kind") == "deadline":
        raise sessions.DeadlineExceeded(value["message"])
    raise HarnessError(value.get("message", "Shared command failed; preserve retained receipts"))


class Host:
    """Raw-byte local endpoint embedded in the notification owner's process."""
    def __init__(self, root, token, generation, pool):
        self.root, self.token, self.generation, self.pool = Path(root).resolve(), token, generation, pool
        self.identity = runtime_identity(self.root)
        self.family = "AF_PIPE" if os.name == "nt" else "AF_UNIX"
        name = digest({"root": sessions.canonical_root(root), "generation": generation, "token": token})[:40]
        if os.name == "nt":
            self.address = "\\\\.\\pipe\\oasis-" + name
        else:
            self.address = str(self.root / ".oasis/local" / ("ipc-" + name[:20] + ".sock"))
        self.listener = None
        self.closed = False
        self.accepting = True
        self.clients = set()
        self.lock = threading.Lock()

    def descriptor(self):
        return {"protocol": PROTOCOL, "address": self.address, "family": self.family, "runtime": self.identity}

    def busy(self):
        return self.pool.busy()

    @property
    def last_activity(self):
        return self.pool.last_activity

    def begin_shutdown(self):
        """Close admission atomically against authenticated lease acquisition."""
        with self.lock:
            if self.pool.busy():
                return False
            self.accepting = False
            return True

    def __enter__(self):
        if os.name != "nt":
            Path(self.address).parent.mkdir(parents=True, exist_ok=True)
        self.listener = Listener(self.address, family=self.family, authkey=None, backlog=MAX_CLIENTS)
        if os.name != "nt":
            os.chmod(self.address, 0o600)
        threading.Thread(target=self._accept, name="oasis-shared-accept", daemon=True).start()
        return self

    def _accept(self):
        while not self.closed:
            try:
                connection = self.listener.accept()
            except (OSError, EOFError, AttributeError):
                return
            with self.lock:
                if self.closed or len(self.clients) >= MAX_CLIENTS:
                    connection.close()
                    continue
                self.clients.add(connection)
            threading.Thread(target=self._serve, args=(connection,), name="oasis-shared-command", daemon=True).start()

    def _serve(self, connection):
        leased = False
        listener = None
        try:
            if not _same_user(connection, server_side=True):
                return
            if not connection.poll(5):
                return
            request = _bounded(lambda: connection.recv_bytes(MAX_BYTES), 5, cancel=connection.close)
            hello = _decode(request)
            if (not isinstance(hello.get("token"), str) or not hmac.compare_digest(hello["token"], self.token)
                    or hello.get("generation") != self.generation or hello.get("runtime") != self.identity
                    or hello.get("protocol") != PROTOCOL):
                return
            if hello.get("op") == "diagnostics":
                frame = _encode({"diagnostics": self.pool.diagnostics()})
                _bounded(lambda: connection.send_bytes(frame), 1, cancel=connection.close)
                return
            originator = hello.get("originator")
            sessions.require_text(originator, "Shared upstream originator")
            with self.lock:
                if not self.accepting or self.closed:
                    return
                self.pool.acquire()
                leased = True
                listener = self.pool.listen(originator)
            frame = _encode({"ready": True, "generation": self.generation, "runtime": self.identity})
            _bounded(lambda: connection.send_bytes(frame), 1, cancel=connection.close)
            while not self.closed and connection.poll(IDLE_SECONDS):
                request = _decode(_bounded(lambda: connection.recv_bytes(MAX_BYTES), 30, cancel=connection.close))
                if request.get("op") == "release":
                    return
                operation = request.get("op")
                if operation not in ("call", "events", "diagnostics", "covered"):
                    raise HarnessError("Unknown shared command operation")
                timeout = request.get("timeout")
                sessions._valid_seconds(timeout, "Shared RPC timeout")
                deadline = request.get("deadline")
                sessions._valid_seconds(deadline, "Shared RPC absolute deadline")
                if operation != "diagnostics":
                    with self.pool.lock:
                        self.pool.ipc_requests += 1
                try:
                    with sessions.deadline_scope(timeout=min(timeout, 24 * 60 * 60), deadline=deadline):
                        if operation == "call":
                            value = self.pool.call(originator, request.get("method"), request.get("params"), timeout, listener=listener)
                        elif operation == "events":
                            wait = request.get("wait_timeout")
                            sessions._valid_seconds(wait, "Shared event timeout")
                            # Leave enough of the same caller budget to encode
                            # an ordinary empty timeout response back over IPC.
                            budget = max(0, sessions.remaining_timeout(timeout) - 0.02)
                            value = listener.wait(min(wait, budget))
                        elif operation == "covered":
                            value = self.pool.event_covered(request.get("thread_id"))
                        else:
                            value = self.pool.diagnostics()
                    reply = {"result": value}
                except (HarnessError, OSError) as exc:
                    reply = {"error": _error(exc)}
                frame = _encode(reply)
                def respond():
                    sessions.remaining_timeout(30, deadline=deadline)
                    connection.send_bytes(frame)
                _bounded(respond, sessions.remaining_timeout(30, deadline=deadline), cancel=connection.close)
        except (OSError, EOFError, HarnessError, ValueError):
            pass
        finally:
            if leased:
                self.pool.release()
            if listener is not None:
                self.pool.unlisten(listener)
            connection.close()
            with self.lock:
                self.clients.discard(connection)

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            self.accepting = False
        if self.listener is not None:
            # Wake a blocking accept before closing; no command is authenticated.
            with contextlib.suppress(OSError, EOFError, sessions.DeadlineExceeded):
                connection = _bounded(lambda: PipeClient(self.address, family=self.family, authkey=None), 0.2, late_close=True)
                connection.close()
            self.listener.close()
        with self.lock:
            for connection in list(self.clients):
                with contextlib.suppress(OSError):
                    connection.close()

    def __exit__(self, kind, error, traceback):
        try:
            self.close()
        except Exception as cleanup:
            if error is None:
                raise
            error.add_note(f"Shared endpoint cleanup failed: {type(cleanup).__name__}")


class Client:
    def __init__(self, row, originator):
        descriptor = row["ipc"]
        self.closed = False
        self.lock = threading.Lock()
        self.connection = _bounded(lambda: PipeClient(descriptor["address"], family=descriptor["family"], authkey=None),
                                   sessions.remaining_timeout(5), late_close=True)
        try:
            if not _same_user(self.connection, server_side=False):
                raise HarnessError("Shared command endpoint belongs to another user")
            hello = {"token": row["token"], "generation": row["generation"], "runtime": descriptor["runtime"],
                     "protocol": PROTOCOL, "originator": originator}
            self._send(hello, 5)
            answer = self._receive(5)
            if (answer.get("ready") is not True or answer.get("generation") != row["generation"]
                    or answer.get("runtime") != descriptor["runtime"]):
                raise HarnessError("Shared command generation changed before acceptance")
        except BaseException:
            self.close()
            raise

    def _send(self, value, timeout):
        frame = _encode(value)
        deadline = sessions._earliest_deadline()
        def write():
            sessions.remaining_timeout(timeout, deadline=deadline)
            self.connection.send_bytes(frame)
        _bounded(write, sessions.remaining_timeout(timeout), cancel=self.connection.close)

    def _receive(self, timeout):
        return _decode(_bounded(lambda: self.connection.recv_bytes(MAX_BYTES), sessions.remaining_timeout(timeout),
                                cancel=self.connection.close))

    def call(self, method, params, timeout=30):
        sessions.require_text(method, "Shared RPC method")
        if not isinstance(params, dict):
            raise HarnessError("Shared RPC params must be an object")
        return self._request("call", {"method": method, "params": params}, timeout)

    def _request(self, operation, fields, timeout):
        deadline = time.monotonic() + sessions.remaining_timeout(timeout)
        if not self.lock.acquire(timeout=max(0, deadline - time.monotonic())):
            raise sessions.DeadlineExceeded("Shared client queue deadline expired before forwarding")
        try:
            if self.closed:
                raise HarnessError("Shared command lease closed; reconcile before another mutation")
            with sessions.deadline_scope(deadline=deadline):
                self._send({"op": operation, **fields,
                            "timeout": sessions.remaining_timeout(timeout, deadline=deadline), "deadline": deadline}, timeout)
                reply = self._receive(timeout)
            if "error" in reply:
                _raise_error(reply["error"])
            if "result" not in reply:
                raise HarnessError("Shared command returned an invalid response; outcome uncertain")
            return reply["result"]
        except (OSError, EOFError):
            self.close()
            raise HarnessError(f"{fields.get('method', operation)}: shared connection ended; outcome uncertain; reconcile before another mutation") from None
        finally:
            self.lock.release()

    def pages(self, method, params, *, timeout=30):
        yield from _pages(self, method, params, timeout=timeout)

    def wait_events(self, timeout=30):
        sessions._valid_seconds(timeout, "Shared event timeout")
        return self._request("events", {"wait_timeout": timeout}, max(timeout, 0.1))

    def drain_events(self):
        return self.wait_events(0)

    def event_covered(self, thread_id):
        return self._request("covered", {"thread_id": thread_id}, 1)

    subscribed = event_covered

    def diagnostics(self):
        return self._request("diagnostics", {}, 1)

    def close(self):
        if self.closed:
            return
        self.closed = True
        with contextlib.suppress(OSError):
            self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def connect(root, originator):
    """Select sharing before forwarding; uncertain calls never switch transport."""
    from . import notifications
    root = Path(root).resolve()
    expected = runtime_identity(root)
    row = notifications.ensure_running(root)
    deadline = time.monotonic() + sessions.remaining_timeout(5)
    while (not row.get("ipc") and time.monotonic() < deadline
           and (row.get("status") == "starting" or row.get("status") == "running" and row.get("shared_protocol") == PROTOCOL)):
        time.sleep(min(0.02, max(0, deadline - time.monotonic())))
        row = notifications.status(root)
    descriptor = row.get("ipc") or {}
    if (row.get("status") != "running" or descriptor.get("protocol") != PROTOCOL
            or descriptor.get("runtime") != expected):
        # A legacy live owner is never replaced. No request has been forwarded.
        return sessions.AppServer(originator, notification_profile="command")
    expected_family = "AF_PIPE" if os.name == "nt" else "AF_UNIX"
    if descriptor.get("family") != expected_family or not isinstance(descriptor.get("address"), str):
        raise HarnessError("Invalid shared command endpoint; preserve ownership state")
    # Handshake itself cannot issue native work, so this is the only safe fallback.
    for attempt in range(2):
        try:
            return Client(row, originator)
        except (OSError, EOFError, HarnessError):
            sessions.remaining_timeout()
            if attempt == 0:
                row = notifications.ensure_running(root)
                descriptor = row.get("ipc") or {}
                if (row.get("status") == "running" and descriptor.get("protocol") == PROTOCOL
                        and descriptor.get("runtime") == expected):
                    continue
            return sessions.AppServer(originator, notification_profile="command")


def read_diagnostics(root, row):
    """One bounded read-only IPC query; no lease, activity or owner startup."""
    descriptor = row.get("ipc") or {}
    if descriptor.get("protocol") != PROTOCOL or descriptor.get("runtime") != runtime_identity(root):
        return {}
    connection = None
    try:
        with sessions.deadline_scope(timeout=1):
            connection = _bounded(lambda: PipeClient(descriptor["address"], family=descriptor["family"], authkey=None),
                                  sessions.remaining_timeout(0.3), late_close=True)
            if not _same_user(connection, server_side=False):
                return {}
            frame = _encode({"op": "diagnostics", "token": row["token"], "generation": row["generation"],
                             "runtime": descriptor["runtime"], "protocol": PROTOCOL})
            _bounded(lambda: connection.send_bytes(frame), sessions.remaining_timeout(0.3), cancel=connection.close)
            answer = _decode(_bounded(lambda: connection.recv_bytes(MAX_BYTES), sessions.remaining_timeout(0.3),
                                      cancel=connection.close))
            return answer.get("diagnostics", {})
    except (OSError, EOFError, HarnessError, KeyError):
        return {}
    finally:
        if connection is not None:
            connection.close()
