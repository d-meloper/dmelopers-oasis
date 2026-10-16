"""Native Codex sessions and one-shot delivery, without editing app storage."""
from __future__ import annotations

import base64
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import socket
import struct
import subprocess
import threading
import time
import uuid
from urllib.parse import urlsplit

from .common import HarnessError, clean_environment, contained, digest, operation_lock, read_json, write_json
from . import __version__

SOURCES = ["cli", "vscode", "exec", "appServer", "subAgent", "subAgentReview", "subAgentCompact", "subAgentThreadSpawn", "subAgentOther", "unknown"]
ROLES = ("Oasis", "Cameleer", "Camel", "Pioneer", "Developer")
COMMAND_DELTAS = ("item/agentMessage/delta", "item/reasoning/summaryTextDelta", "item/reasoning/textDelta",
                  "item/commandExecution/outputDelta", "item/fileChange/outputDelta")
CREATION_RETRYABLE = ("prepared", "creation_rejected")
_operation_deadline = ContextVar("oasis_native_operation_deadline", default=None)
_command_context = ContextVar("oasis_native_command_context", default=None)


class DeadlineExceeded(HarnessError):
    """An operation's shared absolute deadline expired, including its cleanup."""


def _valid_seconds(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise HarnessError(f"{label} must be finite and nonnegative")
    return value


def _earliest_deadline(deadline=None):
    values = [value for value in (_operation_deadline.get(), deadline) if value is not None]
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
        raise HarnessError("Native absolute deadline must be finite")
    return min(values) if values else None


def remaining_timeout(default=30, *, deadline=None):
    """Cap an I/O budget to the enclosing operation without renewing its clock."""
    _valid_seconds(default, "Native timeout")
    deadline = _earliest_deadline(deadline)
    if deadline is None:
        return default
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise DeadlineExceeded("Native operation deadline expired; resume from the saved state")
    return min(default, remaining)


@contextmanager
def deadline_scope(timeout=None, *, deadline=None):
    """Share one monotonic budget across creation, calls, I/O and cleanup.

    Factories keep their existing signature. Nested scopes may shorten, never
    extend, an outer budget; independent threads do not inherit a caller's scope.
    """
    deadline = _earliest_deadline(deadline)
    if timeout is not None:
        _valid_seconds(timeout, "Native operation timeout")
        candidate = time.monotonic() + timeout
        deadline = candidate if deadline is None else min(candidate, deadline)
    token = _operation_deadline.set(deadline)
    try:
        remaining_timeout(deadline=deadline)
        yield deadline
    finally:
        _operation_deadline.reset(token)


def _cleanup_timeout(default, deadline=None):
    """Cleanup must still release owned resources after the operation expires."""
    try:
        return remaining_timeout(default, deadline=deadline)
    except DeadlineExceeded:
        return 0


class NativeError(HarnessError):
    """A definite native rejection, distinct from a lost mutation response."""

    def __init__(self, method, error):
        self.method = method
        self.error = dict(error)
        self.code = error.get("code")
        super().__init__(f"{method}: rejected ({self.code}): {error.get('message', 'native API error')}")


class MissingSavedSettings(HarnessError):
    """A rollout has no settings record yet, rather than a damaged record."""


def canonical_root(path):
    resolved = os.path.realpath(path)
    if resolved.startswith("\\\\?\\UNC\\"):
        resolved = "\\\\" + resolved[8:]
    elif resolved.startswith("\\\\?\\"):
        resolved = resolved[4:]
    return os.path.normcase(resolved)


class _WebSocketEOF(Exception):
    pass


class _LoopbackWebSocket:
    """RFC 6455 text transport for an explicitly supplied experimental endpoint.

    This connects to an existing server. It neither starts a server nor owns
    that server's process or turns. No extensions or authentication are inferred.
    """
    MAX_MESSAGE = 64 * 1024 * 1024
    GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    supports_close_deadline = True

    @staticmethod
    def endpoint(value):
        error = "OASIS_APP_SERVER_URL must be an explicit loopback ws:// URL without credentials or a fragment"
        if not isinstance(value, str) or not value or any(ord(char) <= 32 or ord(char) == 127 for char in value):
            raise HarnessError(error)
        try:
            parsed = urlsplit(value)
            host = parsed.hostname
            port = parsed.port if parsed.port is not None else 80
            if (parsed.scheme != "ws" or not host or parsed.username is not None or parsed.password is not None
                    or "#" in value or not 1 <= port <= 65535 or "%" in host):
                raise ValueError
            if host.casefold() == "localhost":
                address = "127.0.0.1"  # Do not resolve a hostname outside loopback.
            else:
                address = str(ipaddress.ip_address(host))
                if not ipaddress.ip_address(address).is_loopback:
                    raise ValueError
            target = parsed.path or "/"
            if parsed.query:
                target += "?" + parsed.query
            target.encode("ascii")
            authority = (f"[{host}]" if ":" in host else host) + f":{port}"
        except (ValueError, UnicodeError):
            raise HarnessError(error) from None
        return address, port, target, authority

    def __init__(self, url, *, deadline=None):
        address, port, target, authority = self.endpoint(url)
        self._open(lambda timeout: socket.create_connection((address, port), timeout=timeout),
                   target, authority, deadline=deadline)

    def _open(self, connect, target, authority, *, deadline=None):
        self.socket = None
        self.buffer = bytearray()
        self.write_lock = threading.RLock()
        self.closed = False
        self.sent_close = False
        # One handshake budget also covers a peer dripping headers slowly.
        handshake_deadline = time.monotonic() + remaining_timeout(10, deadline=deadline)
        try:
            self.socket = connect(remaining_timeout(10, deadline=handshake_deadline))
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            request = (f"GET {target} HTTP/1.1\r\nHost: {authority}\r\nUpgrade: websocket\r\n"
                       f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
            self.socket.settimeout(remaining_timeout(10, deadline=handshake_deadline))
            self.socket.sendall(request.encode("ascii"))
            header = bytearray()
            while b"\r\n\r\n" not in header:
                self.socket.settimeout(remaining_timeout(10, deadline=handshake_deadline))
                chunk = self.socket.recv(4096)
                if not chunk:
                    raise HarnessError("Native WebSocket handshake ended before an upgrade response")
                header.extend(chunk)
                if len(header) > 65536:
                    raise HarnessError("Native WebSocket handshake headers exceed the supported size")
            raw, remainder = bytes(header).split(b"\r\n\r\n", 1)
            lines = raw.decode("iso-8859-1").split("\r\n")
            status = lines[0].split(" ", 2)
            if len(status) < 2 or status[:2] != ["HTTP/1.1", "101"]:
                raise HarnessError("Native WebSocket endpoint did not accept the protocol upgrade")
            headers = {}
            for line in lines[1:]:
                if ":" not in line or line[:1] in (" ", "\t"):
                    raise HarnessError("Native WebSocket upgrade contains an invalid header")
                name, value = line.split(":", 1)
                if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name):
                    raise HarnessError("Native WebSocket upgrade contains an invalid header")
                headers.setdefault(name.casefold(), []).append(value.strip())
            tokens = lambda name: {part.strip().casefold() for value in headers.get(name, []) for part in value.split(",")}
            expected = base64.b64encode(hashlib.sha1((key + self.GUID).encode("ascii"), usedforsecurity=False).digest()).decode("ascii")
            if ("websocket" not in tokens("upgrade") or "upgrade" not in tokens("connection")
                    or headers.get("sec-websocket-accept") != [expected]
                    or "sec-websocket-extensions" in headers or "sec-websocket-protocol" in headers):
                raise HarnessError("Native WebSocket handshake acceptance or negotiation is invalid")
            self.buffer.extend(remainder)
            self.socket.settimeout(None)
        except TimeoutError:
            self._drop()
            raise DeadlineExceeded("Native WebSocket connection deadline expired") from None
        except OSError:
            self._drop()
            raise HarnessError("Native loopback WebSocket is unavailable; supply the address of an already running caller-managed App Server") from None
        except Exception:
            self._drop()
            raise

    def _drop(self):
        self.closed = True
        if self.socket is not None:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.socket.close()

    def _exact(self, size):
        while len(self.buffer) < size:
            chunk = self.socket.recv(min(65536, size - len(self.buffer)))
            if not chunk:
                raise _WebSocketEOF
            self.buffer.extend(chunk)
        result = bytes(self.buffer[:size])
        del self.buffer[:size]
        return result

    def _frame(self, opcode, payload, *, timeout=30):
        deadline = time.monotonic() + timeout
        if self.closed:
            raise OSError("WebSocket connection is closed")
        length = len(payload)
        if length > self.MAX_MESSAGE or (opcode >= 8 and length > 125):
            raise HarnessError("Native WebSocket outgoing message exceeds the supported size")
        header = bytes((0x80 | opcode,))
        if length < 126:
            header += bytes((0x80 | length,))
        elif length <= 65535:
            header += bytes((0x80 | 126,)) + struct.pack("!H", length)
        else:
            header += bytes((0x80 | 127,)) + struct.pack("!Q", length)
        mask = os.urandom(4)
        encoded = bytearray()
        for offset in range(0, length, 16384):
            if time.monotonic() >= deadline:
                raise TimeoutError("Native WebSocket write deadline expired")
            encoded.extend(byte ^ mask[(offset + index) % 4] for index, byte in enumerate(payload[offset:offset + 16384]))
        finished = threading.Event()
        errors = []

        def write():
            acquired = False
            try:
                acquired = self.write_lock.acquire(timeout=max(0, deadline - time.monotonic()))
                if not acquired:
                    raise TimeoutError("Native WebSocket write deadline expired")
                if self.closed:
                    raise OSError("WebSocket connection is closed")
                if time.monotonic() >= deadline:
                    raise TimeoutError("Native WebSocket write deadline expired")
                if opcode != 8 or not self.sent_close:
                    self.socket.sendall(header + mask + encoded)
                    if opcode == 8:
                        self.sent_close = True
            except Exception as exc:
                errors.append(exc)
            finally:
                if acquired:
                    self.write_lock.release()
                finished.set()

        # Changing this socket's timeout would also interrupt the idle reader.
        # A bounded writer lets shutdown release a saturated sendall instead.
        threading.Thread(target=write, daemon=True).start()
        if not finished.wait(max(0, deadline - time.monotonic())):
            self._drop()
            raise TimeoutError("Native WebSocket write deadline expired")
        if errors:
            self._drop()
            raise errors[0]

    def send(self, text, *, timeout=30):
        deadline = time.monotonic() + timeout
        payload = text.encode("utf-8")
        if time.monotonic() >= deadline:
            raise TimeoutError("Native WebSocket write deadline expired")
        self._frame(1, payload, timeout=max(0, deadline - time.monotonic()))

    def _close_frame(self, payload, *, deadline=None):
        try:
            timeout = _cleanup_timeout(0.2, deadline)
            if not self.sent_close and timeout > 0:
                self._frame(8, payload, timeout=timeout)
        except OSError:
            pass
        finally:
            self._drop()

    def _fail(self, message, code=1002):
        self._close_frame(struct.pack("!H", code))
        raise HarnessError(message)

    def _text(self, payload):
        try:
            return payload.decode("utf-8")
        except UnicodeError:
            self._fail("Native WebSocket text is not valid UTF-8", 1007)

    def receive(self):
        fragments = None
        try:
            while not self.closed:
                first, second = self._exact(2)
                final, opcode = bool(first & 0x80), first & 0x0f
                if first & 0x70 or second & 0x80:
                    self._fail("Native WebSocket has unsupported extensions or a masked server frame")
                length = second & 0x7f
                if opcode >= 8 and (not final or length > 125):
                    self._fail("Native WebSocket control frame is fragmented or oversized")
                if length == 126:
                    length = struct.unpack("!H", self._exact(2))[0]
                    if length < 126:
                        self._fail("Native WebSocket frame uses a nonminimal length")
                elif length == 127:
                    length = struct.unpack("!Q", self._exact(8))[0]
                    if length < 65536 or length & (1 << 63):
                        self._fail("Native WebSocket frame length is invalid")
                if length > self.MAX_MESSAGE or (fragments is not None and len(fragments) + length > self.MAX_MESSAGE and opcode < 8):
                    self._fail("Native WebSocket message exceeds the supported size", 1009)
                payload = self._exact(length)
                if opcode == 8:
                    if len(payload) == 1:
                        self._fail("Native WebSocket close payload is invalid")
                    if payload:
                        code = struct.unpack("!H", payload[:2])[0]
                        if code not in (1000, 1001, 1002, 1003, 1007, 1008, 1009, 1010, 1011, 1012, 1013, 1014) and not 3000 <= code <= 4999:
                            self._fail("Native WebSocket close status is invalid")
                        self._text(payload[2:])
                    self._close_frame(payload)
                    return None
                if opcode == 9:
                    self._frame(10, payload)
                    continue
                if opcode == 10:
                    continue
                if opcode == 2:
                    self._fail("Native App Server transport requires WebSocket text messages", 1003)
                if opcode == 1:
                    if fragments is not None:
                        self._fail("Native WebSocket starts a message before finishing its fragmented predecessor")
                    if final:
                        return self._text(payload)
                    fragments = bytearray(payload)
                elif opcode == 0:
                    if fragments is None:
                        self._fail("Native WebSocket continuation has no preceding message")
                    fragments.extend(payload)
                    if final:
                        return self._text(fragments)
                else:
                    self._fail("Native WebSocket frame opcode is unsupported")
        except _WebSocketEOF:
            self._drop()
            return None

    def close(self, *, deadline=None):
        if self.closed:
            return
        self._close_frame(struct.pack("!H", 1000), deadline=deadline)


class _ProxyStream:
    """Bounded byte stream through our proxy process, without JSONL framing."""
    MAX_MESSAGE = _LoopbackWebSocket.MAX_MESSAGE
    STDERR_LIMIT = 64 * 1024
    supports_close_deadline = True

    def __init__(self, executable, socket_path=None, *, deadline=None):
        command = [executable, "app-server", "proxy"]
        if socket_path:
            command += ["--sock", socket_path]
        deadline = _earliest_deadline(deadline)
        remaining_timeout(deadline=deadline)

        def launch():
            return subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, bufsize=0, env=clean_environment(),
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

        if deadline is None:
            self.process = launch()
        else:
            # Process creation itself cannot be interrupted on every platform.
            # Return on time and release any late result; it is only our proxy.
            result, abandoned = queue.Queue(maxsize=1), threading.Event()

            def discard(process):
                try:
                    process.terminate()
                    process.wait(timeout=0.2)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        process.kill()
                    except OSError:
                        pass
                for stream in (process.stdin, process.stdout, process.stderr):
                    try:
                        stream.close()
                    except (OSError, ValueError):
                        pass

            def start():
                try:
                    value = launch()
                except Exception as exc:
                    value = exc
                if abandoned.is_set():
                    if not isinstance(value, Exception):
                        discard(value)
                    return
                result.put_nowait(value)
                if abandoned.is_set():
                    try:
                        value = result.get_nowait()
                    except queue.Empty:
                        return
                    if not isinstance(value, Exception):
                        discard(value)

            threading.Thread(target=start, daemon=True).start()
            try:
                self.process = result.get(timeout=remaining_timeout(30, deadline=deadline))
            except (queue.Empty, DeadlineExceeded):
                abandoned.set()
                try:
                    late = result.get_nowait()
                except queue.Empty:
                    pass
                else:
                    if not isinstance(late, Exception):
                        threading.Thread(target=discard, args=(late,), daemon=True).start()
                raise DeadlineExceeded("Native proxy connection deadline expired") from None
            if isinstance(self.process, Exception):
                raise self.process
        self.buffer = bytearray()
        self.closed = False
        self.write_lock = threading.Lock()
        self.close_lock = threading.Lock()
        self.stderr_lock = threading.Lock()
        self.stderr_buffer = bytearray()
        self.stderr_bytes = 0
        self.stderr_reader = threading.Thread(target=self._stderr, daemon=True)
        self.stderr_reader.start()
        self.timeout = None
        self.eof = False
        self.chunks = queue.Queue(maxsize=16)
        self.stdout_reader = threading.Thread(target=self._stdout, daemon=True)
        self.stdout_reader.start()

    def _stdout(self):
        while not self.closed:
            try:
                block = self.process.stdout.read(65536)
            except (OSError, ValueError):
                block = b""
            while not self.closed:
                try:
                    self.chunks.put(block, timeout=0.05)
                    break
                except queue.Full:
                    continue
            if not block:
                return

    def settimeout(self, value):
        self.timeout = value

    def _stderr(self):
        try:
            while chunk := self.process.stderr.read(4096):
                with self.stderr_lock:
                    self.stderr_bytes += len(chunk)
                    self.stderr_buffer.extend(chunk)
                    del self.stderr_buffer[:-self.STDERR_LIMIT]
        except (OSError, ValueError):
            pass

    def stderr_tail(self):
        with self.stderr_lock:
            return self.stderr_buffer.decode("utf-8", errors="replace"), self.stderr_bytes > self.STDERR_LIMIT

    def recv(self, size):
        if self.eof:
            return b""
        if not self.buffer:
            if self.closed and self.chunks.empty():
                return b""
            try:
                self.buffer.extend(self.chunks.get(timeout=self.timeout))
            except queue.Empty:
                raise TimeoutError("Native proxy read deadline expired") from None
            if not self.buffer:
                self.eof = True
        value = bytes(self.buffer[:size])
        del self.buffer[:size]
        return value

    def sendall(self, payload):
        self.write(payload, timeout=self.timeout if self.timeout is not None else 30)

    def write(self, payload, *, timeout=30):
        deadline = time.monotonic() + timeout
        if time.monotonic() >= deadline:
            raise TimeoutError("Native stdio write deadline expired")
        finished, errors = threading.Event(), []

        def write():
            acquired = False
            try:
                acquired = self.write_lock.acquire(timeout=max(0, deadline - time.monotonic()))
                if not acquired:
                    raise TimeoutError("Native stdio write deadline expired")
                if self.closed:
                    raise OSError("Native stdio connection is closed")
                data, offset = payload, 0
                while offset < len(data):
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Native stdio write deadline expired")
                    count = self.process.stdin.write(data[offset:])
                    if not count:
                        raise OSError("Native stdio write ended")
                    offset += count
                self.process.stdin.flush()
            except Exception as exc:
                errors.append(exc)
            finally:
                if acquired:
                    self.write_lock.release()
                finished.set()

        threading.Thread(target=write, daemon=True).start()
        if not finished.wait(max(0, deadline - time.monotonic())):
            self.close(deadline=deadline)
            raise TimeoutError("Native stdio write deadline expired")
        if errors:
            self.close(deadline=deadline)
            raise OSError("Native stdio send failed") from None

    def shutdown(self, _how):
        self.close()

    def close(self, *, deadline=None):
        deadline = deadline if deadline is not None else getattr(self, "cleanup_deadline", None)
        with self.close_lock:
            if self.closed:
                return
            self.closed = True
        try:
            self.chunks.put_nowait(b"")
        except queue.Full:
            pass
        # Closing a buffered stdin during another thread's flush can hang.
        # This proxy uses unbuffered pipes; serialize a graceful EOF, otherwise
        # terminate only our own proxy to release a blocked write.
        acquired = self.write_lock.acquire(timeout=_cleanup_timeout(0.1, deadline))
        try:
            if acquired:
                self.process.stdin.close()
            elif self.process.poll() is None:
                self.process.terminate()
        except (OSError, ValueError):
            pass
        finally:
            if acquired:
                self.write_lock.release()
        try:
            self.process.wait(timeout=_cleanup_timeout(0.25, deadline))
        except subprocess.TimeoutExpired:
            try:
                self.process.terminate()
                self.process.wait(timeout=_cleanup_timeout(0.5, deadline))
            except subprocess.TimeoutExpired:
                self.process.kill()
                try:
                    self.process.wait(timeout=_cleanup_timeout(0.5, deadline))
                except subprocess.TimeoutExpired:
                    pass
            except OSError:
                pass
        except OSError:
            pass
        if self.stderr_reader is not threading.current_thread():
            self.stderr_reader.join(timeout=_cleanup_timeout(0.2, deadline))
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            try:
                stream.close()
            except (OSError, ValueError):
                pass
        if self.stdout_reader is not threading.current_thread():
            self.stdout_reader.join(timeout=_cleanup_timeout(0.2, deadline))


class _ProxyTransport(_LoopbackWebSocket):
    """RFC 6455 over the existing control socket's byte-forwarding CLI proxy."""

    def __init__(self, executable, socket_path=None, *, deadline=None):
        self.proxy = None

        def connect(timeout):
            self.proxy = _ProxyStream(executable, socket_path, deadline=time.monotonic() + timeout)
            self.proxy.settimeout(timeout)
            return self.proxy

        try:
            self._open(connect, "/", "localhost", deadline=deadline)
        except HarnessError as exc:
            if str(exc) not in {"Native WebSocket handshake ended before an upgrade response",
                                "Native loopback WebSocket is unavailable; supply the address of an already running caller-managed App Server"}:
                raise
            raise HarnessError("Native App Server proxy is unavailable; this path requires an already running daemon/control socket with WebSocket support. Select its OASIS_APP_SERVER_SOCKET. No server was started.") from None
        self.process = self.proxy.process

    def stderr_tail(self):
        return self.proxy.stderr_tail()

    def close(self, *, deadline=None):
        if self.proxy is not None:
            self.proxy.cleanup_deadline = deadline
        super().close(deadline=deadline)


class _RpcInbox:
    """Connection-local response waiters and a bounded, separate event buffer."""
    EVENT_LIMIT = 256
    EVENT_BYTES = _LoopbackWebSocket.MAX_MESSAGE

    def __init__(self):
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.sequence = 0
        self.pending = {}
        self.events = deque()
        self.event_bytes = 0
        self.state = "connected"
        self.error = None
        self.event_error = None
        self.event_error_reported = False
        self.unsupported = deque(maxlen=64)
        self.unmatched_responses = 0
        self.calls_by_method = {}

    def register(self, method):
        with self.lock:
            if self.state != "connected":
                raise HarnessError(f"{method}: {self.error or 'connection ended'}; outcome uncertain")
            self.sequence += 1
            waiter = queue.Queue(maxsize=1)
            self.pending[self.sequence] = waiter
            return self.sequence, waiter

    def response(self, value):
        with self.lock:
            waiter = self.pending.get(value["id"])
            if waiter is None or waiter.full():
                self.unmatched_responses += 1
            else:
                waiter.put_nowait(value)

    def notification(self, value, size):
        with self.lock:
            if len(self.events) >= self.EVENT_LIMIT or self.event_bytes + size > self.EVENT_BYTES:
                raise HarnessError("Native App Server event buffer overflow")
            self.events.append(value)
            self.event_bytes += size
            self.changed.notify_all()

    def end(self, reason, *, failed=False, event_error=False):
        with self.lock:
            if self.state != "connected":
                return
            self.state = "failed" if failed else "closed"
            self.error = reason
            if event_error:
                self.event_error = reason
            for waiter in self.pending.values():
                if not waiter.full():
                    waiter.put_nowait(HarnessError(reason))
            self.changed.notify_all()

    def drain(self):
        with self.lock:
            if self.event_error is not None and not self.event_error_reported:
                self.event_error_reported = True
                raise HarnessError(self.event_error)
            values = list(self.events)
            self.events.clear()
            self.event_bytes = 0
            return values

    def wait(self, timeout):
        with self.changed:
            if not self.events and self.state == "connected":
                self.changed.wait_for(lambda: bool(self.events) or self.state != "connected", timeout=timeout)
            return self.drain()


class AppServer:
    def __init__(self, originator, *, notification_profile="all", deadline=None):
        if notification_profile not in ("all", "command"):
            raise HarnessError("Unknown native notification profile")
        self.process = None
        self.transport = None
        self.closing = False
        self._rpc = _RpcInbox()
        self._close_lock = threading.Lock()
        self._deadline = _earliest_deadline(deadline)
        remaining_timeout(deadline=self._deadline)
        self.sequence = 0
        endpoint = os.environ.get("OASIS_APP_SERVER_URL")
        if endpoint is not None:
            self.transport = _LoopbackWebSocket(endpoint, deadline=self._deadline)
            self.backend = "websocket"
        else:
            executable = shutil.which("codex")
            if not executable:
                raise HarnessError("Codex CLI is unavailable; install or select the supported host explicitly")
            self.transport = _ProxyTransport(executable, os.environ.get("OASIS_APP_SERVER_SOCKET"), deadline=self._deadline)
            self.process = self.transport.process
            self.backend = "proxy"
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            capabilities = {"experimentalApi": True}
            if notification_profile == "command":
                capabilities["optOutNotificationMethods"] = list(COMMAND_DELTAS)
            parameters = {"clientInfo": {"name": originator, "version": __version__}, "capabilities": capabilities}
            try:
                self.call("initialize", parameters)
            except NativeError as exc:
                if (notification_profile != "command" or exc.code != -32602
                        or "optoutnotificationmethods" not in str(exc).casefold()):
                    raise
                self.call("initialize", {**parameters, "capabilities": {"experimentalApi": True}})
            self._send({"method": "initialized"})
        except Exception as exc:
            try:
                self.close()
            except Exception as cleanup:
                exc.add_note(f"Native connection cleanup failed: {type(cleanup).__name__}")
            if (self.process is not None and isinstance(exc, HarnessError) and not isinstance(exc, (NativeError, DeadlineExceeded))
                    and self._rpc.event_error is None):
                raise HarnessError("Native App Server proxy is unavailable; this path requires an already running daemon/control socket. Select its OASIS_APP_SERVER_SOCKET, or explicitly supply a caller-managed experimental loopback OASIS_APP_SERVER_URL. No server was started.") from None
            raise

    def _read(self):
        try:
            while (message := self.transport.receive()) is not None:
                value = self._decode(message)
                if "method" not in value:
                    self._rpc.response(value)
                elif "id" not in value:
                    self._rpc.notification(value, len(message.encode("utf-8")))
                else:
                    with self._rpc.lock:
                        self._rpc.unsupported.append(value["method"][:256])
                    self._send({"id": value["id"], "error": {"code": -32601, "message": "Unsupported server request"}},
                               deadline=time.monotonic() + 1)
        except (OSError, ValueError, HarnessError) as exc:
            if not self.closing:
                reason = str(exc) if isinstance(exc, HarnessError) else "Native App Server transport connection ended"
                self._rpc.end(reason, failed=True, event_error=isinstance(exc, HarnessError))
                self._close_transport(getattr(self, "_deadline", None))
        finally:
            self._rpc.end("Native App Server connection ended")

    @staticmethod
    def _decode(message):
        if len(message.encode("utf-8")) > _LoopbackWebSocket.MAX_MESSAGE:
            raise HarnessError("Native App Server message exceeds the supported size")
        def invalid_constant(value):
            raise ValueError("Non-JSON numeric constant")
        def object_fields(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("Duplicate protocol object field")
                value[key] = item
            return value
        try:
            value = json.loads(message, parse_constant=invalid_constant, object_pairs_hook=object_fields)
        except (ValueError, RecursionError):
            raise HarnessError("Native App Server returned invalid JSON") from None
        if not isinstance(value, dict):
            raise HarnessError("Native App Server returned a non-object protocol message")
        if "jsonrpc" in value and value["jsonrpc"] != "2.0":
            raise HarnessError("Native App Server returned an unsupported protocol version")
        if "id" in value and (isinstance(value["id"], bool) or not isinstance(value["id"], (int, str))):
            raise HarnessError("Native App Server returned an invalid protocol ID")
        if "method" in value:
            if (not isinstance(value["method"], str) or not value["method"] or "\0" in value["method"]
                    or "result" in value or "error" in value
                    or ("params" in value and value["params"] is not None and not isinstance(value["params"], (dict, list)))):
                raise HarnessError("Native App Server returned an invalid request/notification envelope")
        else:
            if "id" not in value or ("result" in value) == ("error" in value):
                raise HarnessError("Native App Server returned an invalid response envelope")
            if "error" in value:
                error = value["error"]
                if (not isinstance(error, dict) or isinstance(error.get("code"), bool)
                        or not isinstance(error.get("code"), int) or not isinstance(error.get("message"), str)):
                    raise HarnessError("Native App Server returned an invalid error envelope")
        return value

    def _send(self, value, *, deadline=None):
        text = json.dumps(value, ensure_ascii=False)
        try:
            # Serialization is part of the same budget, never a fresh timeout.
            own_deadline = getattr(self, "_deadline", None)
            if own_deadline is not None:
                deadline = own_deadline if deadline is None else min(deadline, own_deadline)
            deadline = _earliest_deadline(deadline)
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError
            timeout = 30 if deadline is None else max(0, deadline - time.monotonic())
            if "id" in value and "method" in value:
                with self._rpc.lock:
                    method = value["method"]
                    self._rpc.calls_by_method[method] = self._rpc.calls_by_method.get(method, 0) + 1
            self.transport.send(text, timeout=timeout)
        except TimeoutError:
            raise HarnessError("Native App Server send timed out; outcome uncertain") from None
        except OSError:
            raise HarnessError("Native App Server send failed; outcome uncertain") from None

    def call(self, method, params, timeout=30):
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout < 0:
            raise HarnessError("Native RPC timeout must be finite and nonnegative")
        timeout = remaining_timeout(timeout, deadline=getattr(self, "_deadline", None))
        deadline = time.monotonic() + timeout
        sequence, waiter = self._rpc.register(method)
        self.sequence = self._rpc.sequence
        try:
            try:
                self._send({"id": sequence, "method": method, "params": params}, deadline=deadline)
            except HarnessError as exc:
                self._rpc.end(str(exc), failed=True)
                self._close_transport(deadline)
                try:
                    reply = waiter.get_nowait()
                except queue.Empty:
                    raise exc
                if isinstance(reply, HarnessError):
                    raise exc
            else:
                try:
                    reply = waiter.get(timeout=max(0, deadline - time.monotonic()))
                except queue.Empty:
                    # A timed-out read or mutation keeps its uncertain-delivery
                    # contract; callers can also distinguish an outer expiry.
                    remaining_timeout(deadline=getattr(self, "_deadline", None))
                    raise HarnessError(f"{method}: outcome uncertain; reconcile before another mutation") from None
            if isinstance(reply, HarnessError):
                raise HarnessError(f"{method}: {reply}; outcome uncertain") from None
            if "error" in reply:
                raise NativeError(method, reply["error"])
            return reply["result"]
        finally:
            with self._rpc.lock:
                self._rpc.pending.pop(sequence, None)

    def drain_events(self):
        """Return buffered native notifications in order, without waiting.

        A protocol/overflow error is raised once before draining the preserved
        buffer. It remains visible in diagnostics after that first report.
        """
        return self._rpc.drain()

    def wait_events(self, timeout=30):
        """Bounded I/O wait on this connection's notifications, without model requests."""
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout < 0:
            raise HarnessError("Native event wait timeout must be finite and nonnegative")
        return self._rpc.wait(remaining_timeout(timeout, deadline=getattr(self, "_deadline", None)))

    def diagnostics(self):
        """Connection information including a PRIVATE bounded stderr tail."""
        with self._rpc.lock:
            value = {"backend": self.backend, "state": self._rpc.state,
                     "error": self._rpc.error, "event_error": self._rpc.event_error,
                     "pending_calls": len(self._rpc.pending), "buffered_events": len(self._rpc.events),
                     "buffered_event_bytes": self._rpc.event_bytes,
                     "unsupported_methods": list(self._rpc.unsupported), "unmatched_responses": self._rpc.unmatched_responses}
            value["rpc_by_method"] = dict(self._rpc.calls_by_method)
            value["rpc_by_method_complete"] = True
        value["stderr_tail"], value["stderr_truncated"] = self.transport.stderr_tail() if self.process is not None else ("", False)
        return value

    def pages(self, method, params, *, timeout=30):
        # A page boundary must not renew this query's timeout.
        deadline = time.monotonic() + remaining_timeout(timeout, deadline=getattr(self, "_deadline", None))
        seen = set()
        while True:
            page = self.call(method, params, timeout=remaining_timeout(timeout, deadline=deadline))
            _history_page(page, method)
            yield from page["data"]
            cursor = page.get("nextCursor")
            if not cursor:
                return
            if cursor in seen:
                raise HarnessError("Repeated Codex pagination cursor; discovery is incomplete")
            seen.add(cursor)
            params = {**params, "cursor": cursor}

    def _close_transport(self, deadline=None):
        if getattr(self.transport, "supports_close_deadline", False) is True:
            self.transport.close(deadline=deadline)
        else:
            # Preserve the established injected transport/factory interface.
            self.transport.close()

    def close(self):
        with self._close_lock:
            if self.closing:
                return
            self.closing = True
        self._rpc.end("Native App Server client connection closed")
        try:
            self._close_transport(getattr(self, "_deadline", None))
        finally:
            if self.reader is not threading.current_thread():
                self.reader.join(timeout=_cleanup_timeout(0.5, getattr(self, "_deadline", None)))

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        try:
            self.close()
        except Exception as cleanup:
            if error is None:
                raise
            error.add_note(f"Native connection cleanup failed: {type(cleanup).__name__}")


@contextmanager
def command_scope(root, *, channel=None):
    """Opt a project command into its existing transient connection owner.

    Explicit channels retain creation originators. Injected factories and bare
    AppServer clients keep their existing transport and ownership contracts.
    """
    if channel is not None:
        require_text(channel, "Native shared connection channel")
    token = _command_context.set((str(Path(root).resolve()), channel))
    try:
        yield
    finally:
        _command_context.reset(token)


def command_server(originator):
    """Command connections suppress unused deltas; general clients retain all events."""
    scope = _command_context.get()
    if scope is not None:
        if (scope[1] or originator).startswith("oasis_desktop_"):
            from .desktop_sessions import DesktopServer
            return DesktopServer(originator)
        if desktop_selected(scope[0]):
            # General mode/discovery RPCs retain their full App Server contract;
            # the Desktop observer implements only task operations.
            return AppServer(originator, notification_profile="command")
        from . import shared_runtime
        return shared_runtime.connect(scope[0], scope[1] or originator)
    return AppServer(originator, notification_profile="command")


def desktop_selected(root=None):
    """Keep an accepted Desktop assignment on its actual owning application."""
    if os.environ.get("OASIS_SESSION_BACKEND") == "desktop":
        return True
    if root is None:
        return False
    path = contained(root, ".oasis/local/tasks/state.json")
    if not path.exists():
        return False
    value = read_json(path)
    return any(row.get("native_backend") == "desktop" and not row.get("archived")
               for row in value.get("tasks", []) if isinstance(row, dict))


def observer_server(originator):
    if desktop_selected() or originator.startswith("oasis_desktop_"):
        from .desktop_sessions import DesktopServer
        return DesktopServer(originator)
    return AppServer(originator, notification_profile="command")


def latest_settings(path):
    settings = None
    found = False
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            remaining_timeout()
            record = json.loads(line)
            if not isinstance(record, dict):
                raise HarnessError("Native rollout record must be an object")
            payload = record.get("payload", {})
            if record.get("type") == "turn_context":
                found = True
                settings = payload
            elif record.get("type") == "event_msg":
                if not isinstance(payload, dict):
                    raise HarnessError("Native event payload must be an object")
                if payload.get("type") == "thread_settings_applied":
                    found = True
                    settings = payload.get("thread_settings")
    if not found:
        raise MissingSavedSettings("Caller has no saved settings; cannot infer permissions")
    if not isinstance(settings, dict) or not settings:
        raise HarnessError("Saved native settings must be a nonempty object")
    return settings


def inherited_settings(settings):
    if not isinstance(settings, dict):
        raise HarnessError("Saved native settings must be an object")
    for field in ("active_permission_profile", "sandbox_policy", "permission_profile"):
        if settings.get(field) is not None and not isinstance(settings[field], dict):
            raise HarnessError(f"Saved {field} must be an object")
    for field in ("reasoning_effort", "effort", "model"):
        if settings.get(field) is not None and (not isinstance(settings[field], str) or not settings[field].strip()):
            raise HarnessError(f"Saved {field} must be nonempty text")
    efforts = {settings[key] for key in ("reasoning_effort", "effort") if settings.get(key) is not None}
    if len(efforts) > 1:
        raise HarnessError("Saved reasoning fields disagree; inspect actual caller settings")
    reasoning = next(iter(efforts), None)
    profile = (settings.get("active_permission_profile") or {}).get("id")
    sandbox = settings.get("sandbox_policy") or {}
    if profile is not None and (not isinstance(profile, str) or not profile.strip()):
        raise HarnessError("Saved permission profile ID must be nonempty text")
    for field in ("network_access", "exclude_tmpdir_env_var", "exclude_slash_tmp"):
        if field in sandbox and not isinstance(sandbox[field], bool):
            raise HarnessError(f"Saved sandbox {field} must be a boolean")
    if "writable_roots" in sandbox and (not isinstance(sandbox["writable_roots"], list)
            or any(not isinstance(root, str) or not root for root in sandbox["writable_roots"])):
        raise HarnessError("Saved writable roots must be text paths")
    # Current saved settings can omit the legacy sandbox_policy. Accept only
    # the observed exact disabled representation with matching built-in
    # provenance; never infer broad access from a missing or custom policy.
    if settings.get("permission_profile") is not None:
        if settings["permission_profile"] != {"type": "disabled"} or profile != ":danger-full-access":
            raise HarnessError("Unsupported current permission representation; preserve it before creation")
        if sandbox and sandbox.get("type") != "danger-full-access":
            raise HarnessError("Saved permission representations disagree; no session is created")
        sandbox = {"type": "danger-full-access"}
    policy_type = sandbox.get("type")
    known = {"danger-full-access": (":danger-full-access", "dangerFullAccess"),
             "workspace-write": (":workspace", "workspaceWrite"), "read-only": (":read-only", "readOnly")}
    if not isinstance(policy_type, str) or policy_type not in known:
        raise HarnessError("Unsupported effective caller permission policy; preserve it and use a verified adapter")
    if profile in {row[0] for row in known.values()} and profile != known[policy_type][0]:
        raise HarnessError("Saved built-in profile disagrees with effective policy")
    if not profile:
        if policy_type != "danger-full-access":
            raise HarnessError("Restricted caller needs an explicit saved named profile")
        profile = known[policy_type][0]
    approval = settings.get("approval_policy")
    if not ((isinstance(approval, str) and approval in ("never", "untrusted", "on-request")) or
            (isinstance(approval, dict) and set(approval) == {"granular"} and isinstance(approval["granular"], dict) and all(isinstance(v, bool) for v in approval["granular"].values()))):
        raise HarnessError("Unsupported saved approval policy")
    reviewer = settings.get("approvals_reviewer")
    if reviewer not in ("user", "auto_review", "guardian_subagent"):
        raise HarnessError("Saved approval reviewer is unavailable or unsupported")
    # Restricted named profiles must be compared in full; no promotion to full access.
    effective = {"type": known[policy_type][1]}
    for snake, camel in (("writable_roots", "writableRoots"), ("network_access", "networkAccess"),
                         ("exclude_tmpdir_env_var", "excludeTmpdirEnvVar"), ("exclude_slash_tmp", "excludeSlashTmp")):
        if snake in sandbox:
            effective[camel] = sandbox[snake]
    return {"permissions": profile, "approvalPolicy": approval, "approvalsReviewer": reviewer,
            "effective_sandbox": effective, "model": settings.get("model"),
            "reasoning": reasoning}


def project_id(server, target):
    matches = [row["id"] for row in server.pages("project/list", {})
               if any(canonical_root(root["path"]) == canonical_root(target) for root in row.get("roots", []))]
    if len(matches) != 1:
        raise HarnessError("Target must match exactly one registered Codex project. Open/register this folder in Codex, then inspect again")
    return matches[0]


def prepare(server, source_id, target):
    require_text(source_id, "Source thread ID")
    source = server.call("thread/read", {"threadId": source_id, "includeTurns": False})["thread"]
    settings, _ = _actual_settings(server, source_id, thread=source)
    identity = project_id(server, target)
    profiles = list(server.pages("permissionProfile/list", {"cwd": str(target)}))
    if not any(row.get("id") == settings["permissions"] and row.get("allowed") for row in profiles):
        raise HarnessError("Target requirements do not allow the caller's profile; no substitute profile is selected")
    return identity, settings, source


def discover(server, target, identity):
    found = {}
    for assigned in (identity, None):
        for row in server.pages("thread/list", {"projectId": assigned, "archived": False, "sourceKinds": SOURCES, "limit": 100}):
            if canonical_root(row["cwd"]) == canonical_root(target):
                found[row["id"]] = row
    return list(found.values())


def letters(index):
    result = ""
    while index:
        index, part = divmod(index - 1, 26)
        result = chr(65 + part) + result
    return result


def require_text(value, label):
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise HarnessError(f"{label} must be nonempty text")
    return value


def retired_role():
    return {"status": "retired_role", "role": "Calf", "replacement": "Camel",
            "message": "Calf was retired in core 2.0.0. Assign implementation and checks to Camel; existing Calf records remain readable.",
            "thread_created": False}


def title_for(role, goal, source=None, threads=(), receipts=(), *, pioneer_id=None):
    """Choose a readable convention; role and parent links use actual IDs."""
    if role == "Calf":
        return None
    if role not in ROLES:
        raise HarnessError("Unknown session role")
    if role in ("Oasis", "Cameleer", "Pioneer"):
        return role
    require_text(goal, "Task goal")
    label = " ".join(goal.split())
    if role == "Developer":
        return f"Developer_{label}"
    occupied = {row.get("name") for row in threads} | {row.get("title") for row in receipts}
    index = 1
    while f"camel_{letters(index)}_{label}" in occupied:
        index += 1
    return f"camel_{letters(index)}_{label}"


def verify_response(response, receipt):
    """Check the creation result once so permission inheritance is not widened."""
    expected = receipt["settings"]
    if (not isinstance(response, dict) or not isinstance(response.get("thread"), dict)
            or not isinstance(response.get("cwd"), str)
            or response.get("activePermissionProfile") is not None and not isinstance(response["activePermissionProfile"], dict)):
        raise HarnessError("Created native settings response has invalid consumed fields")
    if (response.get("activePermissionProfile") or {}).get("id") != expected["permissions"]:
        raise HarnessError("Created permission profile differs from the caller")
    for key in ("approvalPolicy", "approvalsReviewer"):
        if response.get(key) != expected[key]:
            raise HarnessError(f"Created {key} differs from the caller")
    if response.get("sandbox") != expected["effective_sandbox"]:
        raise HarnessError("Created effective sandbox differs from the caller")
    if canonical_root(response["cwd"]) != canonical_root(receipt["target"]) or response["thread"].get("projectId") != receipt["project_id"]:
        raise HarnessError("Created project/root mismatch")
    if expected.get("model") and response.get("model") != expected["model"]:
        raise HarnessError("Model selection was not preserved")
    if expected.get("reasoning") and response.get("reasoningEffort") != expected["reasoning"]:
        raise HarnessError("Reasoning selection was not preserved")


def create_metadata(path, receipt, factory=command_server):
    if not isinstance(receipt, dict) or not isinstance(receipt.get("settings"), dict):
        raise HarnessError("Native creation receipt/settings must be objects")
    if receipt.get("role") == "Calf":
        return retired_role()
    if receipt.get("phase") == "ready" and receipt.get("thread_id"):
        return receipt
    settings = receipt["settings"]
    options = {"cwd": receipt["target"], "projectId": receipt["project_id"],
               **{key: settings[key] for key in ("permissions", "approvalPolicy", "approvalsReviewer")}}
    if settings.get("model"):
        options["model"] = settings["model"]
    if settings.get("reasoning"):
        options["config"] = {"model_reasoning_effort": settings["reasoning"]}
    if not receipt.get("thread_id") and receipt["phase"] not in CREATION_RETRYABLE:
        raise HarnessError("Creation response is uncertain; inspect this receipt instead of creating another chat")
    try:
        with command_scope(receipt["target"], channel=receipt["originator"]), factory(receipt["originator"]) as server:
            if not receipt.get("thread_id"):
                receipt["phase"] = "creation_started"
                write_json(path, receipt)
                try:
                    response = server.call("thread/start", options)
                except NativeError as exc:
                    if exc.code in (-32601, -32602, -32001):
                        receipt["phase"] = "creation_rejected"
                        write_json(path, receipt)
                    raise
                if not isinstance(response, dict) or not isinstance(response.get("thread"), dict):
                    raise HarnessError("Creation returned an invalid native thread response; preserve uncertainty")
                require_text(response["thread"].get("id"), "Created native thread ID")
                receipt.update(thread_id=response["thread"]["id"], phase="created", creation_verified=False)
                write_json(path, receipt)
                verify_response(response, receipt)
                receipt["creation_verified"] = True
                write_json(path, receipt)
            else:
                # Native read verifies identity without repeated cold resumes or
                # resetting a user's later model/permission selection.
                thread = server.call("thread/read", {"threadId": receipt["thread_id"], "includeTurns": False})["thread"]
                if canonical_root(thread["cwd"]) != canonical_root(receipt["target"]) or thread.get("projectId") != receipt["project_id"]:
                    raise HarnessError("Reconciled thread belongs to another project/root")
                if not receipt.get("creation_verified"):
                    # Only unresolved creation needs this check. A failed
                    # inheritance response must not become a ready wider chat.
                    resume_options = {key: value for key, value in options.items() if key not in ("cwd", "projectId")}
                    response = server.call("thread/resume", {"threadId": receipt["thread_id"], "excludeTurns": True, **resume_options})
                    verify_response(response, receipt)
                    receipt["creation_verified"] = True
                    write_json(path, receipt)
            server.call("thread/name/set", {"threadId": receipt["thread_id"], "name": receipt["title"]})
        receipt.update(phase="ready", handoff_delivered=False)
        receipt.pop("error", None)
        write_json(path, receipt)
        return receipt
    except Exception as exc:
        receipt["error"] = str(exc)
        write_json(path, receipt)
        raise


def inspect(path, factory=command_server):
    receipt = read_json(path)
    with command_scope(receipt["target"], channel=receipt["originator"]), factory(receipt["originator"] + "_inspect") as server:
        if receipt.get("thread_id"):
            identity = receipt["thread_id"]
        else:
            rows = discover(server, receipt["target"], receipt["project_id"])
            identities = {row["id"] for row in rows if row.get("originator") == receipt["originator"]}
            if len(identities) != 1:
                return {"phase": "uncertain", "matches": sorted(identities), "retry_allowed": False}
            identity = next(iter(identities))
        thread = server.call("thread/read", {"threadId": identity, "includeTurns": False})["thread"]
        if canonical_root(thread["cwd"]) != canonical_root(receipt["target"]) or thread.get("projectId") != receipt["project_id"]:
            raise HarnessError("Reconciled thread belongs to another project/root")
        return {"phase": receipt["phase"], "thread_id": identity, "name": thread.get("name"),
                "target": thread.get("cwd"), "receipt": str(path)}


def resume(path, authority=None, factory=command_server):
    receipt = read_json(path)
    with operation_lock(contained(receipt["target"], ".oasis/local/operations.lock")):
        if receipt.get("phase") == "creation_rejected" and not receipt.get("thread_id"):
            return create_metadata(path, receipt, factory)
        result = inspect(path, factory)
        if not result.get("thread_id"):
            raise HarnessError("Creation identity is unresolved; preserve the receipt without retrying creation")
        receipt["thread_id"] = result["thread_id"]
        write_json(path, receipt)
        if receipt.get("role") == "Calf":
            return {**receipt, "legacy_role": True}
        return create_metadata(path, receipt, factory)


def create(target, role, source_id, goal=None, *, title=None, apply=False, factory=command_server, **_legacy):
    if role == "Calf":
        return retired_role()
    if role not in ROLES:
        raise HarnessError("Unknown session role")
    require_text(source_id, "Source thread ID")
    from .installation import target_root
    target = target_root(target)
    originator = "oasis_session_" + uuid.uuid4().hex
    with command_scope(target, channel=originator), factory(originator) as server:
        identity, settings, source = prepare(server, source_id, target)
        selected_title = title if title is not None else title_for(role, goal, source, discover(server, target, identity))
    require_text(selected_title, "Chat title")
    receipt = {"schema_version": 1, "originator": originator, "source_thread_id": source_id,
               "target": str(target), "project_id": identity, "settings": settings, "title": selected_title,
               "role": role, "parent_thread_id": source_id if role in ("Camel", "Developer") else None,
               "phase": "prepared"}
    if not apply:
        return receipt
    with operation_lock(contained(target, ".oasis/local/operations.lock")):
        path = contained(target, f".oasis/local/sessions/{originator}/receipt.json")
        write_json(path, receipt)
        return {**create_metadata(path, receipt, factory), "receipt": str(path)}


def _history_page(page, method):
    if not isinstance(page, dict) or not isinstance(page.get("data"), list):
        raise HarnessError(f"{method}: invalid native page")
    for key in ("nextCursor", "backwardsCursor"):
        if page.get(key) is not None and (not isinstance(page[key], str) or not page[key]):
            raise HarnessError(f"{method}: invalid native cursor")
    if any(not isinstance(row, dict) for row in page["data"]):
        raise HarnessError(f"{method}: native page entries must be objects")
    return page


def _history_pages(server, method, params):
    seen = set()
    while True:
        page = _history_page(server.call(method, params), method)
        yield page
        cursor = page.get("nextCursor")
        if not cursor:
            return
        if cursor in seen:
            raise HarnessError("Repeated Codex pagination cursor; history is incomplete")
        seen.add(cursor)
        params = {**params, "cursor": cursor}


def _full_turns(server, thread_id):
    thread = server.call("thread/read", {"threadId": thread_id, "includeTurns": True})["thread"]
    check_thread_binding(thread, thread_id)
    turns = thread.get("turns")
    if isinstance(turns, list) and thread.get("turnsView", "full") == "full":
        return turns
    return list(server.pages("thread/turns/list", {"threadId": thread_id, "itemsView": "full", "limit": 100}))


def read_turns(server, thread_id):
    """A requested reconciliation read; return the existing list facade."""
    try:
        return [turn for page in _history_pages(server, "thread/turns/list", {
            "threadId": thread_id, "itemsView": "full", "sortDirection": "asc", "limit": 100}) for turn in page["data"]]
    except NativeError as exc:
        if exc.code != -32601:
            raise
        return _full_turns(server, thread_id)


def check_thread_binding(thread, thread_id, binding=None):
    if not isinstance(thread, dict) or thread.get("id") != thread_id:
        raise HarnessError("Native read returned another thread ID")
    if binding is not None:
        if (not isinstance(binding, dict) or not isinstance(binding.get("target"), str)
                or not isinstance(binding.get("project_id"), str)):
            raise HarnessError("Expected native binding requires target and project ID")
        if (not isinstance(thread.get("cwd"), str)
                or canonical_root(thread["cwd"]) != canonical_root(binding["target"])
                or thread.get("projectId") != binding["project_id"]):
            raise HarnessError("Native thread belongs to another project/root")


def _legacy_baseline(server, value):
    before = read_turns(server, value["thread_id"])
    value["before_turn_ids"] = [turn.get("id") for turn in before]
    value["before_user_item_ids"] = [item["id"] for turn in before for item in turn.get("items", [])
                                      if item.get("type") == "userMessage" and item.get("id")]


def _capture_anchor(server, value):
    try:
        page = _history_page(server.call("thread/turns/list", {"threadId": value["thread_id"],
            "itemsView": "notLoaded", "sortDirection": "desc", "limit": 1}), "thread/turns/list")
        if not page["data"]:
            value["history_anchor"] = {"empty": True}
            return
        if not page.get("backwardsCursor"):
            _legacy_baseline(server, value)
            return
        turn_id = require_text(page["data"][0].get("id"), "Native history turn ID")
        items = _history_page(server.call("thread/items/list", {"threadId": value["thread_id"],
            "turnId": turn_id, "sortDirection": "desc", "limit": 1}), "thread/items/list")
        last = None
        if items["data"]:
            entry = items["data"][0]
            if entry.get("turnId") != turn_id or not isinstance(entry.get("item"), dict):
                raise HarnessError("Native history item belongs to another turn")
            last = entry["item"]
        value["history_anchor"] = {"turn_id": turn_id, "backwards_cursor": page["backwardsCursor"],
                                   "last_item_id": require_text(last.get("id"), "Native history item ID") if last else None}
    except NativeError as exc:
        if exc.code != -32601:
            raise
        _legacy_baseline(server, value)


def _anchored_items(server, value):
    anchor = value["history_anchor"]
    params = {"threadId": value["thread_id"], "itemsView": "notLoaded", "sortDirection": "asc", "limit": 100}
    if not anchor.get("empty"):
        params["cursor"] = anchor["backwards_cursor"]
    for page in _history_pages(server, "thread/turns/list", params):
        for turn in page["data"]:
            identity = require_text(turn.get("id"), "Native history turn ID")
            item_params = {"threadId": value["thread_id"], "turnId": identity, "sortDirection": "asc", "limit": 100}
            boundary = anchor.get("last_item_id") if identity == anchor.get("turn_id") else None
            if boundary:
                item_params["cursor"] = {"type": "item", "itemId": boundary}
            for items in _history_pages(server, "thread/items/list", item_params):
                for entry in items["data"]:
                    if entry.get("turnId") != identity or not isinstance(entry.get("item"), dict):
                        raise HarnessError("Native history item belongs to another turn")
                    yield turn, entry["item"], True


def _anchored_turn_items(server, value):
    anchor = value["history_anchor"]
    params = {"threadId": value["thread_id"], "itemsView": "full", "sortDirection": "asc", "limit": 100}
    if not anchor.get("empty"):
        params["cursor"] = anchor["backwards_cursor"]
    for page in _history_pages(server, "thread/turns/list", params):
        for turn in page["data"]:
            if not isinstance(turn.get("items"), list):
                raise HarnessError("Native history turn items are unavailable")
            boundary = anchor.get("last_item_id") if turn.get("id") == anchor.get("turn_id") else None
            allowed = boundary is None
            for item in turn["items"]:
                if not isinstance(item, dict):
                    raise HarnessError("Native history item must be an object")
                if allowed:
                    yield turn, item, True
                elif item.get("id") == boundary:
                    allowed = True
            if not allowed:
                raise HarnessError("Native history item anchor is unavailable; preserve uncertainty")


def _delivery_items(server, value):
    for turn in read_turns(server, value["thread_id"]):
        for item in turn.get("items", []):
            allowed = (item.get("id") not in value.get("before_user_item_ids", [])
                       if item.get("id") else turn.get("id") not in value.get("before_turn_ids", []))
            yield turn, item, allowed


def _message_text(item):
    return "\n".join(part.get("text", "") for part in item.get("content", []) if part.get("type") == "text")


def _delivery_matches(items, value):
    matches, first = 0, None
    for turn, item, allowed in items:
        if value.get("desktop_source_id") is not None and item.get("sourceThreadId") != value["desktop_source_id"]:
            continue
        if item.get("type") == "userMessage" and (item.get("clientId") == value["message_id"] or (
                not item.get("clientId") and allowed and _message_text(item) == value["text"])):
            matches += 1
            first = first or turn.get("id")
    return matches, first


def reconcile_delivery(server, value):
    if "history_anchor" in value:
        anchor = value["history_anchor"]
        if (not isinstance(anchor, dict) or (anchor.get("empty") is not True and
                (not isinstance(anchor.get("turn_id"), str) or not isinstance(anchor.get("backwards_cursor"), str)
                 or (anchor.get("last_item_id") is not None and not isinstance(anchor["last_item_id"], str))))):
            raise HarnessError("Invalid retained history anchor; preserve delivery")
        try:
            matches, first = _delivery_matches(_anchored_items(server, value), value)
        except NativeError as exc:
            if exc.code != -32601:
                raise
            try:
                matches, first = _delivery_matches(_anchored_turn_items(server, value), value)
            except NativeError as fallback:
                if fallback.code != -32601:
                    raise
                # Full read cannot prove a text-only boundary from a small receipt.
                matches, first = _delivery_matches(((turn, item, False)
                    for turn in _full_turns(server, value["thread_id"]) for item in turn.get("items", [])), value)
    else:
        matches, first = _delivery_matches(_delivery_items(server, value), value)
    if matches:
        value.update(state="accepted", turn_id=first, duplicate_observed=matches > 1)
        value.pop("error", None)
        return True
    return False


def _collaboration(settings, mode):
    model = settings.get("model")
    if not isinstance(model, str) or not model:
        raise HarnessError("The native collaboration mode needs the existing thread's model")
    return {"mode": mode, "settings": {"model": model, "reasoning_effort": settings.get("reasoning"),
                                       "developer_instructions": None}}


def _verified_initial_settings(thread, thread_id):
    """Use exact creation evidence only before the first settings record exists."""
    root = Path(thread["cwd"]).resolve()
    matches = []
    for path in contained(root, ".oasis/local/sessions").glob("*/receipt.json"):
        row = read_json(contained(root, path.relative_to(root).as_posix()))
        if (not isinstance(row, dict) or row.get("thread_id") != thread_id
                or row.get("creation_verified") is not True):
            continue
        if canonical_root(row.get("target", "")) != canonical_root(root) or row.get("project_id") != thread.get("projectId"):
            raise HarnessError("Initial settings record has a different native project/root")
        if not isinstance(row.get("settings"), dict):
            raise HarnessError("Verified initial settings record is invalid")
        matches.append(row["settings"])
    if not matches:
        raise MissingSavedSettings("Native thread has no saved settings or matching verified creation record")
    if any(settings != matches[0] for settings in matches[1:]):
        raise HarnessError("Conflicting initial settings records for this native thread")
    settings = matches[0]
    sandbox = settings.get("effective_sandbox")
    kinds = {"dangerFullAccess": "danger-full-access", "workspaceWrite": "workspace-write", "readOnly": "read-only"}
    fields = {"writableRoots": "writable_roots", "networkAccess": "network_access",
              "excludeTmpdirEnvVar": "exclude_tmpdir_env_var", "excludeSlashTmp": "exclude_slash_tmp"}
    if not isinstance(sandbox, dict) or sandbox.get("type") not in kinds or set(sandbox) - {"type", *fields}:
        raise HarnessError("Verified initial sandbox representation is unsupported")
    saved = {"active_permission_profile": {"id": settings.get("permissions")},
             "sandbox_policy": {"type": kinds[sandbox["type"]],
                                **{fields[key]: value for key, value in sandbox.items() if key in fields}},
             "approval_policy": settings.get("approvalPolicy"), "approvals_reviewer": settings.get("approvalsReviewer"),
             "model": settings.get("model"), "reasoning_effort": settings.get("reasoning")}
    return inherited_settings(saved), saved


def _actual_settings(server, thread_id, *, thread=None):
    thread = thread if thread is not None else server.call("thread/read", {"threadId": thread_id, "includeTurns": False})["thread"]
    if thread.get("id") != thread_id:
        raise HarnessError("Native settings lookup returned another thread ID")
    require_text(thread.get("path"), "Native saved settings path")
    try:
        saved = latest_settings(thread["path"])
    except MissingSavedSettings:
        return _verified_initial_settings(thread, thread_id)
    return inherited_settings(saved), saved


def _resume_current(server, thread, settings):
    """Load only a cold recipient with its current selections, then verify once.

    On the observed native host a no-override resume resets model effort and
    approval/profile fields to server defaults. Explicit identical selections
    preserve this thread's configuration without writing global settings.
    """
    require_text(settings.get("model"), "Current native model")
    options = {key: settings[key] for key in ("permissions", "approvalPolicy", "approvalsReviewer", "model")}
    if settings.get("reasoning") is not None:
        options["config"] = {"model_reasoning_effort": settings["reasoning"]}
    response = server.call("thread/resume", {"threadId": thread["id"], "excludeTurns": True, **options})
    verify_response(response, {"settings": settings, "target": thread["cwd"], "project_id": thread.get("projectId")})
    if response.get("reasoningEffort") != settings.get("reasoning"):
        raise HarnessError("Cold resume did not preserve the current reasoning selection")


def _plan_route(server, thread_id, settings):
    try:
        modes = server.call("collaborationMode/list", {})["data"]
    except NativeError as exc:
        if exc.code == -32601:
            return "manual", None
        raise
    if not any(row.get("mode") == "plan" for row in modes):
        return "manual", None
    mode = _collaboration(settings, "plan")
    try:
        server.call("thread/settings/update", {"threadId": thread_id, "collaborationMode": mode})
        return "settings", mode
    except NativeError as exc:
        if exc.code == -32601:
            return "turn", mode
        raise


def send_once(path, thread_id, text, server, *, planning=False, execution=False, skill=None, expected_binding=None):
    """Send one native user message and retain an ambiguous attempt for recovery.

    A client ID identifies this delivery; it imposes no format on role messages.
    Definite native rejection is retryable. Lost responses never replay a turn.
    """
    require_text(thread_id, "Recipient thread ID")
    require_text(text, "Message")
    if not isinstance(planning, bool) or not isinstance(execution, bool) or planning and execution:
        raise HarnessError("Choose either planning or implementation delivery")
    path = Path(path)
    value = read_json(path) if path.exists() else {
        "schema_version": 1, "thread_id": thread_id, "text": text, "message_id": str(uuid.uuid4()),
        "planning": planning, "execution": execution, "state": "not_started"}
    if not isinstance(value, dict) or value.get("state") not in ("not_started", "started", "uncertain", "accepted", "rejected", "manual_plan", "manual_mode"):
        raise HarnessError("Invalid delivery record; preserve it for recovery")
    if value.get("thread_id") != thread_id or value.get("text") != text:
        raise HarnessError("Delivery path already belongs to another message; preserve it and use its existing action")
    if any(value.get(key, False) != choice for key, choice in (("planning", planning), ("execution", execution))):
        raise HarnessError("Delivery path has different mode inputs; preserve its existing action")
    if value.get("expected_binding") is not None:
        if expected_binding is not None and value["expected_binding"] != expected_binding:
            raise HarnessError("Delivery belongs to another project binding")
        expected_binding = value["expected_binding"]
    if value["state"] == "accepted":
        return value
    native = server.call("thread/read", {"threadId": thread_id, "includeTurns": False})["thread"]
    check_thread_binding(native, thread_id, expected_binding)
    if native.get("status") is not None and (not isinstance(native["status"], dict)
            or not isinstance(native["status"].get("type"), str)):
        raise HarnessError("Native thread status must contain type text")
    if expected_binding is not None:
        value["expected_binding"] = expected_binding
    if getattr(server, "desktop_managed", False):
        source_id = require_text(server.source_id, "Desktop delivery source chat ID")
        if (value.get("desktop_source_id") not in (None, source_id)
                and value["state"] not in ("started", "uncertain")):
            raise HarnessError("Desktop delivery belongs to another source chat")
        value.setdefault("desktop_source_id", source_id)
    if value["state"] in ("started", "uncertain"):
        reconcile_delivery(server, value)
        write_json(path, value)
        return value
    settings = saved = None
    collaboration = None
    if (native.get("status") or {}).get("type") == "notLoaded" and not getattr(server, "desktop_managed", False):
        settings, saved = _actual_settings(server, thread_id, thread=native)
        _resume_current(server, native, settings)
    if planning or execution:
        if settings is None:
            settings, saved = _actual_settings(server, thread_id, thread=native)
    if planning:
        actual_mode = (saved.get("collaboration_mode") or {}).get("mode")
        route, collaboration = ("manual_already_set", None) if actual_mode == "plan" else _plan_route(server, thread_id, settings)
        value["plan_route"] = route
        if route == "manual":
            value["state"] = "manual_plan"
            if not value.get("manual_instruction_shown"):
                value["manual_instruction_shown"] = True
                write_json(path, value)
                return {**value, "instruction": f"Enable actual Codex Plan mode in chat {thread_id}, then start planning with the assigned request."}
            write_json(path, value)
            return value
    elif execution:
        # Only an explicit implementation follow-up requests this mode change.
        if getattr(server, "desktop_managed", False):
            if (saved.get("collaboration_mode") or {}).get("mode") != "default":
                value["state"] = "manual_mode"
                if not value.get("manual_instruction_shown"):
                    value["manual_instruction_shown"] = True
                    write_json(path, value)
                    return {**value, "instruction": f"Switch chat {thread_id} to actual default mode, then resume this retained implementation request."}
                write_json(path, value)
                return value
        else:
            collaboration = _collaboration(settings, "default")
    if "before_turn_ids" not in value and "history_anchor" not in value:
        _capture_anchor(server, value)
    params = {"threadId": thread_id, "input": [{"type": "text", "text": text}],
              "clientUserMessageId": value["message_id"]}
    if skill and not getattr(server, "desktop_managed", False):
        params["input"].append({"type": "skill", "name": skill["name"], "path": skill["path"]})
    if collaboration is not None:
        params["collaborationMode"] = collaboration
    value["state"] = "started"
    write_json(path, value)
    try:
        result = server.call("turn/start", params)
        value.update(state="accepted", turn_id=result["turn"]["id"])
        value.pop("error", None)
    except NativeError as exc:
        if planning and exc.code == -32602 and "collaboration" in str(exc).casefold():
            value.update(state="manual_plan", plan_route="manual", error=str(exc))
            if not value.get("manual_instruction_shown"):
                value["manual_instruction_shown"] = True
                write_json(path, value)
                return {**value, "instruction": f"Enable actual Codex Plan mode in chat {thread_id}, then start planning with the assigned request."}
        else:
            value.update(state="rejected", error=str(exc))
            write_json(path, value)
            raise
    except Exception as exc:
        value.update(state="uncertain", error=str(exc))
        write_json(path, value)
        raise
    write_json(path, value)
    return value


def archive(server, thread_id):
    require_text(thread_id, "Thread ID")
    return server.call("thread/archive", {"threadId": thread_id})


def restore(server, thread_id):
    require_text(thread_id, "Thread ID")
    return server.call("thread/unarchive", {"threadId": thread_id})


def workflow_pioneer(target, source_id, server=None):
    from .workflows import bound_pioneer
    return bound_pioneer(target, source_id, server)


def register(subparsers):
    parser = subparsers.add_parser("session", help="Native chats, assignment and retained delivery recovery")
    commands = parser.add_subparsers(dest="session_command", required=True)
    p = commands.add_parser("inspect")
    p.add_argument("receipt")
    p.set_defaults(func=lambda args: inspect(args.receipt))
    p = commands.add_parser("resume")
    p.add_argument("receipt")
    p.add_argument("--authority", help="Legacy request reference", default=None)
    p.set_defaults(func=lambda args: resume(args.receipt, args.authority))
    p = commands.add_parser("discovery")
    p.add_argument("--target", required=True)
    def discovery(args):
        with command_server("oasis_discovery") as server:
            identity = project_id(server, args.target)
            result = server.call("skills/list", {"cwds": [str(Path(args.target).resolve())], "forceReload": True})
            return {"project_id": identity, "skills": result, "adoption_verified": False}
    p.set_defaults(func=discovery)
    p = commands.add_parser("create")
    p.add_argument("--target", required=True)
    p.add_argument("--role", required=True, choices=(*ROLES, "Calf"))
    p.add_argument("--goal")
    p.add_argument("--title")
    p.add_argument("--lane", choices=("main", "test"), help="Legacy lane hint; preserves the selected Git workflow")
    p.add_argument("--source-thread-id", default=os.environ.get("CODEX_THREAD_ID"))
    p.add_argument("--authority", help="Legacy request reference")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(func=lambda args: create(args.target, args.role, args.source_thread_id, args.goal,
                                           title=args.title, apply=args.apply))
