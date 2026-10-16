"""Desktop byte-pipe contract fixtures; no native chat or model requests."""
import json
import os
import struct
import threading
import time
import unittest
import uuid
from unittest.mock import patch

from oasis_harness import desktop_tools as desktop, sessions


PIPE = r"\\.\pipe\codex-app-tools-fixture"


def result(value):
    return {"success": True, "contentItems": [{"type": "inputText", "text": json.dumps(value, ensure_ascii=False)}]}


class ByteStream:
    """Independent partial byte stream that records only complete requests."""
    def __init__(self, response=None, *, read_size=3, write_size=7, delay=0, wire=None, close_error=False):
        self.response = response or (lambda request: {"id": request["id"], "jsonrpc": "2.0", "result": result({"accepted": True})})
        self.read_size, self.write_size, self.delay = read_size, write_size, delay
        self.wire, self.close_error = wire, close_error
        self.written, self.incoming = bytearray(), bytearray()
        self.requests, self.closed, self.opens = [], False, 0

    def open(self, path, deadline):
        self.opens += 1
        return self

    def write(self, value, *, deadline):
        count = min(len(value), self.write_size)
        self.written.extend(value[:count])
        if len(self.written) >= 4 and len(self.written) == 4 + struct.unpack("<I", self.written[:4])[0]:
            request = json.loads(self.written[4:].decode("utf-8"))
            self.requests.append(request)
            if self.wire is None:
                value = self.response(request)
                if value is not None:
                    payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
                    self.incoming.extend(struct.pack("<I", len(payload)) + payload)
            else:
                self.incoming.extend(self.wire)
        return count

    def read(self, size, *, deadline):
        if self.delay:
            remaining = deadline - time.monotonic()
            time.sleep(max(0, min(self.delay, remaining)))
            if time.monotonic() >= deadline:
                raise TimeoutError("Fixture read deadline")
        count = min(size, self.read_size, len(self.incoming))
        value = bytes(self.incoming[:count])
        del self.incoming[:count]
        return value

    def close(self, *, deadline=None):
        self.closed = True
        if self.close_error:
            raise OSError("Fixture close failed")


