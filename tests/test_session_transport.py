"""Real loopback RFC 6455 exchanges, without native chats or model calls."""
import base64
from contextlib import contextmanager
import hashlib
import io
import json
import os
import queue
import select
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from pathlib import Path

from oasis_harness import sessions
from oasis_harness.common import HarnessError


def exact(connection, length):
    result = bytearray()
    while len(result) < length:
        chunk = connection.recv(length - len(result))
        if not chunk:
            raise EOFError
        result.extend(chunk)
    return bytes(result)


def server_frame(payload, opcode=1, *, final=True):
    header = bytes((opcode | (0x80 if final else 0),))
    size = len(payload)
    if size < 126:
        header += bytes((size,))
    elif size < 65536:
        header += bytes((126,)) + struct.pack("!H", size)
    else:
        header += bytes((127,)) + struct.pack("!Q", size)
    return header + payload


class LoopbackServer:
    """Disposable independent server which checks client masks and RPC bytes."""
    def __init__(self, *, fragmented=False, handshake="valid", coalesced=False, invalid=None):
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.listener.settimeout(0.1)
        self.url = f"ws://127.0.0.1:{self.listener.getsockname()[1]}/native?fixture=1"
        self.fragmented = fragmented
        self.handshake = handshake
        self.coalesced = coalesced
        self.invalid = invalid
        self.stop = threading.Event()
        self.pong = threading.Event()
        self.close_received = threading.Event()
        self.connections = []
        self.handlers = []
        self.messages = []
        self.widths = []
        self.closes = []
        self.pongs = []
        self.errors = []
        self.requests = []
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()

    def _accept(self):
        while not self.stop.is_set():
            try:
                connection, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            connection.settimeout(2)
            self.connections.append(connection)
            handler = threading.Thread(target=self._connection, args=(connection,), daemon=True)
            self.handlers.append(handler)
            handler.start()

    def _connection(self, connection):
        try:
            request = bytearray()
            while not request.endswith(b"\r\n\r\n"):
                request.extend(exact(connection, 1))
            self.requests.append(bytes(request))
            fields = dict(line.split(": ", 1) for line in request.decode("ascii").split("\r\n")[1:] if line)
            key = fields["Sec-WebSocket-Key"]
            if len(base64.b64decode(key)) != 16 or fields["Sec-WebSocket-Version"] != "13":
                raise AssertionError("Invalid client upgrade key/version")
            accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()).decode("ascii")
            status = "HTTP/1.1 101 Switching Protocols"
            headers = ["Upgrade: websocket", "Connection: keep-alive, Upgrade", "Sec-WebSocket-Accept: " + accept]
            if self.handshake == "bad_accept":
                headers[-1] = "Sec-WebSocket-Accept: invalid"
            elif self.handshake == "duplicate_accept":
                headers.append(headers[-1])
            elif self.handshake == "no_upgrade":
                headers[1] = "Connection: keep-alive"
            elif self.handshake == "redirect":
                status = "HTTP/1.1 302 Redirect"
            elif self.handshake == "extension":
                headers.append("Sec-WebSocket-Extensions: permessage-deflate")
            response = (status + "\r\n" + "\r\n".join(headers) + "\r\n\r\n").encode("ascii")
            if self.coalesced:
                response += server_frame(b'{"method":"fixture/ready","params":{}}')
            connection.sendall(response)
            # The handshake has a deadline; an initialized connection remains
            # alive until peer close or this fixture's explicit shutdown. A
            # suite scheduling pause must not turn into an unrelated EOF.
            connection.settimeout(None)
            while not self.stop.is_set():
                first, second = exact(connection, 2)
                if not second & 0x80:
                    raise AssertionError("Client frame must be masked")
                opcode, tag = first & 15, second & 127
                length = tag
                if tag == 126:
                    length = struct.unpack("!H", exact(connection, 2))[0]
                elif tag == 127:
                    length = struct.unpack("!Q", exact(connection, 8))[0]
                mask = exact(connection, 4)
                encoded = exact(connection, length)
                payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(encoded))
                if opcode == 8:
                    self.closes.append(payload)
                    self.close_received.set()
                    connection.sendall(server_frame(payload, 8))
                    return
                if opcode == 10:
                    self.pongs.append(payload)
                    self.pong.set()
                    continue
                if opcode != 1 or not first & 0x80:
                    raise AssertionError("Unexpected client application frame")
                value = json.loads(payload.decode("utf-8"))
                self.messages.append(value)
                self.widths.append((value.get("method"), tag))
                if "id" not in value:
                    continue
                if value["method"] == "bad_frame":
                    connection.sendall(self.invalid)
                    continue
                if value["method"] == "remote_close":
                    connection.sendall(server_frame(struct.pack("!H", 1000) + b"done", 8))
                    continue
                if value["method"] == "disconnect":
                    return
                result = {"fixture": True} if value["method"] == "initialize" else value["params"]
                data = json.dumps({"id": value["id"], "result": result, "fixtureText": "한글"}, ensure_ascii=False).encode("utf-8")
                if self.fragmented:
                    split = data.index("한".encode("utf-8")) + 1
                    connection.sendall(server_frame(data[:split], final=False) + server_frame(b"fixture-ping", 9)
                                       + server_frame(data[split:], 0))
                else:
                    connection.sendall(server_frame(data))
        except (EOFError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception as exc:
            if not self.stop.is_set():
                self.errors.append(exc)
        finally:
            connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.listener.close()
        for connection in self.connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.thread.join(timeout=1)
        for handler in self.handlers:
            handler.join(timeout=1)


class InjectedTransport:
    """An in-memory native wire; never launches a server or a model."""
    def __init__(self):
        self.process = object()
        self.messages = queue.Queue()
        self.sent = []
        self.write_lock = threading.Lock()
        self.closed = False
        self.on_send = None
        self.initialize_messages = None
        self.private_tail = ""

    def feed(self, value):
        self.messages.put(value if value is None or isinstance(value, str) else json.dumps(value, ensure_ascii=False))

    def receive(self):
        return self.messages.get()

    def send(self, text, *, timeout=30):
        with self.write_lock:
            value = json.loads(text)
            self.sent.append(value)
            if value.get("method") == "initialize":
                for message in self.initialize_messages if self.initialize_messages is not None else [{"id": value["id"], "result": {}}]:
                    self.feed(message)
            elif self.on_send is not None:
                self.on_send(value)

    def stderr_tail(self):
        return self.private_tail, False

    def close(self):
        if not self.closed:
            self.closed = True
            self.messages.put(None)


class SessionTransportContracts(unittest.TestCase):
    @contextmanager
    def proxy_client(self, server):
        # A real child forwards bytes only, like `codex app-server proxy`.
        # The independent server rejects unmasked frames and checks the upgrade.
        bridge = '''import socket, sys, threading
peer = socket.create_connection(("127.0.0.1", int(sys.argv[1])))
def upload():
    try:
        while block := sys.stdin.buffer.read1(65536):
            peer.sendall(block)
        peer.shutdown(socket.SHUT_WR)
    except OSError:
        pass
threading.Thread(target=upload, daemon=True).start()
try:
    while block := peer.recv(65536):
        sys.stdout.buffer.write(block)
        sys.stdout.buffer.flush()
finally:
    peer.close()
'''
        original = subprocess.Popen
        with tempfile.TemporaryDirectory(prefix="oasis-proxy-") as directory:
            script = Path(directory) / "bridge.py"
            script.write_text(bridge, encoding="utf-8")
            def launch(command, **kwargs):
                self.assertEqual(command, ["fixture-codex", "app-server", "proxy", "--sock", "fixture-socket"])
                return original([sys.executable, "-B", "-X", "utf8", str(script), str(server.listener.getsockname()[1])], **kwargs)
            environment = {key: value for key, value in os.environ.items() if key not in {"OASIS_APP_SERVER_URL", "OASIS_APP_SERVER_SOCKET"}}
            environment["OASIS_APP_SERVER_SOCKET"] = "fixture-socket"
            with patch.dict(os.environ, environment, clear=True), \
                    patch("oasis_harness.sessions.shutil.which", return_value="fixture-codex"), \
                    patch("oasis_harness.sessions.subprocess.Popen", side_effect=launch):
                with sessions.deadline_scope(timeout=5), sessions.AppServer("proxy_fixture") as client:
                    yield client

    def test_default_proxy_upgrades_before_first_rpc_and_frames_utf8(self):
        with LoopbackServer(fragmented=True, coalesced=True) as server, self.proxy_client(server) as client:
            self.assertEqual(client.backend, "proxy")
            self.assertEqual(client.call("echo", {"text": "한글" * 12000}), {"text": "한글" * 12000})
            self.assertEqual(client.drain_events()[0]["method"], "fixture/ready")
            process = client.process
            self.assertTrue(server.requests[0].startswith(b"GET / HTTP/1.1\r\n"))
            self.assertEqual([row["method"] for row in server.messages[:2]], ["initialize", "initialized"])
            self.assertEqual(client.diagnostics()["rpc_by_method"], {"initialize": 1, "echo": 1})
        self.assertIsNotNone(process.poll())
        self.assertEqual(server.errors, [])

    def test_proxy_invalid_upgrade_sends_no_rpc_and_preserves_protocol_error(self):
        with LoopbackServer(handshake="bad_accept") as server:
            with self.assertRaisesRegex(HarnessError, "acceptance or negotiation"):
                with self.proxy_client(server):
                    self.fail("Invalid handshake was accepted")
            self.assertEqual(server.messages, [])

    def test_proxy_response_loss_never_replays_the_request(self):
        with LoopbackServer() as server, self.proxy_client(server) as client:
            with self.assertRaisesRegex(HarnessError, "outcome uncertain"):
                client.call("disconnect", {}, timeout=1)
            self.assertEqual(sum(row.get("method") == "disconnect" for row in server.messages), 1)

    def injected_client(self, transport):
        scope = patch.dict(os.environ, {}, clear=True)
        select = patch("oasis_harness.sessions.shutil.which", return_value="fixture-codex")
        connect = patch("oasis_harness.sessions._ProxyTransport", return_value=transport)
        for patcher in (scope, select, connect):
            patcher.start()
            self.addCleanup(patcher.stop)
        client = sessions.AppServer("injected_wire")
        self.addCleanup(client.close)
        return client

    def test_command_profile_opts_out_only_deltas_and_preserves_terminal_events(self):
        wire = InjectedTransport()
        with patch.dict(os.environ, {}, clear=True), patch("oasis_harness.sessions.shutil.which", return_value="fixture"), \
                patch("oasis_harness.sessions._ProxyTransport", return_value=wire):
            with sessions.command_server("command_fixture") as client:
                capabilities = wire.sent[0]["params"]["capabilities"]
                self.assertEqual(capabilities["optOutNotificationMethods"], list(sessions.COMMAND_DELTAS))
                wire.feed({"method": "turn/completed", "params": {"turn": {"id": "final"}}})
                wire.feed(None)
                client.reader.join(timeout=1)
                self.assertEqual(client.drain_events()[0]["method"], "turn/completed")
        wire = InjectedTransport()
        client = self.injected_client(wire)
        self.assertNotIn("optOutNotificationMethods", wire.sent[0]["params"]["capabilities"])

    def test_command_profile_falls_back_only_for_explicit_capability_rejection(self):
        for message, retries in (("Unknown optOutNotificationMethods capability", 2), ("Bad client information", 1)):
            wire = InjectedTransport()
            original = wire.send
            def send(text, *, timeout=30):
                request = json.loads(text)
                if request.get("method") == "initialize" and not wire.sent:
                    wire.sent.append(request)
                    wire.feed({"id": request["id"], "error": {"code": -32602, "message": message}})
                else:
                    original(text, timeout=timeout)
            wire.send = send
            with patch.dict(os.environ, {}, clear=True), patch("oasis_harness.sessions.shutil.which", return_value="fixture"), \
                    patch("oasis_harness.sessions._ProxyTransport", return_value=wire):
                if retries == 2:
                    with sessions.command_server("fixture"):
                        pass
                else:
                    with self.assertRaises(sessions.NativeError):
                        sessions.command_server("fixture")
            requests = [row for row in wire.sent if row.get("method") == "initialize"]
            self.assertEqual(len(requests), retries)
            if retries == 2:
                self.assertNotIn("optOutNotificationMethods", requests[-1]["params"]["capabilities"])

    def test_expired_encoding_or_masking_never_writes_to_transport(self):
        from unittest.mock import Mock
        socket_wire = object.__new__(sessions._LoopbackWebSocket)
        socket_wire.closed = socket_wire.sent_close = False
        socket_wire.socket = Mock()
        with patch("oasis_harness.sessions.time.monotonic", side_effect=[0, 2]):
            with self.assertRaises(TimeoutError):
                socket_wire._frame(1, b"payload", timeout=1)
        socket_wire.socket.sendall.assert_not_called()
        proxy = object.__new__(sessions._ProxyStream)
        proxy.process = Mock()
        with patch("oasis_harness.sessions.time.monotonic", side_effect=[0, 2]):
            with self.assertRaises(TimeoutError):
                proxy.write(b"payload", timeout=1)
        proxy.process.stdin.write.assert_not_called()
        client = object.__new__(sessions.AppServer)
        client.transport = Mock()
        with patch("oasis_harness.sessions.time.monotonic", return_value=2):
            with self.assertRaisesRegex(HarnessError, "send timed out"):
                client._send({"method": "mutation"}, deadline=1)
        client.transport.send.assert_not_called()

    def test_rpc_dispatches_reversed_concurrent_responses_and_preserves_events_at_eof(self):
        wire = InjectedTransport()
        client = self.injected_client(wire)
        requests, results, errors = [], {}, []
        final = {"method": "turn/completed", "params": {"turn": {"id": "fixture-turn", "status": "completed"}}}
        def send(value):
            if value.get("method") not in ("first", "second"):
                return
            requests.append(value)
            if len(requests) == 2:
                wire.feed({"method": "item/outputDelta", "params": {"delta": "fixture"}})
                for request in reversed(requests):
                    wire.feed({"id": request["id"], "result": request["method"]})
                wire.feed(final)
                wire.feed(None)
        wire.on_send = send
        def call(method):
            try:
                results[method] = client.call(method, {}, timeout=1)
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=call, args=(method,)) for method in ("first", "second")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
        self.assertEqual(errors, [])
        self.assertEqual(results, {"first": "first", "second": "second"})
        client.reader.join(timeout=1)
        events = client.drain_events()
        self.assertEqual([event["method"] for event in events], ["item/outputDelta", "turn/completed"])
        self.assertEqual(events[-1], final)
        self.assertEqual(client.diagnostics()["state"], "closed")
        self.assertEqual(len({row["id"] for row in requests}), 2)

    def test_initialize_protocol_and_overflow_errors_keep_their_actual_cause(self):
        cases = [(["[]"], "non-object protocol message"),
                 ([{"method": "fixture/first", "params": {}}, {"method": "fixture/overflow", "params": {}}], "event buffer overflow")]
        for messages, cause in cases:
            with self.subTest(cause=cause), patch.object(sessions._RpcInbox, "EVENT_LIMIT", 1):
                wire = InjectedTransport()
                wire.initialize_messages = messages
                wire.private_tail = "PRIVATE_FIXTURE_DETAIL"
                with self.assertRaisesRegex(HarnessError, cause) as error:
                    self.injected_client(wire)
                self.assertNotIn("daemon/control socket", str(error.exception))
                self.assertNotIn("PRIVATE_FIXTURE_DETAIL", str(error.exception))

    def test_eof_wakes_all_pending_calls_and_future_call_without_losing_final_event(self):
        wire = InjectedTransport()
        client = self.injected_client(wire)
        requests, errors = [], []
        def send(value):
            if value.get("method") == "waiting":
                requests.append(value)
                if len(requests) == 2:
                    wire.feed({"method": "turn/completed", "params": {"status": "failed"}})
                    wire.feed(None)
        wire.on_send = send
        def call():
            try:
                client.call("waiting", {}, timeout=1)
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=call) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
        self.assertEqual(len(errors), 2)
        self.assertTrue(all(isinstance(error, HarnessError) and "outcome uncertain" in str(error) for error in errors))
        count = len(wire.sent)
        with self.assertRaisesRegex(HarnessError, "connection ended"):
            client.call("after_eof", {}, timeout=1)
        self.assertEqual(len(wire.sent), count)
        self.assertEqual(client.drain_events(), [{"method": "turn/completed", "params": {"status": "failed"}}])

    def test_event_wait_wakes_on_notification_and_eof_without_model_requests(self):
        wire = InjectedTransport()
        client = self.injected_client(wire)
        calls = len(wire.sent)
        event = {"method": "fs/changed", "params": {"watchId": "scoped", "changedPaths": []}}
        timer = threading.Timer(0.02, lambda: wire.feed(event))
        timer.start()
        self.addCleanup(timer.join, 1)
        self.assertEqual(client.wait_events(1), [event])
        self.assertEqual(client.wait_events(0), [])
        wire.feed(None)
        client.reader.join(timeout=1)
        self.assertEqual(client.wait_events(1), [])
        self.assertEqual(len(wire.sent), calls)
        for timeout in (-1, True, float("nan"), "1"):
            with self.subTest(timeout=timeout), self.assertRaises(HarnessError):
                client.wait_events(timeout)

    def test_event_wait_retains_protocol_error_and_buffered_notifications(self):
        client = object.__new__(sessions.AppServer)
        client._rpc = sessions._RpcInbox()
        event = {"method": "fs/changed", "params": {"watchId": "scoped", "changedPaths": []}}
        client._rpc.notification(event, 1)
        client._rpc.end("Actual protocol failure", failed=True, event_error=True)
        with self.assertRaisesRegex(HarnessError, "Actual protocol failure"):
            client.wait_events(0)
        self.assertEqual(client.wait_events(0), [event])

    def test_bad_envelopes_are_protocol_errors_and_native_rejection_stays_distinct(self):
        nested = '{"id":2,"result":' + '[' * 20000 + '0' + ']' * 20000 + '}'
        for case, invalid in enumerate(("[]", "null", "{", nested, '{"id":2,"result":{"value":NaN}}', '{"id":2,"id":2,"result":{}}',
                                       {"jsonrpc": "1.0", "id": 2, "result": {}}, {"id": 2}, {"id": 2, "error": None}, {"id": 2, "result": {}, "error": {}})):
            with self.subTest(case=case):
                wire = InjectedTransport()
                client = self.injected_client(wire)
                wire.on_send = lambda value: wire.feed(invalid)
                with self.assertRaises(HarnessError) as error:
                    client.call("malformed", {}, timeout=1)
                self.assertNotIsInstance(error.exception, sessions.NativeError)
                self.assertEqual(client.diagnostics()["state"], "failed")
                client.close()
        wire = InjectedTransport()
        client = self.injected_client(wire)
        wire.on_send = lambda value: wire.feed({"id": value["id"], "error": {"code": 403, "message": "Fixture denial"}})
        with self.assertRaises(sessions.NativeError) as error:
            client.call("denied", {}, timeout=1)
        self.assertEqual(error.exception.code, 403)
        self.assertEqual(client.diagnostics()["state"], "connected")

    def test_event_limits_report_overflow_and_keep_the_accepted_buffer(self):
        for byte_limit in (False, True):
            with self.subTest(byte_limit=byte_limit):
                wire = InjectedTransport()
                client = self.injected_client(wire)
                count = 2 if byte_limit else 257
                if byte_limit:
                    client._rpc.EVENT_BYTES = 1500
                def flood(value):
                    for index in range(count):
                        wire.feed({"method": "item/outputDelta", "params": {"index": index, "text": "x" * (900 if byte_limit else 1)}})
                wire.on_send = flood
                with self.assertRaisesRegex(HarnessError, "event buffer overflow"):
                    client.call("flood", {}, timeout=2)
                with self.assertRaisesRegex(HarnessError, "event buffer overflow"):
                    client.drain_events()
                events = client.drain_events()
                self.assertEqual(len(events), 1 if byte_limit else 256)
                self.assertEqual([event["params"]["index"] for event in events], list(range(len(events))))
                self.assertIn("overflow", client.diagnostics()["event_error"])
                self.assertEqual(client.diagnostics()["buffered_events"], 0)
                client.close()

    def test_unsupported_server_requests_are_rejected_without_ui_or_stderr_disclosure(self):
        wire = InjectedTransport()
        wire.private_tail = "PRIVATE_FIXTURE_DETAIL"
        client = self.injected_client(wire)
        def send(value):
            if value.get("method") == "interactive":
                wire.feed({"id": "fixture-approval", "method": "item/commandExecution/requestApproval", "params": {}})
                wire.feed({"id": value["id"], "result": {"accepted": True}})
            elif value.get("method") == "denied":
                wire.feed({"id": value["id"], "error": {"code": 403, "message": "Fixture denial"}})
        wire.on_send = send
        self.assertEqual(client.call("interactive", {}, timeout=1), {"accepted": True})
        rejection = next(value for value in wire.sent if value.get("id") == "fixture-approval")
        self.assertEqual(rejection["error"], {"code": -32601, "message": "Unsupported server request"})
        self.assertEqual(client.drain_events(), [])
        self.assertEqual(client.diagnostics()["unsupported_methods"], ["item/commandExecution/requestApproval"])
        self.assertEqual(client.diagnostics()["stderr_tail"], "PRIVATE_FIXTURE_DETAIL")
        with self.assertRaises(sessions.NativeError) as error:
            client.call("denied", {}, timeout=1)
        self.assertNotIn("PRIVATE_FIXTURE_DETAIL", str(error.exception))

    def test_proxy_stream_preserves_binary_bytes_and_partial_reads(self):
        proxy = object.__new__(sessions._ProxyStream)
        proxy.buffer = bytearray()
        proxy.closed, proxy.eof, proxy.timeout = False, False, 0.01
        proxy.chunks = queue.Queue(maxsize=16)
        with self.assertRaises(TimeoutError):
            proxy.recv(1)
        proxy.chunks.put(b"\x81\xff\n\x00")
        proxy.chunks.put(b"")
        self.assertEqual(proxy.recv(1), b"\x81")
        self.assertEqual(proxy.recv(64), b"\xff\n\x00")
        self.assertEqual(proxy.recv(1), b"")
        self.assertEqual(proxy.recv(1), b"")

    def test_stdio_blocked_write_or_flush_closes_only_own_proxy_with_a_deadline(self):
        for block_flush in (False, True):
            with self.subTest(block_flush=block_flush):
                release, entered, finished = threading.Event(), threading.Event(), threading.Event()
                class Input:
                    closed = False
                    def write(self, data):
                        if not block_flush:
                            entered.set()
                            release.wait(2)
                        return len(data)
                    def flush(self):
                        if block_flush:
                            entered.set()
                            release.wait(2)
                    def close(self):
                        self.closed = True
                process = Mock()
                process.stdin, process.stdout, process.stderr = Input(), io.BytesIO(), io.BytesIO()
                process.poll.return_value = None
                process.wait.return_value = 0
                process.terminate.side_effect = release.set
                proxy = object.__new__(sessions._ProxyStream)
                proxy.process, proxy.closed = process, False
                proxy.write_lock, proxy.close_lock = threading.Lock(), threading.Lock()
                proxy.stderr_reader = Mock()
                proxy.stdout_reader = Mock()
                proxy.chunks = queue.Queue(maxsize=16)
                errors = []
                def send():
                    try:
                        proxy.write(b'{"id":1,"method":"fixture"}', timeout=0.03)
                    except Exception as exc:
                        errors.append(exc)
                    finally:
                        finished.set()
                thread = threading.Thread(target=send, daemon=True)
                thread.start()
                self.assertTrue(entered.wait(0.2))
                timely = finished.wait(0.6)
                release.set()
                thread.join(timeout=1)
                self.assertTrue(timely)
                self.assertIsInstance(errors[0], TimeoutError)
                process.terminate.assert_called_once_with()
                proxy.close()
                process.terminate.assert_called_once_with()

    def test_private_stderr_ring_is_drained_and_bounded(self):
        proxy = object.__new__(sessions._ProxyStream)
        marker = b"PRIVATE_FIXTURE_DETAIL"
        proxy.process = SimpleNamespace(stderr=io.BytesIO(b"x" * (64 * 1024) + marker))
        proxy.stderr_buffer, proxy.stderr_bytes = bytearray(), 0
        proxy.stderr_lock = threading.Lock()
        proxy._stderr()
        tail, truncated = proxy.stderr_tail()
        self.assertTrue(truncated)
        self.assertEqual(len(tail.encode()), 64 * 1024)
        self.assertTrue(tail.endswith(marker.decode()))

    def socket_transport(self, *, saturated=False):
        connection, peer = socket.socketpair()
        self.addCleanup(peer.close)
        self.addCleanup(connection.close)
        if saturated:
            connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
            peer.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
            connection.setblocking(False)
            deadline = time.monotonic() + 2
            while True:
                try:
                    while True:
                        connection.send(b"x" * 65536)
                except BlockingIOError:
                    pass
                if not select.select([], [connection], [], 0.05)[1]:
                    break
                if time.monotonic() >= deadline:
                    self.fail("Disposable socket send buffer did not saturate")
            connection.settimeout(None)
        transport = object.__new__(sessions._LoopbackWebSocket)
        transport.socket = connection
        transport.buffer = bytearray()
        transport.write_lock = threading.RLock()
        transport.closed = transport.sent_close = False
        self.addCleanup(transport.close)
        return transport, peer

    def bounded_action(self, transport, action):
        finished = threading.Event()
        errors = []

        def run():
            try:
                action()
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()

        thread = threading.Thread(target=run, daemon=True)
        started = time.monotonic()
        thread.start()
        timely = finished.wait(0.7)
        elapsed = time.monotonic() - started
        # A regression must release its real blocked syscall before failing.
        if not timely:
            transport.socket.shutdown(socket.SHUT_RDWR)
        thread.join(timeout=1)
        self.assertTrue(timely, "Socket action blocked past its deadline")
        self.assertLess(elapsed, 0.7)
        return errors

    def connect(self, server):
        scope = patch.dict(os.environ, {"OASIS_APP_SERVER_URL": server.url})
        scope.start()
        self.addCleanup(scope.stop)
        return sessions.AppServer("loopback_fixture")

    def test_close_is_bounded_when_the_real_send_buffer_is_saturated(self):
        transport, peer = self.socket_transport(saturated=True)
        errors = self.bounded_action(transport, transport.close)
        self.assertEqual(errors, [])
        self.assertTrue(transport.closed)
        self.assertEqual(transport.socket.fileno(), -1)
        self.assertNotEqual(peer.fileno(), -1)
        transport.close()

    def test_call_deadline_includes_a_saturated_websocket_write(self):
        transport, _ = self.socket_transport(saturated=True)
        client = object.__new__(sessions.AppServer)
        client.transport, client.process = transport, None
        client._rpc = sessions._RpcInbox()
        client.sequence = 0
        errors = self.bounded_action(transport, lambda: client.call("fixture/write", {}, timeout=0.1))
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], HarnessError)
        self.assertIn("send timed out; outcome uncertain", str(errors[0]))
        self.assertEqual(client.sequence, 1)
        self.assertTrue(transport.closed)

    def test_protocol_failure_close_is_bounded_when_the_peer_does_not_read(self):
        transport, peer = self.socket_transport(saturated=True)
        peer.sendall(b"\xc1\x00")
        errors = self.bounded_action(transport, transport.receive)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], HarnessError)
        self.assertIn("unsupported extensions", str(errors[0]))
        self.assertTrue(transport.closed)

    def test_write_deadline_does_not_change_an_idle_reader_timeout(self):
        transport, peer = self.socket_transport()
        received, errors = [], []
        finished = threading.Event()

        def read():
            try:
                received.append(transport.receive())
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        transport.send("bounded outgoing message", timeout=0.05)
        self.assertIsNone(transport.socket.gettimeout())
        self.assertFalse(finished.wait(0.1))
        peer.sendall(server_frame(b"still receiving"))
        self.assertTrue(finished.wait(1))
        reader.join(timeout=1)
        self.assertEqual(received, ["still receiving"])
        self.assertEqual(errors, [])
        self.assertFalse(transport.closed)

    def test_explicit_endpoint_uses_no_subprocess_and_server_survives_client_close(self):
        with LoopbackServer(coalesced=True) as server, patch("oasis_harness.sessions.subprocess.Popen") as start:
            with self.connect(server) as client:
                self.assertEqual(client.call("echo", {"value": "first client"}), {"value": "first client"})
                self.assertIsNone(client.process)
            with self.connect(server) as client:
                self.assertEqual(client.call("echo", {"value": "second client"}), {"value": "second client"})
            start.assert_not_called()
            self.assertTrue(server.close_received.wait(1))
            self.assertEqual(len([row for row in server.messages if row.get("method") == "initialize"]), 2)
            self.assertTrue(server.requests[0].startswith(b"GET /native?fixture=1 HTTP/1.1\r\n"))
            self.assertEqual(server.errors, [])

    def test_masks_and_all_frame_length_encodings_roundtrip(self):
        with LoopbackServer() as server, self.connect(server) as client:
            for length in (10, 300, 70000):
                message = {"text": "x" * length}
                self.assertEqual(client.call("echo", message), message)
            widths = [tag for method, tag in server.widths if method == "echo"]
            self.assertLess(widths[0], 126)
            self.assertEqual(widths[1:], [126, 127])
            self.assertEqual(server.errors, [])

    def test_fragmented_unicode_message_and_interleaved_ping(self):
        with LoopbackServer(fragmented=True) as server, self.connect(server) as client:
            self.assertEqual(client.call("echo", {"text": "유니코드"}), {"text": "유니코드"})
            self.assertTrue(server.pong.wait(1))
            self.assertEqual(server.pongs[0], b"fixture-ping")
            self.assertEqual(server.errors, [])

    def test_bad_handshake_never_follows_redirect_or_accepts_unoffered_extension(self):
        for handshake in ("bad_accept", "duplicate_accept", "no_upgrade", "redirect", "extension"):
            with self.subTest(handshake=handshake), LoopbackServer(handshake=handshake) as server:
                with self.assertRaises(HarnessError):
                    self.connect(server)

    def test_invalid_urls_fail_before_any_network_or_subprocess(self):
        fixture_credential_url = "ws://" + "user:fixture-password" + "@127.0.0.1:12"
        urls = ("", "http://127.0.0.1:12", "wss://127.0.0.1:12", "ws://192.0.2.1:12", "ws://example.invalid:12",
                "ws://localhost.example:12", fixture_credential_url, "ws://127.0.0.1:bad",
                "ws://127.0.0.1:0", "ws://127.0.0.1:65536", "ws://127.0.0.1:12/#fragment", " ws://127.0.0.1:12",
                "ws://127.0.0.1:12/\r\ninjected", "ws://[::1%scope]:12")
        for value in urls:
            with self.subTest(value=value), patch.dict(os.environ, {"OASIS_APP_SERVER_URL": value}), \
                    patch("oasis_harness.sessions.socket.create_connection") as connect, patch("oasis_harness.sessions.subprocess.Popen") as start:
                with self.assertRaises(HarnessError) as error:
                    sessions.AppServer("fixture")
                self.assertNotIn("fixture-password", str(error.exception))
                connect.assert_not_called()
                start.assert_not_called()

    def test_localhost_and_ipv6_loopback_are_literal_local_destinations(self):
        self.assertEqual(sessions._LoopbackWebSocket.endpoint("ws://localhost:12/")[:2], ("127.0.0.1", 12))
        self.assertEqual(sessions._LoopbackWebSocket.endpoint("ws://[::1]:12/")[:2], ("::1", 12))
        self.assertEqual(sessions._LoopbackWebSocket.endpoint("ws://127.0.0.2:12/")[:2], ("127.0.0.2", 12))

    def test_invalid_server_frames_close_with_protocol_specific_status(self):
        cases = [
            (b"\x81\x80", 1002),  # A server must never mask.
            (b"\xc1\x00", 1002),  # RSV1 was not negotiated.
            (b"\x89\x7e", 1002),  # Extended control payload.
            (b"\x09\x00", 1002),  # Fragmented ping.
            (b"\x80\x00", 1002),  # Unsolicited continuation.
            (b"\x81\x7e\x00\x01x", 1002),  # Nonminimal length.
            (b"\x81\x7f" + struct.pack("!Q", 1 << 63), 1002),
            (b"\x81\x7f" + struct.pack("!Q", sessions._LoopbackWebSocket.MAX_MESSAGE + 1), 1009),
            (server_frame(b"\xff"), 1007),
            (server_frame(b"binary", 2), 1003),
            (server_frame(b"x", 8), 1002),
            (server_frame(struct.pack("!H", 1005), 8), 1002),
            (server_frame(struct.pack("!H", 1000) + b"\xff", 8), 1007),
        ]
        for raw, code in cases:
            with self.subTest(code=code, header=raw[:2]), LoopbackServer(invalid=raw) as server, self.connect(server) as client:
                with self.assertRaises(HarnessError):
                    client.call("bad_frame", {}, timeout=2)
                self.assertTrue(server.close_received.wait(1), f"Fixture errors: {server.errors}; client: {client.diagnostics()}")
                self.assertEqual(struct.unpack("!H", server.closes[0][:2])[0], code)

    def test_loopback_fixture_stays_open_between_requests_until_explicit_shutdown(self):
        with LoopbackServer() as server, self.connect(server) as client:
            # Previously the server itself closed after two idle seconds,
            # racing a later protocol assertion when the suite was delayed.
            client.reader.join(timeout=2.1)
            self.assertTrue(client.reader.is_alive(), f"Fixture errors: {server.errors}")
            self.assertEqual(client.call("echo", {"after_idle": True}, timeout=1), {"after_idle": True})
            self.assertEqual(server.errors, [])

    def test_peer_close_is_echoed_once_and_disconnect_is_an_uncertain_rpc(self):
        with LoopbackServer() as server, self.connect(server) as client:
            with self.assertRaisesRegex(HarnessError, "outcome uncertain"):
                client.call("remote_close", {}, timeout=2)
            self.assertTrue(server.close_received.wait(1))
            self.assertEqual(server.closes, [struct.pack("!H", 1000) + b"done"])
            client.close()
        with LoopbackServer() as server, self.connect(server) as client:
            with self.assertRaisesRegex(HarnessError, "outcome uncertain"):
                client.call("disconnect", {}, timeout=2)
            self.assertEqual(len([row for row in server.messages if row.get("method") == "disconnect"]), 1)

    def test_default_proxy_preserves_socket_selection_and_reports_the_prerequisite(self):
        process = Mock()
        process.stdin, process.stdout, process.stderr = io.BytesIO(), io.BytesIO(), io.BytesIO()
        process.wait.return_value = 1
        with patch.dict(os.environ, {"OASIS_APP_SERVER_SOCKET": "fixture-private-socket"}, clear=True), \
                patch("oasis_harness.sessions.shutil.which", return_value="fixture-codex"), \
                patch("oasis_harness.sessions.subprocess.Popen", return_value=process) as start:
            with self.assertRaisesRegex(HarnessError, "already running daemon/control socket") as error:
                sessions.AppServer("fixture")
            self.assertNotIn("fixture-private-socket", str(error.exception))
            self.assertEqual(start.call_args.args[0], ["fixture-codex", "app-server", "proxy", "--sock", "fixture-private-socket"])


if __name__ == "__main__":
    unittest.main()
