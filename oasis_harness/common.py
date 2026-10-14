"""Small shared primitives. No imports from the project carrying this package."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
import time
import uuid


class HarnessError(RuntimeError):
    """An actionable boundary failure; never permission to bypass that boundary."""


class ProcessTimeout(HarnessError):
    """Private partial output for an owned command that did not finish."""
    def __init__(self, timeout, stdout=b"", stderr=b""):
        super().__init__(f"Process timed out after {timeout} seconds; partial output is private evidence")
        self.stdout = stdout.decode("utf-8", errors="replace") if isinstance(stdout, bytes) else stdout or ""
        self.stderr = stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else stderr or ""


def json_object(value, label):
    if not isinstance(value, dict):
        raise HarnessError(f"{label} must be a JSON object")
    return value


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise HarnessError(f"Cannot read JSON {path}: {exc}") from exc


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or is_reparse(path):
        raise HarnessError(f"Refusing linked destination: {path}")
    data = content.encode("utf-8") if isinstance(content, str) else content
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        # Windows readers can briefly deny replacement even after our own
        # handle is closed. Retry only this local replacement of the same
        # flushed bytes; never replay a caller's external operation or remove
        # the destination to force success. Permanent denial still propagates.
        for attempt in range(6):
            if path.is_symlink() or is_reparse(path):
                raise HarnessError(f"Refusing linked destination: {path}")
            try:
                os.replace(temporary, path)
                break
            except OSError as exc:
                if os.name != "nt" or getattr(exc, "winerror", None) not in (5, 32) or attempt == 5:
                    raise
                time.sleep(0.02 * 2 ** attempt)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def write_new_json(path, value):
    """Create new evidence exclusively; ongoing journals use write_json."""
    path = Path(path).absolute()
    if any(candidate.is_symlink() or is_reparse(candidate) for candidate in (path, *path.parents)):
        raise HarnessError("Linked evidence destination is not supported")
    path.parent.mkdir(parents=True, exist_ok=True)
    if any(candidate.is_symlink() or is_reparse(candidate) for candidate in path.parents):
        raise HarnessError("Linked evidence ancestor is not supported")
    try:
        with path.open("xb") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise HarnessError("Evidence output already exists; preserve it and select a new file") from exc


def is_reparse(path):
    try:
        return bool(getattr(Path(path).lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    except FileNotFoundError:
        return False


def safe_relative(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or "\x00" in value:
        raise HarnessError("Expected a nonempty portable relative path")
    parts = value.split("/")
    if any(part in ("", ".", "..") or part.rstrip(" .") != part or any(c in part for c in '<>"|?*\r\n') or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in part) for part in parts):
        raise HarnessError(f"Unsafe relative path: {value!r}")
    if PurePosixPath(value).is_absolute():
        raise HarnessError(f"Absolute path is not permitted: {value!r}")
    devices = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10)), *(f"{prefix}{suffix}" for prefix in ("COM", "LPT") for suffix in "¹²³")}
    if any(part.split(".")[0].upper() in devices for part in parts):
        raise HarnessError(f"Reserved Windows path: {value!r}")
    return value


def contained(root, relative):
    root = Path(root).resolve()
    relative = safe_relative(relative)
    current = root
    for part in relative.split("/"):
        current /= part
        if current.is_symlink() or is_reparse(current):
            raise HarnessError(f"Linked path is not supported: {current}")
    if not current.resolve().is_relative_to(root):
        raise HarnessError("Path escaped its declared root")
    return current


def clean_environment(extra=None):
    # A hook's GIT_DIR/INDEX/WORK_TREE must never redirect a relay or fixture.
    stripped = {"GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN", "GH_DEBUG"}
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_") and key.upper() not in stripped}
    if extra:
        env.update(extra)
    return env


def run(argv, *, cwd=None, input_text=None, input_bytes=None, env=None, check=True, timeout=120):
    if input_text is not None and input_bytes is not None:
        raise HarnessError("Select text or byte input, not both")
    payload = input_text.encode("utf-8") if input_text is not None else input_bytes
    try:
        result = subprocess.run([str(arg) for arg in argv], cwd=cwd, input=payload,
                                capture_output=True,
                                env=clean_environment(env), timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ProcessTimeout(timeout, exc.output, exc.stderr) from exc
    except OSError as exc:
        raise HarnessError(f"Process could not complete: {type(exc).__name__}: {exc}") from exc
    result.stdout = result.stdout.decode("utf-8", errors="replace")
    result.stderr = result.stderr.decode("utf-8", errors="replace")
    if check and result.returncode:
        raise HarnessError(f"Process exited {result.returncode}: {result.stderr.strip() or result.stdout.strip()}")
    return result


def git(root, *args, check=True, input_text=None):
    return run(["git", "-C", str(root), *args], check=check, input_text=input_text).stdout.strip()


def git_objects(root, identities):
    """Read exact binary objects in bounded batches without checkout filters."""
    identities = list(identities)
    if any(not isinstance(oid, str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", oid) for oid in identities):
        raise HarnessError("Git object identities must be complete hexadecimal IDs")
    for offset in range(0, len(identities), 128):
        requested = identities[offset:offset + 128]
        try:
            metadata = subprocess.run(["git", "-C", str(root), "cat-file", "--batch-check"],
                                    input=("\n".join(requested) + "\n").encode("ascii"),
                                    capture_output=True, env=clean_environment(), timeout=120)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HarnessError("Cannot read complete Git object batch") from exc
        if metadata.returncode:
            raise HarnessError("Cannot read complete Git object batch")
        try:
            lines = metadata.stdout.splitlines(keepends=True)
            if len(lines) != len(requested):
                raise ValueError("Incomplete metadata inventory")
            records = []
            for expected, line in zip(requested, lines):
                if not line.endswith(b"\n") or line.endswith(b"\r\n"):
                    raise ValueError("Incomplete metadata framing")
                fields = line[:-1].split(b" ")
                if len(fields) != 3 or fields[0].decode("ascii") != expected or not re.fullmatch(rb"0|[1-9][0-9]*", fields[2]):
                    raise ValueError("Object identity/type header differs")
                kind = fields[1].decode("ascii")
                size = int(fields[2])
                if kind not in {"blob", "tree", "commit", "tag"}:
                    raise ValueError("Invalid object header")
                records.append((expected, kind, size))
            groups, group, byte_count = [], [], 0
            for record in records:
                if group and byte_count + record[2] > GIT_OBJECT_BATCH_BYTES:
                    groups.append(group)
                    group, byte_count = [], 0
                group.append(record)
                byte_count += record[2]
            if group:
                groups.append(group)
            for group in groups:
                try:
                    result = subprocess.run(["git", "-C", str(root), "cat-file", "--batch"],
                                            input=("\n".join(row[0] for row in group) + "\n").encode("ascii"),
                                            capture_output=True, env=clean_environment(), timeout=120)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    raise HarnessError("Cannot read complete Git object batch") from exc
                if result.returncode:
                    raise HarnessError("Cannot read complete Git object batch")
                cursor = 0
                for expected, kind, size in group:
                    end = result.stdout.index(b"\n", cursor)
                    if result.stdout[cursor:end] != f"{expected} {kind} {size}".encode("ascii"):
                        raise ValueError("Object changed since metadata inspection")
                    cursor = end + 1
                    data = result.stdout[cursor:cursor + size]
                    cursor += size
                    if len(data) != size or result.stdout[cursor:cursor + 1] != b"\n":
                        raise ValueError("Truncated object framing")
                    cursor += 1
                    yield expected, kind, data
                if cursor != len(result.stdout):
                    raise ValueError("Unexpected trailing object bytes")
        except (ValueError, UnicodeError, IndexError) as exc:
            raise HarnessError("Git object batch framing is incomplete or invalid") from exc


GIT_OBJECT_BATCH_BYTES = 16 * 1024 * 1024


@contextlib.contextmanager
def operation_lock(path):
    """Only a successful acquirer may release this exact lock token."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise HarnessError(f"Operation is already locked: {path}; inspect its owner before recovery") from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"token": token, "pid": os.getpid()}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        yield token
    finally:
        if path.exists() and read_json(path).get("token") == token:
            path.unlink()