class DesktopPipeContracts(unittest.TestCase):
    def client(self, stream):
        return desktop.DesktopTools(PIPE, "actual-caller", "actual-turn", opener=stream.open)

    def test_partial_utf8_reads_and_writes_preserve_real_metadata_and_call_id(self):
        stream = ByteStream()
        answer = self.client(stream).call("create_thread", {"prompt": "한글 😶"}, call_id="stable-mutation")
        self.assertEqual(answer, {"accepted": True})
        self.assertEqual(len(stream.requests), 1)
        request = stream.requests[0]
        self.assertEqual(request["method"], "tools/call")
        self.assertEqual(request["params"], {"arguments": {"prompt": "한글 😶"}, "callerSource": "codex",
                         "callId": "stable-mutation", "hostId": "local", "namespace": "codex_app",
                         "threadId": "actual-caller", "tool": "create_thread", "turnId": "actual-turn"})
        self.assertTrue(stream.closed)

    def test_catalog_request_has_only_its_own_schema_and_filters_namespace(self):
        tools = [{"name": "create_thread", "namespace": "codex_app", "inputSchema": {"type": "object"}},
                 {"name": "uninstall_plugin", "namespace": "plugin_management", "inputSchema": {}}]
        stream = ByteStream(lambda request: {"id": request["id"], "jsonrpc": "2.0", "result": {"tools": tools}})
        self.assertEqual(self.client(stream).list_tools(), tools[:1])
        self.assertEqual(stream.requests[0]["params"], {"threadStartKind": "all"})

    def test_local_windows_pipe_and_nonempty_caller_identity_are_required(self):
        for path in (r"\\server\pipe\remote", "ws://127.0.0.1", "\\\\.\\pipe\\", r"\\.\pipe\nested\child", "C:/file", PIPE + "\0"):
            with self.subTest(path=path), self.assertRaises(desktop.DesktopNotSent):
                desktop.DesktopTools(path, "caller", "turn")
        for thread, turn, host in (("", "turn", "local"), ("caller", None, "local"), ("caller", "turn", " ")):
            with self.subTest(thread=thread, turn=turn), self.assertRaises(desktop.DesktopNotSent):
                desktop.DesktopTools(PIPE, thread, turn, host)

    def test_invalid_or_oversized_input_never_opens_the_pipe(self):
        stream = ByteStream()
        client = self.client(stream)
        cases = [("tool", {"bad": float("nan")}, {}), ("tool", {"bad": object()}, {}),
                 ("tool", {"bad": "\ud800"}, {}), ("tool", [], {}), ("", {}, {}),
                 ("tool", {}, {"call_id": ""}), ("tool", {"large": "x" * desktop.MAX_BYTES}, {})]
        for tool, arguments, options in cases:
            with self.subTest(tool=tool, options=options), self.assertRaises(desktop.DesktopNotSent):
                client.call(tool, arguments, **options)
        self.assertEqual(stream.opens, 0)

    def test_invalid_timeout_or_expired_outer_budget_never_dispatches(self):
        stream = ByteStream()
        client = self.client(stream)
        for timeout in (True, 0, -1, "30", float("inf"), float("nan")):
            with self.subTest(timeout=timeout), self.assertRaises(desktop.DesktopNotSent):
                client.call("tool", {}, timeout=timeout)
        with sessions.deadline_scope(timeout=1), patch("oasis_harness.sessions.remaining_timeout", side_effect=sessions.DeadlineExceeded("expired")):
            with self.assertRaises(desktop.DesktopNotSent):
                client.call("tool", {})
        self.assertEqual(stream.opens, 0)

    def test_connect_failure_is_known_not_sent(self):
        def unavailable(path, deadline):
            raise OSError("Fixture unavailable")
        with self.assertRaises(desktop.DesktopNotSent):
            desktop.DesktopTools(PIPE, "caller", "turn", opener=unavailable).call("tool", {})

    def test_eof_after_one_dispatch_is_uncertain_and_never_replayed(self):
        stream = ByteStream(response=lambda _: None)
        with self.assertRaises(desktop.DesktopUncertain):
            self.client(stream).call("create_thread", {"prompt": "once"}, call_id="stable-once")
        self.assertEqual(stream.opens, 1)
        self.assertEqual(len(stream.requests), 1)
        self.assertTrue(stream.closed)

    def test_zero_partial_or_invalid_frame_is_uncertain(self):
        for wire in (b"", b"\1\0", struct.pack("<I", 0), struct.pack("<I", desktop.MAX_BYTES + 1),
                     struct.pack("<I", 4) + b"ab"):
            with self.subTest(wire=wire):
                stream = ByteStream(wire=wire)
                with self.assertRaises(desktop.DesktopUncertain):
                    self.client(stream).call("tool", {})
                self.assertEqual(len(stream.requests), 1)
                self.assertTrue(stream.closed)

    def test_invalid_json_utf8_duplicate_fields_nonfinite_or_nonobject_rejected(self):
        for payload in (b"\xff", b"not-json", b"[]", b'{"id":1,"id":2}', b'{"number":NaN}', b'{"number":1e999}'):
            stream = ByteStream(wire=struct.pack("<I", len(payload)) + payload)
            with self.subTest(payload=payload), self.assertRaises(desktop.DesktopUncertain):
                self.client(stream).call("tool", {})
            self.assertTrue(stream.closed)

    def test_response_identity_version_and_result_error_exclusivity(self):
        variants = [lambda value: {**value, "id": "another-request"}, lambda value: {**value, "id": True},
                    lambda value: {**value, "jsonrpc": "1.0"}, lambda value: {**value, "error": {"code": 1, "message": "bad"}},
                    lambda value: {key: item for key, item in value.items() if key != "result"},
                    lambda value: {**value, "result": []}]
        for mutate in variants:
            stream = ByteStream(lambda request: mutate({"id": request["id"], "jsonrpc": "2.0", "result": result({})}))
            with self.subTest(mutate=mutate), self.assertRaises(desktop.DesktopUncertain):
                self.client(stream).call("tool", {})

    def test_error_reply_is_distinct_and_does_not_leak_remote_content(self):
        stream = ByteStream(lambda request: {"id": request["id"], "jsonrpc": "2.0",
                            "error": {"code": -32602, "message": "private prompt content"}})
        with self.assertRaises(desktop.DesktopRejected) as rejected:
            self.client(stream).call("tool", {})
        self.assertEqual(rejected.exception.code, -32602)
        self.assertNotIn("private prompt", str(rejected.exception))
        self.assertTrue(stream.closed)

    def test_error_reply_schema_is_checked(self):
        for error in ([], {}, {"code": True, "message": "bad"}, {"code": -32602, "message": None}):
            stream = ByteStream(lambda request: {"id": request["id"], "jsonrpc": "2.0", "error": error})
            with self.subTest(error=error), self.assertRaises(desktop.DesktopUncertain):
                self.client(stream).call("tool", {})

    def test_tool_failure_is_a_received_failure_without_claiming_rollback(self):
        stream = ByteStream(lambda request: {"id": request["id"], "jsonrpc": "2.0", "result": {"success": False, "contentItems": []}})
        with self.assertRaises(desktop.DesktopRejected):
            self.client(stream).call("tool", {})
        self.assertEqual(len(stream.requests), 1)

    def test_tool_content_is_exactly_one_json_text_object(self):
        variants = [{}, {"success": 1, "contentItems": []}, {"success": True, "contentItems": []},
                    {"success": True, "contentItems": [{"type": "inputImage", "imageUrl": "fixture"}]},
                    {"success": True, "contentItems": [{"type": "inputText", "text": "[]"}]},
                    {"success": True, "contentItems": [{"type": "inputText", "text": "{}"}] * 2}]
        for value in variants:
            stream = ByteStream(lambda request: {"id": request["id"], "jsonrpc": "2.0", "result": value})
            with self.subTest(value=value), self.assertRaises(desktop.DesktopUncertain):
                self.client(stream).call("tool", {})

    def test_failure_content_is_still_validated_before_treating_it_as_a_native_reply(self):
        for item in (None, {"type": "unknown"}, {"type": "inputText", "text": 1}):
            stream = ByteStream(lambda request: {"id": request["id"], "jsonrpc": "2.0",
                                "result": {"success": False, "contentItems": [item]}})
            with self.subTest(item=item), self.assertRaises(desktop.DesktopUncertain):
                self.client(stream).call("tool", {})

    def test_catalog_rejects_missing_schema_or_names(self):
        for catalog in (None, [{}], [{"name": "tool", "namespace": "codex_app", "inputSchema": []}]):
            stream = ByteStream(lambda request: {"id": request["id"], "jsonrpc": "2.0", "result": {"tools": catalog}})
            with self.subTest(catalog=catalog), self.assertRaises(desktop.DesktopUncertain):
                self.client(stream).list_tools()

    def test_one_absolute_deadline_covers_fragmented_reads_and_closes_owned_stream(self):
        stream = ByteStream(read_size=1, delay=0.02)
        started = time.monotonic()
        with self.assertRaises(desktop.DesktopUncertain):
            self.client(stream).call("tool", {}, timeout=0.055)
        self.assertLess(time.monotonic() - started, 0.2)
        self.assertEqual(len(stream.requests), 1)
        self.assertTrue(stream.closed)

    def test_invalid_partial_write_count_is_uncertain(self):
        for count in (0, None, True, -1, desktop.MAX_BYTES + 100):
            stream = ByteStream()
            stream.write = lambda value, deadline, count=count: count
            with self.subTest(count=count), self.assertRaises(desktop.DesktopUncertain):
                self.client(stream).call("tool", {})
            self.assertTrue(stream.closed)

    def test_cleanup_failure_does_not_hide_a_received_rejection(self):
        stream = ByteStream(lambda request: {"id": request["id"], "jsonrpc": "2.0", "error": {"code": -32602, "message": "rejected"}}, close_error=True)
        with self.assertRaises(desktop.DesktopRejected) as rejected:
            self.client(stream).call("tool", {})
        self.assertTrue(rejected.exception.__notes__)


