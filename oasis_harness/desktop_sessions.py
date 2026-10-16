"""Desktop-owned chats through its inherited tools pipe, without another writer.

The small AppServer-shaped facade uses native tools for application state and
reads verified rollouts only for identity/settings. Filesystem notifications wake
explicit reconciliation reads; an idle observer never queries thread history.
"""
from __future__ import annotations

from collections import deque
import copy
import ctypes
import html
import json
import math
import os
from pathlib import Path
import sqlite3
import re
import stat
import struct
import threading
import time
import uuid
import xml.etree.ElementTree as ET

from .common import HarnessError
from . import sessions


def available():
    """Only opt into an inherited Desktop pipe; never discover/start another host."""
    return bool(os.name == "nt" and os.environ.get("CODEX_APP_TOOLS_PIPE_PATH"))


def _identity(value, label="Desktop thread ID"):
    if not isinstance(value, str):
        raise HarnessError(f"{label} must be an actual UUID")
    try:
        if str(uuid.UUID(value)) != value.lower():
            raise ValueError
    except ValueError:
        raise HarnessError(f"{label} must be an actual UUID") from None
    return value


def _bounded_prompt(prompt, source_id):
    """The native summary must retain the complete escaped delegation input."""
    from .desktop_tools import DesktopNotSent
    try:
        sessions.require_text(prompt, "Assignment prompt")
        escape = lambda value: value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        wrapped = ("<codex_delegation>\r\n  <source_thread_id>" + source_id + "</source_thread_id>\r\n"
                   "  <input>" + escape(prompt) + "</input>\r\n</codex_delegation>")
        if len(wrapped.encode("utf-16-le")) // 2 > 20000:
            raise ValueError("Prompt exceeds the native exact-readback limit")
        ET.fromstring(wrapped)
    except (HarnessError, ValueError, UnicodeError, ET.ParseError) as exc:
        raise DesktopNotSent("Desktop prompt cannot be verified in the native bounded history; shorten or correct it before dispatch") from exc
    return prompt


