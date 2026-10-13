"""Real loopback RFC 6455 exchanges, without native chats or model calls."""
import base64
import hashlib
import io
import json
import os
import queue
import select
import socket
import struct
import threading
import time
import unittest
from unittest.mock import Mock, patch

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


class SessionTransportContracts(unittest.TestCase):
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
        client.incoming = queue.Queue()
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
                self.assertTrue(server.close_received.wait(1))
                self.assertEqual(struct.unpack("!H", server.closes[0][:2])[0], code)

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

    def test_default_proxy_is_preserved_and_reports_the_existing_socket_prerequisite(self):
        process = Mock()
        process.stdin, process.stdout = io.StringIO(), io.StringIO("")
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