@unittest.skipUnless(os.name == "nt", "Windows byte-pipe fixtures")
class WindowsDesktopPipeContracts(unittest.TestCase):
    def server(self, *, lose_response=False, stall_write=False):
        import _winapi as api
        path = r"\\.\pipe\oasis-desktop-fixture-" + uuid.uuid4().hex
        handle = api.CreateNamedPipe(path, api.PIPE_ACCESS_DUPLEX | api.FILE_FLAG_OVERLAPPED,
                                     0,  # PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT
                                     1, 65536, 65536, 0, 0)
        operation = api.ConnectNamedPipe(handle, overlapped=True)
        stream = object.__new__(desktop._WindowsPipe)
        stream.api, stream.handle = api, handle
        received, release = threading.Event(), threading.Event()
        requests, failures = [], []
        def worker():
            try:
                if api.WaitForSingleObject(operation.event, 2000) != api.WAIT_OBJECT_0:
                    raise TimeoutError("Fixture client did not connect")
                operation.GetOverlappedResult(False)
                if stall_write:
                    received.set()
                    release.wait(2)
                    return
                deadline = time.monotonic() + 2
                def read(size):
                    data = bytearray()
                    while len(data) < size:
                        chunk = stream.read(size - len(data), deadline=deadline)
                        if not chunk:
                            raise EOFError
                        data.extend(chunk)
                    return bytes(data)
                size = struct.unpack("<I", read(4))[0]
                request = json.loads(read(size).decode("utf-8"))
                requests.append(request)
                received.set()
                if lose_response:
                    release.wait(2)
                else:
                    payload = json.dumps({"id": request["id"], "jsonrpc": "2.0", "result": result({"nativePipe": True})}).encode("utf-8")
                    frame = struct.pack("<I", len(payload)) + payload
                    for offset in range(0, len(frame), 3):
                        stream.write(frame[offset:offset + 3], deadline=deadline)
            except Exception as exc:
                failures.append(exc)
            finally:
                stream.close()
        thread = threading.Thread(target=worker, name="oasis-desktop-pipe-fixture")
        thread.start()
        def cleanup():
            release.set()
            thread.join(3)
            self.assertFalse(thread.is_alive(), "Native fixture thread leaked")
            self.assertEqual(failures, [])
        self.addCleanup(cleanup)
        return path, received, requests

    def test_real_windows_byte_pipe_round_trip_and_same_account_peer(self):
        path, received, requests = self.server()
        self.assertEqual(desktop.DesktopTools(path, "caller", "turn").call("fixture_tool", {}), {"nativePipe": True})
        self.assertTrue(received.is_set())
        self.assertEqual(len(requests), 1)

    def test_real_windows_pending_read_deadline_cancels_without_retry_or_reader_thread(self):
        path, received, requests = self.server(lose_response=True)
        started = time.monotonic()
        with self.assertRaises(desktop.DesktopUncertain):
            desktop.DesktopTools(path, "caller", "turn").call("fixture_tool", {}, timeout=0.15, call_id="once")
        self.assertLess(time.monotonic() - started, 0.8)
        self.assertTrue(received.is_set())
        self.assertEqual(len(requests), 1)

    def test_real_windows_pending_write_deadline_cancels_owned_io(self):
        path, connected, requests = self.server(stall_write=True)
        started = time.monotonic()
        with self.assertRaises(desktop.DesktopUncertain):
            desktop.DesktopTools(path, "caller", "turn").call("fixture_tool", {"bytes": "x" * 200000}, timeout=0.15)
        self.assertLess(time.monotonic() - started, 0.8)
        self.assertTrue(connected.is_set())
        self.assertEqual(requests, [])


if __name__ == "__main__":
    unittest.main()