def _unlinked(path, root):
    """Check the requested lexical path before resolve can erase a link boundary."""
    path, root = Path(os.path.abspath(path)), Path(os.path.abspath(root))
    try:
        relative = path.relative_to(root)
    except ValueError:
        raise HarnessError("Desktop rollout/watch path leaves its verified owner") from None
    current = root
    for part in (None, *relative.parts):
        if part is not None:
            current /= part
        try:
            value = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(value.st_mode) or getattr(value, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise HarnessError("Desktop rollout/watch path contains a linked or reparse entry")
    return path


class MissingRollout(HarnessError):
    """An acknowledged creation has not yet persisted its initial record."""


class Rollouts:
    """Bounded, read-only exact-ID lookup; no app database or cached defaults."""
    MAX_ENTRIES = 100000

    def __init__(self, home):
        self.home = Path(os.path.abspath(home))
        self.cache = {}

    def find(self, identity):
        _identity(identity)
        previous = self.cache.get(identity)
        if previous is not None and previous.is_file():
            _unlinked(previous, self.home)
            return previous
        suffix, matches, visited = "-" + identity.lower() + ".jsonl", [], 0
        pending = [self.home / name for name in ("sessions", "archived_sessions")]
        while pending:
            directory = pending.pop()
            _unlinked(directory, self.home)
            if not directory.exists():
                continue
            sessions.remaining_timeout()
            with os.scandir(directory) as entries:
                for entry in entries:
                    visited += 1
                    if visited > self.MAX_ENTRIES:
                        raise HarnessError("Desktop rollout inventory exceeds its bounded lookup; preserve the known chat ID")
                    if entry.is_dir(follow_symlinks=False):
                        # Ordinary session trees are date directories; do not traverse links.
                        _unlinked(Path(entry.path), self.home)
                        pending.append(Path(entry.path))
                    elif entry.name.lower().startswith("rollout-") and entry.name.lower().endswith(suffix):
                        candidate = _unlinked(Path(entry.path), self.home)
                        if not candidate.is_file():
                            raise HarnessError("Desktop rollout identity is not an ordinary file")
                        matches.append(candidate)
        if not matches:
            raise MissingRollout("Desktop chat has no saved rollout yet; preserve its acknowledged ID")
        if len(matches) != 1:
            raise HarnessError("Desktop thread requires exactly one actual UUID-named rollout; preserve its known ID")
        self.cache[identity] = matches[0]
        return matches[0]

    def metadata(self, identity):
        path = self.find(identity)
        metadata, turn_id, complete_records = None, None, 0
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                sessions.remaining_timeout()
                # A writer can have an unfinished last record. Never use it as evidence.
                if not line.endswith("\n"):
                    continue
                complete_records += 1
                record = json.loads(line)
                if not isinstance(record, dict) or not isinstance(record.get("payload"), dict):
                    raise HarnessError("Desktop rollout has an invalid record")
                payload = record["payload"]
                if record.get("type") == "session_meta":
                    if metadata is not None and payload != metadata:
                        raise HarnessError("Desktop rollout has conflicting session identity")
                    metadata = payload
                elif record.get("type") == "turn_context" and payload.get("turn_id"):
                    turn_id = payload["turn_id"]
                elif record.get("type") == "event_msg" and payload.get("type") == "task_started" and payload.get("turn_id"):
                    turn_id = payload["turn_id"]
        if not complete_records:
            raise MissingRollout("Desktop initial rollout record is not complete yet")
        if (not isinstance(metadata, dict) or metadata.get("id") != identity
                or not isinstance(metadata.get("cwd"), str) or not metadata["cwd"]):
            raise HarnessError("Desktop rollout metadata does not match its exact chat ID/root")
        return path, metadata, turn_id


class _DirectoryWatch:
    """One cancellable overlapped ReadDirectoryChangesW owner per directory."""
    def __init__(self, directory, changed, failed, *, recursive=False):
        if os.name != "nt":
            raise sessions.NativeError("fs/watch", {"code": -32601, "message": "Windows change notifications unavailable"})
        from ctypes import wintypes as wt
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.changed, self.failed = changed, failed
        self.recursive = recursive
        self.closed = False
        self.lock = threading.RLock()
        self.buffer = ctypes.create_string_buffer(65536)

        class Overlapped(ctypes.Structure):
            _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                        ("Offset", wt.DWORD), ("OffsetHigh", wt.DWORD), ("hEvent", wt.HANDLE)]

        self.overlapped = Overlapped()
        self.pending = False
        api = self.api
        api.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID, wt.DWORD, wt.DWORD, wt.HANDLE]
        api.CreateFileW.restype = wt.HANDLE
        api.CreateEventW.argtypes = [wt.LPVOID, wt.BOOL, wt.BOOL, wt.LPCWSTR]
        api.CreateEventW.restype = wt.HANDLE
        api.ReadDirectoryChangesW.argtypes = [wt.HANDLE, wt.LPVOID, wt.DWORD, wt.BOOL, wt.DWORD,
                                             ctypes.POINTER(wt.DWORD), ctypes.POINTER(Overlapped), wt.LPVOID]
        api.ReadDirectoryChangesW.restype = wt.BOOL
        api.GetOverlappedResult.argtypes = [wt.HANDLE, ctypes.POINTER(Overlapped), ctypes.POINTER(wt.DWORD), wt.BOOL]
        api.GetOverlappedResult.restype = wt.BOOL
        api.WaitForMultipleObjects.argtypes = [wt.DWORD, ctypes.POINTER(wt.HANDLE), wt.BOOL, wt.DWORD]
        api.WaitForMultipleObjects.restype = wt.DWORD
        api.CancelIoEx.argtypes = [wt.HANDLE, wt.LPVOID]
        api.CancelIoEx.restype = wt.BOOL
        for name in ("ResetEvent", "SetEvent", "CloseHandle"):
            getattr(api, name).argtypes = [wt.HANDLE]
            getattr(api, name).restype = wt.BOOL
        self.handle = self.event = self.stop = None
        try:
            self.handle = api.CreateFileW(str(directory), 1, 7, None, 3, 0x42000000, None)
            if self.handle == ctypes.c_void_p(-1).value:
                self.handle = None
                raise ctypes.WinError(ctypes.get_last_error())
            self.event, self.stop = api.CreateEventW(None, True, False, None), api.CreateEventW(None, True, False, None)
            if not self.event or not self.stop:
                raise ctypes.WinError(ctypes.get_last_error())
            self.overlapped.hEvent = self.event
            self._arm()  # Register before returning, closing the subscription race.
            self.thread = threading.Thread(target=self._run, name="oasis-desktop-filesystem", daemon=True)
            self.thread.start()
        except Exception:
            self._release()
            raise

    def _arm(self):
        self.api.ResetEvent(self.event)
        if not self.api.ReadDirectoryChangesW(self.handle, self.buffer, len(self.buffer), self.recursive,
                                               0x1F, None, ctypes.byref(self.overlapped), None):
            if ctypes.get_last_error() != 997:
                raise ctypes.WinError(ctypes.get_last_error())
        self.pending = True

    def _run(self):
        from ctypes import wintypes as wt
        handles = (wt.HANDLE * 2)(self.stop, self.event)
        try:
            while True:
                outcome = self.api.WaitForMultipleObjects(2, handles, False, 0xFFFFFFFF)
                if outcome == 0:
                    return
                if outcome != 1:
                    raise ctypes.WinError(ctypes.get_last_error())
                count = wt.DWORD()
                if not self.api.GetOverlappedResult(self.handle, ctypes.byref(self.overlapped), ctypes.byref(count), False):
                    raise ctypes.WinError(ctypes.get_last_error())
                self.pending = False
                raw, names, offset = self.buffer.raw[:count.value], [], 0
                while offset < len(raw):
                    if offset + 12 > len(raw):
                        raise HarnessError("Incomplete Windows directory change record")
                    following, _, length = struct.unpack_from("<III", raw, offset)
                    if length % 2 or offset + 12 + length > len(raw):
                        raise HarnessError("Invalid Windows directory change filename")
                    names.append(raw[offset + 12:offset + 12 + length].decode("utf-16-le"))
                    if not following:
                        break
                    if following < 12 or offset + following >= len(raw):
                        raise HarnessError("Invalid Windows directory change offset")
                    offset += following
                with self.lock:
                    if self.closed:
                        return
                    self._arm()
                if not count.value:
                    raise HarnessError("Windows directory change buffer overflow; reconcile retained state")
                self.changed(names)
        except Exception as exc:
            if not self.closed:
                self.failed(exc)
        finally:
            self._release()

    def _release(self):
        from ctypes import wintypes as wt
        with self.lock:
            self.closed = True
            if self.handle and self.pending:
                self.api.CancelIoEx(self.handle, None)
                # Cancellation only requests completion. The OVERLAPPED and
                # buffer stay alive until the kernel acknowledges that request.
                count = wt.DWORD()
                self.api.GetOverlappedResult(self.handle, ctypes.byref(self.overlapped), ctypes.byref(count), True)
                self.pending = False
            for name in ("handle", "event", "stop"):
                value = getattr(self, name, None)
                if value:
                    self.api.CloseHandle(value)
                    setattr(self, name, None)

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            self.api.SetEvent(self.stop)
            self.api.CancelIoEx(self.handle, None)
        if self.thread is not threading.current_thread():
            self.thread.join(timeout=.5)


