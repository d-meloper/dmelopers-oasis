"""Bounded calls to the inherited Desktop tools pipe; never starts a host.

Each request owns one byte stream and is sent once. The workflow journal owns
reconciliation: a transport failure after writing starts is not permission to
repeat a mutation, even when the caller supplies the same tool call ID.
"""
from __future__ import annotations

import json
import math
import os
import struct
import time
import uuid

from .common import HarnessError

MAX_BYTES = 8 * 1024 * 1024
_PIPE_PREFIX = "\\\\.\\pipe\\"


class DesktopToolsError(HarnessError):
    """A Desktop request failed without exposing its prompt or raw transport."""


class DesktopNotSent(DesktopToolsError):
    """No request bytes were issued; the caller can retain that known boundary."""


class DesktopUncertain(DesktopToolsError):
    """A request may have applied; reconcile its journal before another send."""


class DesktopRejected(DesktopToolsError):
    """A valid failure reply was received; this does not establish rollback."""
    def __init__(self, message, *, code=None):
        super().__init__(message)
        self.code = code


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise DesktopNotSent(f"Desktop {label} must be a nonempty string")
    return value


def _pipe_path(value):
    _text(value, "pipe path")
    tail = value[len(_PIPE_PREFIX):]
    if not value.casefold().startswith(_PIPE_PREFIX.casefold()) or not tail or any(c in tail for c in "\\/\r\n"):
        raise DesktopNotSent("Desktop tools require an inherited local Windows named pipe")
    return value


def _encode(value):
    try:
        payload = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise DesktopNotSent("Desktop request must contain bounded UTF-8 JSON") from None
    if not 0 < len(payload) <= MAX_BYTES:
        raise DesktopNotSent("Desktop request exceeds the 8 MiB frame limit")
    return struct.pack("<I", len(payload)) + payload


def _decode(payload):
    def fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate field")
            result[key] = value
        return result
    def number(value):
        value = float(value)
        if not math.isfinite(value):
            raise ValueError("Nonfinite number")
        return value
    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=fields, parse_float=number,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Invalid number")))
    except (UnicodeError, ValueError, RecursionError):
        raise DesktopUncertain("Desktop returned invalid UTF-8 JSON; reconcile the retained request") from None
    if not isinstance(value, dict):
        raise DesktopUncertain("Desktop response must be a JSON object; reconcile the retained request")
    return value


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Desktop tools deadline expired")
    return remaining


class _WindowsPipe:
    """Windows overlapped byte I/O; no background thread outlives a request."""
    def __init__(self, path, deadline):
        if os.name != "nt":
            raise OSError("Desktop tools pipe is only available on Windows")
        import _winapi
        self.api = _winapi
        self.handle = None
        milliseconds = min(0xFFFFFFFE, max(1, math.ceil(_remaining(deadline) * 1000)))
        _winapi.WaitNamedPipe(path, milliseconds)
        _remaining(deadline)
        self.handle = _winapi.CreateFile(path, _winapi.GENERIC_READ | _winapi.GENERIC_WRITE, 0,
                                         0, _winapi.OPEN_EXISTING, _winapi.FILE_FLAG_OVERLAPPED, 0)
        try:
            # Reuse the existing same-account peer check, not multiprocessing framing.
            from .shared_runtime import _same_user
            if not _same_user(self, server_side=False):
                raise OSError("Desktop tools pipe peer is not the current account")
            _remaining(deadline)
        except BaseException:
            self.close(deadline=deadline)
            raise

    def fileno(self):
        return self.handle

    def _io(self, data, deadline, *, write):
        api = self.api
        _remaining(deadline)
        if self.handle is None:
            raise OSError("Desktop tools pipe is closed")
        operation, error = (api.WriteFile if write else api.ReadFile)(self.handle, data, overlapped=True)
        try:
            if error == api.ERROR_IO_PENDING:
                milliseconds = min(0xFFFFFFFE, max(1, math.ceil(_remaining(deadline) * 1000)))
                if api.WaitForSingleObject(operation.event, milliseconds) != api.WAIT_OBJECT_0:
                    raise TimeoutError("Desktop tools pipe I/O deadline expired")
            count, error = operation.GetOverlappedResult(False)
            if error:
                raise OSError("Desktop tools pipe I/O failed")
            _remaining(deadline)
            return count if write else bytes(operation.getbuffer())[:count]
        except BaseException as original:
            try:
                operation.cancel()
            except OSError:
                original.add_note("The owned Desktop I/O also reported a cancellation failure")
            # Named-pipe cancellation has a separate finite cleanup wait, even
            # after the request deadline. Never wait indefinitely for a reply.
            try:
                self.close(deadline=deadline)
            except OSError:
                original.add_note("The owned Desktop I/O also reported a close failure")
            if api.WaitForSingleObject(operation.event, 500) != api.WAIT_OBJECT_0:
                original.add_note("Desktop pipe cancellation did not settle within its cleanup budget")
            else:
                try:
                    operation.GetOverlappedResult(False)
                except OSError:
                    pass
            raise

    def read(self, size, *, deadline):
        return self._io(size, deadline, write=False)

    def write(self, data, *, deadline):
        return self._io(data, deadline, write=True)

    def close(self, *, deadline=None):
        handle, self.handle = self.handle, None
        if handle is not None:
            self.api.CloseHandle(handle)


