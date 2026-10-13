import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from oasis_harness.common import HarnessError, atomic_write, operation_lock, read_json, clean_environment, contained, safe_relative, run


class PrimitiveContracts(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Requires native Windows handle sharing")
    def test_atomic_write_recovers_after_real_windows_reader_releases(self):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "state-한글.json"
            target.write_bytes(b"old durable state")
            # Share reads/writes but deny deletion/replacement while open.
            handle = kernel.CreateFileW(str(target), 0x80000000, 3, None, 3, 0x80, None)
            self.assertNotEqual(handle, wintypes.HANDLE(-1).value, ctypes.get_last_error())
            released = False
            def release_reader(_):
                nonlocal released
                self.assertEqual(target.read_bytes(), b"old durable state")
                if not released:
                    self.assertTrue(kernel.CloseHandle(handle))
                    released = True
            try:
                with patch("oasis_harness.common.time.sleep", side_effect=release_reader) as pause:
                    atomic_write(target, b"new durable state")
                    self.assertGreaterEqual(pause.call_count, 1)
                self.assertEqual(target.read_bytes(), b"new durable state")
                self.assertEqual(list(Path(tmp).iterdir()), [target])
            finally:
                if not released:
                    kernel.CloseHandle(handle)

    @unittest.skipUnless(os.name == "nt", "Requires Windows error codes")
    def test_atomic_write_permanent_denial_is_bounded_and_preserves_old_bytes(self):
        import ctypes
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "state.json"
            target.write_bytes(b"old")
            for code in (5, 32):
                with self.subTest(winerror=code), patch("oasis_harness.common.os.replace", side_effect=ctypes.WinError(code)) as replace:
                    with patch("oasis_harness.common.time.sleep") as pause:
                        with self.assertRaises(OSError) as failure:
                            atomic_write(target, b"new")
                        self.assertEqual(failure.exception.winerror, code)
                        self.assertEqual(replace.call_count, 6)
                        self.assertEqual(pause.call_count, 5)
                        self.assertAlmostEqual(sum(call.args[0] for call in pause.call_args_list), 0.62)
                self.assertEqual(target.read_bytes(), b"old")
                self.assertEqual(list(Path(tmp).iterdir()), [target])

    def test_atomic_write_unrelated_error_and_link_drift_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "state.json"
            target.write_bytes(b"old")
            with patch("oasis_harness.common.os.replace", side_effect=OSError("unrelated error")) as replace:
                with patch("oasis_harness.common.time.sleep") as pause:
                    with self.assertRaises(OSError):
                        atomic_write(target, b"new")
                    self.assertEqual(replace.call_count, 1)
                    pause.assert_not_called()
            # Revalidate the destination after staging, not only before it.
            with patch("oasis_harness.common.is_reparse", side_effect=[False, True]):
                with patch("oasis_harness.common.os.replace") as replace:
                    with self.assertRaises(HarnessError):
                        atomic_write(target, b"new")
                    replace.assert_not_called()
            self.assertEqual(target.read_bytes(), b"old")
            self.assertEqual(list(Path(tmp).iterdir()), [target])

    def test_cli_json_roundtrips_unicode_under_redirected_legacy_encoding(self):
        import json
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "Legacy text 😶"
            target.mkdir()
            launcher = Path(__file__).resolve().parents[1] / "oasis.py"
            env = clean_environment({"PYTHONIOENCODING":"cp949"})
            audit = subprocess.run([sys.executable, "-B", str(launcher), "install", "audit", "--target", str(target)],
                                   capture_output=True, env=env)
            self.assertEqual(audit.returncode, 0, audit.stderr)
            self.assertEqual(Path(json.loads(audit.stdout)["target"]), target.resolve())
            failure = subprocess.run([sys.executable, "-B", str(launcher), "install", "verify", "--target", str(target)],
                                     capture_output=True, env=env)
            self.assertEqual(failure.returncode, 1)
            self.assertIn("😶", json.loads(failure.stderr)["error"])

    def test_native_protocol_stdin_preserves_lf_bytes(self):
        import sys
        result=run([sys.executable,"-c","import sys; print(sys.stdin.buffer.read().hex())"],input_text="first\nsecond\n")
        self.assertEqual(result.stdout.strip(),b"first\nsecond\n".hex())
    def test_rejected_contenders_never_remove_owner_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lock"
            with operation_lock(path) as owner:
                for _ in range(2):
                    with self.assertRaises(HarnessError):
                        with operation_lock(path):
                            self.fail("contender entered")
                    self.assertEqual(read_json(path)["token"], owner)
            self.assertFalse(path.exists())

    def test_git_and_credential_environment_are_not_inherited(self):
        with patch.dict(os.environ, {"GIT_DIR": "foreign", "GIT_INDEX_FILE": "foreign", "GH_TOKEN": "secret", "GITHUB_TOKEN": "secret"}):
            env = clean_environment()
            self.assertFalse(set(env) & {"GIT_DIR", "GIT_INDEX_FILE", "GH_TOKEN", "GITHUB_TOKEN"})

    def test_windows_path_escape_and_aliases(self):
        for path in ("../escape", "a//b", "a/../b", "C:/escape", "a\\b", "a/CON.txt", "a/file.", "a/x:y", "a/x*", "/absolute", "a/COM¹.txt", "a/control\x01"):
            with self.subTest(path=path), self.assertRaises(HarnessError):
                safe_relative(path)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(contained(tmp, "Unicode-한글/file.txt").is_relative_to(Path(tmp).resolve()))


if __name__ == "__main__":
    unittest.main()