class DesktopServer:
    backend = "desktop"
    desktop_managed = True
    MAX_HISTORY_PAGES = 1000
    MAX_EVENTS = 4096

    def archive_descendants(self, identity):
        """Read persisted spawn edges before Core's cascading archive.

        Native list_threads is a recency window, not an exhaustive descendant
        inventory. Bind a unique read-only Core state DB to this exact rollout;
        unknown schema/location leaves the chat available instead of archiving.
        """
        identity = _identity(identity)
        rollout, _, _ = self.rollouts.metadata(identity)
        paths = list(self.rollouts.home.glob("state_*.sqlite"))
        if not 1 <= len(paths) <= 8:
            raise HarnessError("Desktop archive requires one verified native spawn-edge inventory")
        matches = []
        for path in paths:
            _unlinked(path, self.rollouts.home)
            for suffix in ("-wal", "-shm"):
                _unlinked(path.with_name(path.name + suffix), self.rollouts.home)
            try:
                connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True,
                                             timeout=min(1, sessions.remaining_timeout()))
                try:
                    connection.execute("PRAGMA query_only=ON")
                    connection.set_progress_handler(lambda: int(sessions.remaining_timeout() <= 0), 1000)
                    connection.execute("BEGIN")
                    tables = {row[0] for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('threads','thread_spawn_edges')")}
                    if tables != {"threads", "thread_spawn_edges"}:
                        raise HarnessError("Desktop archive spawn-edge schema is unsupported; preserve the chat")
                    native = connection.execute("SELECT rollout_path FROM threads WHERE id=?", (identity,)).fetchall()
                    if not native:
                        continue
                    if len(native) != 1 or sessions.canonical_root(native[0][0]) != sessions.canonical_root(rollout):
                        raise HarnessError("Desktop archive state and exact rollout identity disagree")
                    rows = connection.execute("""WITH RECURSIVE descendants(id) AS (
                        SELECT child_thread_id FROM thread_spawn_edges WHERE parent_thread_id=?
                        UNION SELECT e.child_thread_id FROM thread_spawn_edges e JOIN descendants d ON e.parent_thread_id=d.id
                        ) SELECT id FROM descendants LIMIT 10001""", (identity,)).fetchall()
                    if len(rows) > 10000:
                        raise HarnessError("Desktop archive descendant inventory exceeds its bound")
                    descendants = {_identity(row[0]) for row in rows}
                    if identity in descendants:
                        raise HarnessError("Desktop native spawn-edge inventory contains a cycle")
                    matches.append(descendants)
                finally:
                    connection.close()
            except sqlite3.Error as exc:
                raise HarnessError("Desktop native spawn-edge inventory is unavailable; preserve the chat") from exc
        if len(matches) != 1:
            raise HarnessError("Desktop archive requires one unambiguous native spawn-edge inventory")
        return matches[0]

    def __init__(self, originator, *, tools=None, codex_home=None, watcher_factory=None):
        self.originator = sessions.require_text(originator, "Desktop connection originator")
        self.source_id = _identity(os.environ.get("CODEX_THREAD_ID"))
        self.rollouts = Rollouts(codex_home or os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        _, metadata, turn_id = self.rollouts.metadata(self.source_id)
        self.turn_id = _identity(turn_id, "Desktop caller turn ID")
        self.roots = {sessions.canonical_root(metadata["cwd"]): Path(metadata["cwd"])}
        self.verified_paths, self.projects = set(), None
        if tools is None:
            from .desktop_tools import DesktopTools
            tools = DesktopTools(os.environ.get("CODEX_APP_TOOLS_PIPE_PATH"), self.source_id, self.turn_id)
        self.tools = tools
        self.watcher_factory = watcher_factory or _DirectoryWatch
        self.condition = threading.Condition(threading.RLock())
        self.watches, self.directories, self.events = {}, {}, deque()
        self.closed, self.event_error, self.event_error_reported = False, None, False
        self.calls = {}

    def _tool(self, name, args, *, timeout=30, call_id=None, mutation=False):
        if self.closed:
            raise HarnessError("Desktop connection is closed")
        self.calls[name] = self.calls.get(name, 0) + 1
        try:
            result = self.tools.call(name, args, timeout=sessions.remaining_timeout(timeout), call_id=call_id)
        except Exception as exc:
            # App handlers can fail after an effect was issued. Their textual
            # success:false does not establish that a mutation was rejected.
            from .desktop_tools import DesktopRejected
            if isinstance(exc, DesktopRejected) and not mutation:
                raise sessions.NativeError(name, {"code": exc.code or -32000, "message": str(exc)}) from exc
            raise
        if not isinstance(result, dict):
            raise HarnessError("Desktop tool returned a non-object; preserve any mutation outcome")
        return result

    def _projects(self, *, refresh=False):
        if self.projects is None or refresh:
            value = self._tool("list_projects", {})
            if not isinstance(value.get("projects"), list):
                raise HarnessError("Desktop project inventory is unavailable")
            self.projects = value["projects"]
        return self.projects

    def _project(self, cwd):
        matches = [row for row in self._projects() if isinstance(row, dict)
                   and row.get("projectKind") == "local" and row.get("hostId") == "local"
                   and isinstance(row.get("path"), str)
                   and sessions.canonical_root(row["path"]) == sessions.canonical_root(cwd)]
        if len(matches) != 1:
            raise HarnessError("Desktop root must match exactly one actual local Codex project")
        return sessions.require_text(matches[0].get("projectId"), "Desktop project ID")

    @staticmethod
    def _item(item):
        """Adapt exact app delegation inputs, preserving their real native item IDs."""
        if not isinstance(item, dict):
            raise HarnessError("Desktop history item must be an object")
        value = copy.deepcopy(item)
        if item.get("type") == "functionCallOutput" and item.get("namespace") == "codex_app" and item.get("name") in (None, "create_thread", "send_message_to_thread"):
            text = item.get("output")
            if isinstance(text, dict):
                if text.get("truncated") is not False:
                    return value
                text = text.get("text")
        elif item.get("type") == "userMessage":
            content = item.get("content")
            text = "\n".join(part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text") if isinstance(content, list) else None
        else:
            return value
        if not isinstance(text, str) or not text.startswith("<codex_delegation>"):
            return value
        try:
            root = ET.fromstring(text)
            if (root.tag != "codex_delegation" or root.attrib or len(root) != 2
                    or [child.tag for child in root] != ["source_thread_id", "input"]
                    or any(child.attrib or len(child) for child in root)):
                return value
            # XML parsing validates structure but normalizes CRLF. Recover the
            # escaped original bytes so delivery comparisons preserve newlines.
            matched = re.fullmatch(r"<codex_delegation>\r?\n  <source_thread_id>([^<>]*)</source_thread_id>\r?\n"
                                   r"  <input>([^<>]*)</input>\r?\n</codex_delegation>", text)
            if matched is None:
                return value
            source = _identity(html.unescape(matched[1]))
            prompt = html.unescape(matched[2])
        except (ET.ParseError, HarnessError):
            return value
        return {"type": "userMessage", "id": item.get("id"), "content": [{"type": "text", "text": prompt}],
                "nativeType": item["type"], "sourceThreadId": source}

    def _native(self, identity, *, cursor=None, limit=10, timeout=30):
        _identity(identity)
        args = {"threadId": identity, "hostId": "local", "turnLimit": min(10, max(1, limit)),
                "includeOutputs": True, "maxOutputCharsPerItem": 20000}
        if cursor:
            args["cursor"] = cursor
        value = self._tool("read_thread", args, timeout=timeout)
        native, page, turns = value.get("thread"), value.get("page"), value.get("turns")
        if (not isinstance(native, dict) or native.get("id") != identity or native.get("kind") != "codex"
                or native.get("hostId") != "local" or not isinstance(native.get("cwd"), str)
                or not isinstance(native.get("status"), dict) or native["status"].get("type") not in ("active", "idle", "notLoaded", "systemError")
                or not isinstance(page, dict) or page.get("order") != "newest_first" or not isinstance(turns, list)):
            raise HarnessError("Desktop read returned invalid identity, host, status or history")
        seen, normalized = set(), []
        for turn in turns:
            if not isinstance(turn, dict) or not isinstance(turn.get("id"), str) or turn["id"] in seen or not isinstance(turn.get("items"), list):
                raise HarnessError("Desktop history has invalid/repeated actual turn IDs or incomplete items")
            seen.add(turn["id"])
            normalized.append({**turn, "items": [self._item(item) for item in turn["items"]]})
        if (not isinstance(page.get("hasMore"), bool) or page["hasMore"] and not isinstance(page.get("nextCursor"), str)):
            raise HarnessError("Desktop history pagination is incomplete")
        return native, normalized, page

    def _thread(self, identity, *, include_turns=False, timeout=30):
        native, turns, _ = self._native(identity, limit=1, timeout=timeout)
        path, metadata, _ = self.rollouts.metadata(identity)
        if sessions.canonical_root(metadata["cwd"]) != sessions.canonical_root(native["cwd"]):
            raise HarnessError("Desktop native root and saved rollout root disagree")
        self.verified_paths.add(sessions.canonical_root(path))
        self.roots[sessions.canonical_root(native["cwd"])] = Path(native["cwd"])
        if include_turns:
            turns = list(reversed(self._history(identity)))
        return {**native, "projectId": self._project(native["cwd"]), "path": str(path),
                "name": native.get("title"), "turns": turns if include_turns else [],
                "latestTurn": turns[-1] if include_turns and turns else turns[0] if turns else None,
                "turnsView": "full" if include_turns else "notLoaded"}

    def _history(self, identity, *, stop=None):
        turns, cursor, seen, identities = [], None, set(), set()
        for _ in range(self.MAX_HISTORY_PAGES):
            _, data, page = self._native(identity, cursor=cursor)
            for turn in data:
                if turn["id"] in identities:
                    raise HarnessError("Desktop history repeated a turn across pages")
                identities.add(turn["id"])
                turns.append(turn)
                if turn["id"] == stop:
                    return turns
            if not page["hasMore"]:
                if stop is not None:
                    raise HarnessError("Desktop history anchor is unavailable; preserve delivery uncertainty")
                return turns
            cursor = page["nextCursor"]
            if cursor in seen:
                raise HarnessError("Desktop history repeated its cursor")
            seen.add(cursor)
        raise HarnessError("Desktop history exceeds the bounded reconciliation limit")

    def prepare_assignment(self, source_id, target):
        if _identity(source_id) != self.source_id:
            raise HarnessError("Desktop creation must use the actual inherited caller chat")
        source = self._thread(source_id)
        if sessions.canonical_root(source["cwd"]) != sessions.canonical_root(target):
            raise HarnessError("Desktop permission inheritance is verified only for the same local root")
        settings = sessions.inherited_settings(sessions.latest_settings(source["path"]))
        expected = {":danger-full-access": "dangerFullAccess", ":workspace": "workspaceWrite", ":read-only": "readOnly"}
        if (settings["permissions"] not in expected
                or settings["effective_sandbox"].get("type") != expected[settings["permissions"]]):
            raise HarnessError("Desktop custom permission inheritance is unverified; no chat is created")
        sessions.require_text(settings.get("model"), "Actual source model")
        sessions.require_text(settings.get("reasoning"), "Actual source reasoning effort")
        return self._project(target), settings, source

    @staticmethod
    def _prompt_turn(turns, prompt, source_id, excluded=()):
        found = [turn["id"] for turn in turns for item in turn["items"]
                 if item.get("id") not in excluded and item.get("type") == "userMessage"
                 and item.get("sourceThreadId") == source_id and sessions._message_text(item) == prompt]
        if len(found) != 1:
            raise HarnessError("Desktop acknowledgement lacks one exact accepted input/turn; preserve uncertainty without replay")
        return found[0]

    def create_assignment(self, source_id, target, title, prompt, settings, project_id, call_id, *, on_created=None):
        from .desktop_tools import DesktopNotSent
        try:
            actual_project, actual, _ = self.prepare_assignment(source_id, target)
            if actual_project != project_id or actual != settings:
                raise HarnessError("Desktop source selections/project changed before creation")
            _bounded_prompt(prompt, source_id)
            sessions.require_text(title, "Camel title")
        except Exception as exc:
            raise DesktopNotSent("Desktop creation preflight failed before any create request was issued") from exc
        result = self._tool("create_thread", {"target": {"type": "project", "projectId": project_id,
                            "environment": {"type": "local"}}, "title": title, "prompt": prompt,
                            "model": settings["model"], "thinking": settings["reasoning"]}, call_id=call_id, mutation=True)
        identity = _identity(result.get("threadId"))
        if callable(on_created):
            on_created(identity)
        if result.get("hostId") != "local":
            raise HarnessError("Desktop created a different host; preserve the acknowledged chat ID")
        return self.recover_assignment(identity, source_id, target, prompt, settings, project_id)

    def recover_assignment(self, thread_id, source_id, target, prompt, settings, project_id):
        """Verify a retained accepted child ID; never create or replay its prompt."""
        identity = _identity(thread_id)
        _identity(source_id)
        child = sessions.inherited_settings(self._creation_settings(identity, target))
        if child != settings:
            raise HarnessError("Desktop child actual saved selections differ; preserve the acknowledged chat ID")
        native = self._thread(identity)
        if native["projectId"] != project_id or sessions.canonical_root(native["cwd"]) != sessions.canonical_root(target):
            raise HarnessError("Desktop created a different project/root; preserve the acknowledged chat ID")
        turns = self._history(identity)
        turn_id = self._prompt_turn(turns, prompt, source_id)
        return {"thread_id": identity, "turn_id": turn_id, "native_thread": native, "host_id": "local",
                "settings": child, "creation_verified": True, "desktop_managed": True}

    def _creation_settings(self, identity, target):
        """Wait for this acknowledged chat's persisted context before native reads."""
        def read():
            path, metadata, _ = self.rollouts.metadata(identity)
            if sessions.canonical_root(metadata["cwd"]) != sessions.canonical_root(target):
                raise HarnessError("Desktop created a different saved root; preserve the acknowledged chat ID")
            return sessions.latest_settings(path)
        try:
            return read()
        except (MissingRollout, sessions.MissingSavedSettings):
            pass
        condition, generation, failure = threading.Condition(), 0, None
        suffix = "-" + identity.lower() + ".jsonl"
        def changed(names):
            nonlocal generation
            if names is None or any(str(name).lower().endswith(suffix) for name in names):
                with condition:
                    generation += 1
                    condition.notify_all()
        def failed(error):
            nonlocal failure
            with condition:
                failure = HarnessError("Desktop creation observation failed: " + type(error).__name__)
                condition.notify_all()
        with sessions.deadline_scope(timeout=30):
            directory = _unlinked(self.rollouts.home / "sessions", self.rollouts.home)
            if not directory.is_dir():
                raise HarnessError("Desktop session directory is unavailable; retain the acknowledged chat ID")
            watcher = self.watcher_factory(directory, changed, failed, recursive=True)
            try:
                while True:
                    with condition:
                        observed = generation
                        if failure:
                            raise failure
                    try:
                        return read()  # Includes writes during watch registration.
                    except (MissingRollout, sessions.MissingSavedSettings):
                        with condition:
                            if not condition.wait_for(lambda: generation != observed or failure is not None,
                                                      timeout=sessions.remaining_timeout()):
                                raise
                            if failure:
                                raise failure
            finally:
                watcher.close()

    def archive_state(self, thread_id):
        """Read the exact rollout's native archive location, without another writer."""
        # A lifecycle readback deliberately refreshes identity lookup: a previous
        # path can have moved, or a conflicting duplicate can now exist.
        self.rollouts.cache.pop(_identity(thread_id), None)
        path, _, _ = self.rollouts.metadata(thread_id)
        if path.is_relative_to(self.rollouts.home / "archived_sessions"):
            return True
        if path.is_relative_to(self.rollouts.home / "sessions"):
            return False
        raise HarnessError("Desktop rollout archive state has no verified native owner")

    def _turns_page(self, params):
        identity, cursor = params["threadId"], params.get("cursor")
        direction, limit = params.get("sortDirection", "desc"), params.get("limit", 100)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise HarnessError("Desktop history limit must be between 1 and 100")
        if direction == "desc":
            if cursor is not None and (not isinstance(cursor, str) or not cursor.startswith("desktop-older:")):
                raise HarnessError("Unsupported Desktop descending history cursor")
            _, turns, page = self._native(identity, cursor=cursor.split(":", 1)[1] if cursor else None, limit=limit)
            more = "desktop-older:" + page["nextCursor"] if page["hasMore"] else None
        elif direction == "asc":
            if cursor is not None and (not isinstance(cursor, str) or not cursor.startswith(("desktop-anchor:", "desktop-after:"))):
                raise HarnessError("Unsupported Desktop ascending history cursor")
            anchor = cursor.split(":", 1)[1] if cursor else None
            turns = list(reversed(self._history(identity, stop=anchor)))
            if cursor and cursor.startswith("desktop-after:"):
                turns = turns[1:]
            turns, remaining = turns[:limit], turns[limit:]
            more = "desktop-after:" + turns[-1]["id"] if remaining and turns else None
        else:
            raise HarnessError("Unsupported Desktop history direction")
        data = turns if params.get("itemsView", "full") == "full" else [{key: value for key, value in turn.items() if key != "items"} for turn in turns]
        return {"data": data, "nextCursor": more,
                "backwardsCursor": "desktop-anchor:" + turns[0]["id"] if turns else None}

    def call(self, method, params, *, timeout=30):
        with sessions.deadline_scope(timeout=timeout):
            if method == "project/list":
                return {"data": [{"id": row["projectId"], "roots": [{"path": row["path"]}]}
                        for row in self._projects() if row.get("projectKind") == "local" and row.get("hostId") == "local" and row.get("path")], "nextCursor": None}
            if method == "thread/read":
                return {"thread": self._thread(params["threadId"], include_turns=params.get("includeTurns", False), timeout=timeout)}
            if method == "thread/turns/list":
                return self._turns_page(params)
            if method == "thread/items/list":
                turns = self._history(params["threadId"], stop=params["turnId"])
                items = turns[-1]["items"]
                if params.get("sortDirection") == "desc":
                    items = list(reversed(items))
                cursor = params.get("cursor")
                if cursor:
                    anchor = (cursor.get("itemId") if isinstance(cursor, dict) else
                              cursor.split(":", 1)[1] if isinstance(cursor, str) and cursor.startswith("desktop-item:") else None)
                    matches = [index for index, item in enumerate(items) if item.get("id") == anchor]
                    if len(matches) != 1:
                        raise HarnessError("Desktop item anchor is unavailable")
                    items = items[matches[0] + 1:]
                limit = params.get("limit", 100)
                if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
                    raise HarnessError("Desktop item history limit must be between 1 and 100")
                data = items[:limit]
                return {"data": [{"turnId": params["turnId"], "item": item} for item in data],
                        "nextCursor": "desktop-item:" + data[-1]["id"] if len(items) > len(data) and data else None}
            if method == "turn/start":
                if "collaborationMode" in params or any(part.get("type") != "text" for part in params.get("input", [])):
                    raise sessions.NativeError(method, {"code": -32601, "message": "Desktop native mode/skill setters unavailable"})
                identity = _identity(params["threadId"])
                before_native, before, _ = self._native(identity, limit=1)
                if before_native["status"]["type"] not in ("idle", "notLoaded"):
                    raise sessions.NativeError(method, {"code": -32602, "message": "Recipient is active; preserve its current turn"})
                prompt = "\n".join(part["text"] for part in params["input"])
                _bounded_prompt(prompt, self.source_id)
                result = self._tool("send_message_to_thread", {"threadId": identity, "hostId": "local", "prompt": prompt},
                                    call_id=params.get("clientUserMessageId"), mutation=True)
                if result.get("threadId") != identity:
                    raise HarnessError("Desktop send acknowledged another chat; preserve uncertainty")
                _, after, _ = self._native(identity, limit=10)
                excluded = {item.get("id") for turn in before for item in turn["items"]}
                turn_id = self._prompt_turn(after, prompt, self.source_id, excluded)
                if turn_id in {turn["id"] for turn in before}:
                    raise HarnessError("Desktop send did not establish a new native turn; preserve uncertainty")
                return {"turn": {"id": turn_id}}
            if method in ("thread/archive", "thread/unarchive", "thread/name/set"):
                identity = _identity(params["threadId"])
                if method == "thread/name/set":
                    return self._tool("set_thread_title", {"threadId": identity, "title": params["name"]}, mutation=True)
                return self._tool("set_thread_archived", {"threadId": identity, "hostId": "local", "archived": method == "thread/archive"}, mutation=True)
            if method == "fs/watch":
                return self._watch(params["watchId"], params["path"])
            if method == "fs/unwatch":
                return self._unwatch(params["watchId"])
            raise sessions.NativeError(method, {"code": -32601, "message": "Method unavailable through Desktop tools"})

    def pages(self, method, params, *, timeout=30):
        with sessions.deadline_scope(timeout=timeout):
            seen = set()
            while True:
                page = self.call(method, params, timeout=sessions.remaining_timeout(timeout))
                yield from page["data"]
                cursor = page.get("nextCursor")
                if not cursor:
                    return
                key = json.dumps(cursor, sort_keys=True)
                if key in seen:
                    raise HarnessError("Desktop pagination repeated its cursor")
                seen.add(key)
                params = {**params, "cursor": cursor}

    def _watch(self, watch_id, path):
        sessions.require_text(watch_id, "Desktop watch ID")
        path = Path(os.path.abspath(path))
        if sessions.canonical_root(path) in self.verified_paths:
            _unlinked(path, self.rollouts.home)
        else:
            roots = [root for root in self.roots.values() if path == root / ".oasis/local" or root / ".oasis/local" in path.parents]
            if len(roots) != 1:
                raise HarnessError("Desktop watch must use a verified rollout or project-local operational path")
            _unlinked(path, roots[0])
        directory = path if path.is_dir() else path.parent
        key = sessions.canonical_root(directory)
        with self.condition:
            if self.closed or watch_id in self.watches or len(self.watches) >= 256:
                raise HarnessError("Desktop watch is closed, duplicated or exceeds its bound")
            self.watches[watch_id] = {"path": path, "directory": key, "all": path == directory}
            try:
                if key not in self.directories:
                    self.directories[key] = self.watcher_factory(directory,
                        lambda names: self._changed(key, directory, names), self._watch_failed)
            except Exception:
                self.watches.pop(watch_id, None)
                raise
        return {"path": str(path)}

    def _changed(self, key, directory, names):
        with self.condition:
            if self.closed:
                return
            changed = [str(directory / name) for name in names] if names is not None else None
            for watch_id, row in self.watches.items():
                if row["directory"] != key:
                    continue
                paths = changed if row["all"] else [str(row["path"])] if changed is None or any(sessions.canonical_root(value) == sessions.canonical_root(row["path"]) for value in changed) else []
                if paths is None:
                    paths = [str(row["path"])]
                if paths:
                    if len(self.events) >= self.MAX_EVENTS:
                        self._watch_failed(HarnessError("Desktop filesystem notification buffer overflow; reconcile once"))
                        break
                    self.events.append({"method": "fs/changed", "params": {"watchId": watch_id, "changedPaths": paths}})
            self.condition.notify_all()

    def _watch_failed(self, error):
        with self.condition:
            self.event_error = self.event_error or HarnessError(f"Desktop filesystem observation failed: {type(error).__name__}")
            self.condition.notify_all()

    def _unwatch(self, watch_id):
        watcher = None
        with self.condition:
            row = self.watches.pop(watch_id, None)
            if row and not any(value["directory"] == row["directory"] for value in self.watches.values()):
                watcher = self.directories.pop(row["directory"])
        if watcher:
            watcher.close()
        return {}

    def drain_events(self):
        with self.condition:
            if self.event_error is not None and not self.event_error_reported:
                self.event_error_reported = True
                raise self.event_error
            events, self.events = list(self.events), deque()
            return events

    def wait_events(self, timeout=30):
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout < 0:
            raise HarnessError("Desktop event wait must be finite and nonnegative")
        deadline = time.monotonic() + sessions.remaining_timeout(timeout)
        with self.condition:
            while not self.events and not self.closed and not self.event_error:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.condition.wait(remaining)
            return self.drain_events()

    def diagnostics(self):
        with self.condition:
            return {"backend": self.backend, "state": "closed" if self.closed else "ready",
                    "event_error": str(self.event_error) if self.event_error else None,
                    "buffered_events": len(self.events), "watched_directories": len(self.directories),
                    "rpc_by_method": dict(self.calls), "rpc_by_method_complete": True}

    def close(self):
        with self.condition:
            if self.closed:
                return
            self.closed = True
            watchers, self.directories = list(self.directories.values()), {}
            self.watches.clear()
            self.condition.notify_all()
        for watcher in watchers:
            watcher.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