class DesktopTools:
    def __init__(self, pipe_path, thread_id, turn_id, host_id="local", *, opener=None):
        self.pipe_path = _pipe_path(pipe_path)
        self.thread_id = _text(thread_id, "caller chat ID")
        self.turn_id = _text(turn_id, "caller turn ID")
        self.host_id = _text(host_id, "caller host ID")
        self.opener = opener or _WindowsPipe

    def _request(self, method, params, timeout):
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise DesktopNotSent("Desktop timeout must be finite and positive")
        from . import sessions
        try:
            deadline = time.monotonic() + sessions.remaining_timeout(timeout)
        except sessions.DeadlineExceeded:
            raise DesktopNotSent("Desktop deadline expired before dispatch") from None
        identity = uuid.uuid4().hex
        frame = _encode({"id": identity, "jsonrpc": "2.0", "method": method, "params": params})
        stream, issued, failure = None, False, None
        try:
            _remaining(deadline)
            stream = self.opener(self.pipe_path, deadline)
            offset = 0
            while offset < len(frame):
                _remaining(deadline)
                issued = True
                count = stream.write(frame[offset:], deadline=deadline)
                if type(count) is not int or not 0 < count <= len(frame) - offset:
                    raise OSError("Invalid Desktop pipe write")
                offset += count
            def read(size):
                chunks = bytearray()
                while len(chunks) < size:
                    _remaining(deadline)
                    part = stream.read(size - len(chunks), deadline=deadline)
                    if not isinstance(part, bytes) or not part or len(part) > size - len(chunks):
                        raise OSError("Desktop pipe closed or returned invalid bytes")
                    chunks.extend(part)
                return bytes(chunks)
            size = struct.unpack("<I", read(4))[0]
            if not 0 < size <= MAX_BYTES:
                raise DesktopUncertain("Desktop response exceeds the frame boundary; reconcile the retained request")
            reply = _decode(read(size))
            _remaining(deadline)
            if (reply.get("jsonrpc") != "2.0" or type(reply.get("id")) is not str or reply["id"] != identity
                    or ("result" in reply) == ("error" in reply)):
                raise DesktopUncertain("Desktop returned an unmatched response; reconcile the retained request")
            if "error" in reply:
                error = reply["error"]
                if not isinstance(error, dict) or type(error.get("code")) is not int or not isinstance(error.get("message"), str):
                    raise DesktopUncertain("Desktop returned an invalid error reply; reconcile the retained request")
                raise DesktopRejected(f"Desktop rejected the request (code {error['code']})", code=error["code"])
            if not isinstance(reply["result"], dict):
                raise DesktopUncertain("Desktop returned an invalid result; reconcile the retained request")
            return reply["result"]
        except DesktopToolsError as exc:
            failure = exc
            raise
        except Exception:
            failure = (DesktopUncertain("Desktop delivery is uncertain; reconcile the retained request before another send")
                       if issued else DesktopNotSent("Desktop tools pipe unavailable before dispatch"))
            raise failure from None
        finally:
            if stream is not None:
                try:
                    stream.close(deadline=deadline)
                except Exception:
                    if failure is not None:
                        failure.add_note("The owned Desktop pipe also reported a cleanup failure")
                    else:
                        raise DesktopUncertain("Desktop returned a reply but owned pipe cleanup failed") from None

    def call(self, tool, arguments, *, timeout=30, call_id=None):
        _text(tool, "tool name")
        if not isinstance(arguments, dict):
            raise DesktopNotSent("Desktop tool arguments must be an object")
        result = self._request("tools/call", {"arguments": arguments, "callerSource": "codex",
                               "callId": _text(call_id, "call ID") if call_id is not None else uuid.uuid4().hex,
                               "hostId": self.host_id, "namespace": "codex_app", "threadId": self.thread_id,
                               "tool": tool, "turnId": self.turn_id}, timeout)
        if type(result.get("success")) is not bool or not isinstance(result.get("contentItems"), list):
            raise DesktopUncertain("Desktop returned an invalid tool result; reconcile the retained request")
        fields = {"inputText": "text", "inputImage": "imageUrl", "inputAudio": "audioUrl"}
        if any(not isinstance(item, dict) or item.get("type") not in fields
               or not isinstance(item.get(fields[item["type"]]), str) for item in result["contentItems"]):
            raise DesktopUncertain("Desktop returned invalid tool content; reconcile the retained request")
        if not result["success"]:
            raise DesktopRejected("Desktop tool reported failure; inspect the retained task before another mutation")
        items = result["contentItems"]
        if len(items) != 1 or not isinstance(items[0], dict) or items[0].get("type") != "inputText" or not isinstance(items[0].get("text"), str):
            raise DesktopUncertain("Desktop tool returned unsupported content; reconcile the retained request")
        try:
            return _decode(items[0]["text"].encode("utf-8"))
        except UnicodeError:
            raise DesktopUncertain("Desktop tool returned invalid text; reconcile the retained request") from None

    def list_tools(self, *, timeout=30):
        result = self._request("tools/list", {"threadStartKind": "all"}, timeout)
        tools = result.get("tools")
        if not isinstance(tools, list) or any(not isinstance(tool, dict) or not isinstance(tool.get("name"), str)
                or not tool["name"].strip() or not isinstance(tool.get("namespace"), str)
                or not isinstance(tool.get("inputSchema"), dict) for tool in tools):
            raise DesktopUncertain("Desktop returned an invalid tool catalog")
        return [tool for tool in tools if tool["namespace"] == "codex_app"]
