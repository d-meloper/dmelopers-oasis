"""Codex metadata adapter. It never starts turns, sends prompts, or edits app storage."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
import uuid

from .common import HarnessError, clean_environment, operation_lock, read_json, write_json
from . import __version__

SOURCES = ["cli", "vscode", "exec", "appServer", "subAgent", "subAgentReview", "subAgentCompact", "subAgentThreadSpawn", "subAgentOther", "unknown"]
GROUP = re.compile(r"^Camel_([A-Z]+)_.+$")
OCCUPIED_GROUP = re.compile(r"^(?:Camel|Calf)_([A-Z]+)_.+$")


def canonical_root(path):
    return os.path.normcase(os.path.realpath(path))


class AppServer:
    def __init__(self, originator):
        executable = shutil.which("codex")
        if not executable:
            raise HarnessError("Codex CLI is unavailable; install or select the supported host explicitly")
        self.process = subprocess.Popen([executable, "app-server", "--stdio"], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                        encoding="utf-8", env=clean_environment(),
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.incoming = queue.Queue()
        self.sequence = 0
        threading.Thread(target=self._read, daemon=True).start()
        try:
            self.call("initialize", {"clientInfo": {"name": originator, "version": __version__}, "capabilities": {"experimentalApi": True}})
            self._send({"method": "initialized"})
        except Exception:
            self.close()
            raise

    def _read(self):
        for line in self.process.stdout:
            try:
                self.incoming.put(json.loads(line))
            except ValueError:
                continue
        self.incoming.put(None)

    def _send(self, value):
        self.process.stdin.write(json.dumps(value, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

    def call(self, method, params, timeout=30):
        self.sequence += 1
        sequence = self.sequence
        self._send({"id": sequence, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            try:
                reply = self.incoming.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty:
                raise HarnessError(f"{method}: outcome uncertain; reconcile before another mutation") from None
            if reply is None:
                raise HarnessError(f"{method}: connection ended; outcome uncertain")
            if reply.get("id") == sequence and "method" not in reply:
                if "error" in reply:
                    raise HarnessError(f"{method}: rejected ({reply['error'].get('code')}); no permission fallback")
                return reply["result"]
            if "id" in reply and "method" in reply:
                self._send({"id": reply["id"], "error": {"code": -32601, "message": "Metadata client runs no tools or turns"}})

    def pages(self, method, params):
        seen = set()
        while True:
            page = self.call(method, params)
            yield from page["data"]
            cursor = page.get("nextCursor")
            if not cursor:
                return
            if cursor in seen:
                raise HarnessError("Repeated Codex pagination cursor; discovery is incomplete")
            seen.add(cursor)
            params = {**params, "cursor": cursor}

    def close(self):
        if not self.process.stdin.closed:
            try:
                self.process.stdin.close()
            except BrokenPipeError:
                pass
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            self.process.wait(timeout=10)
        self.process.stdout.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def latest_settings(path):
    settings = None
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            payload = record.get("payload", {})
            if record.get("type") == "turn_context":
                settings = payload
            elif record.get("type") == "event_msg" and payload.get("type") == "thread_settings_applied":
                settings = payload["thread_settings"]
    if not settings:
        raise HarnessError("Caller has no saved settings; cannot infer permissions")
    return settings


def inherited_settings(settings):
    efforts = {settings[key] for key in ("reasoning_effort", "effort") if settings.get(key) is not None}
    if len(efforts) > 1:
        raise HarnessError("Saved reasoning fields disagree; inspect actual caller settings")
    reasoning = next(iter(efforts), None)
    profile = (settings.get("active_permission_profile") or {}).get("id")
    sandbox = settings.get("sandbox_policy") or {}
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
    if policy_type not in known:
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
    from .skills import check_core
    check_core(target)
    source = server.call("thread/read", {"threadId": source_id, "includeTurns": False})["thread"]
    settings = inherited_settings(latest_settings(source["path"]))
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


def title_for(role, goal, source, threads, receipts, *, pioneer_id=None):
    if any(row.get("phase") not in ("ready", "archived", "prepared") for row in receipts):
        raise HarnessError("An earlier creation is incomplete or uncertain; inspect and resume its receipt before creating another chat")
    if role in ("Oasis", "Cameleer", "Pioneer"):
        if any(row.get("name") == role for row in threads):
            raise HarnessError("This role already exists; inspect and reuse it instead of duplicating it")
        return role
    if role == "Developer":
        if not pioneer_id or source.get("id") != pioneer_id:
            raise HarnessError("A Developer requires the bound Pioneer as its actual caller, plus the owner's explicit delegation")
        if not goal or not goal.isascii() or any(c in goal for c in "\r\n\0"):
            raise HarnessError("Developer goal must be one nonempty English line")
        return f"Developer_{goal}"
    if role not in ("Camel", "Calf"):
        raise HarnessError("Unknown session role")
    if not goal or not goal.isascii() or any(c in goal for c in "\r\n\0"):
        raise HarnessError("Grouped goal must be one nonempty English line")
    if role == "Calf":
        match = GROUP.fullmatch(source.get("name") or "")
        if not match:
            raise HarnessError("A Calf requires its actual grouped Camel as caller")
        group = match[1]
    else:
        if source.get("name") != "Cameleer":
            raise HarnessError("A grouped Camel requires the actual Cameleer as caller")
        occupied = {match[1] for row in threads if (match := OCCUPIED_GROUP.fullmatch(row.get("name") or ""))}
        for receipt in receipts:
            if receipt.get("phase") != "archived" and (match := OCCUPIED_GROUP.fullmatch(receipt.get("title") or "")):
                occupied.add(match[1])
        index = 1
        while letters(index) in occupied:
            index += 1
        group = letters(index)
    return f"{role}_{group}_{goal}"


def verify_response(response, receipt):
    expected = receipt["settings"]
    if (response.get("activePermissionProfile") or {}).get("id") != expected["permissions"]:
        raise HarnessError("Saved permission profile mismatch")
    for key in ("approvalPolicy", "approvalsReviewer"):
        if response.get(key) != expected[key]:
            raise HarnessError(f"Saved {key} mismatch")
    if response.get("sandbox") != expected["effective_sandbox"]:
        raise HarnessError("Effective sandbox changed; no work may be delivered")
    if canonical_root(response["cwd"]) != canonical_root(receipt["target"]) or response["thread"].get("projectId") != receipt["project_id"]:
        raise HarnessError("Created project/root mismatch")
    if expected.get("model") and response.get("model") != expected["model"]:
        raise HarnessError("Model selection was not preserved")
    if expected.get("reasoning") and response.get("reasoningEffort") != expected["reasoning"]:
        raise HarnessError("Reasoning selection was not preserved")


def create_metadata(path, receipt, factory=AppServer):
    refresh_readiness(receipt)
    settings = receipt["settings"]
    options = {"cwd": receipt["target"], "projectId": receipt["project_id"],
               **{key: settings[key] for key in ("permissions", "approvalPolicy", "approvalsReviewer")}}
    if settings.get("model"):
        options["model"] = settings["model"]
    if settings.get("reasoning"):
        options["config"] = {"model_reasoning_effort": settings["reasoning"]}
    if not receipt.get("thread_id") and receipt["phase"] != "prepared":
        raise HarnessError("Uncertain creation must be reconciled before retry; never start another chat")
    try:
        with factory(receipt["originator"]) as server:
            if receipt.get("thread_id"):
                response = server.call("thread/resume", {"threadId": receipt["thread_id"], "excludeTurns": True})
            else:
                receipt["phase"] = "creation_started"
                write_json(path, receipt)
                response = server.call("thread/start", options)
                receipt.update(thread_id=response["thread"]["id"], phase="created")
                write_json(path, receipt)
            verify_response(response, receipt)
            server.call("thread/name/set", {"threadId": receipt["thread_id"], "name": receipt["title"]})
        receipt["phase"] = "named"
        write_json(path, receipt)
        with factory(receipt["originator"]) as server:
            resume = {key: value for key, value in options.items() if key not in ("cwd", "projectId")}
            response = server.call("thread/resume", {"threadId": receipt["thread_id"], "excludeTurns": True, **resume})
            verify_response(response, receipt)
        receipt["phase"] = "settings_saved"
        write_json(path, receipt)
        with factory(receipt["originator"]) as server:
            response = server.call("thread/resume", {"threadId": receipt["thread_id"], "excludeTurns": True})
            verify_response(response, receipt)
            if response["thread"].get("name") != receipt["title"]:
                raise HarnessError("Title did not survive cold resume")
        refresh_readiness(receipt)
        receipt.update(phase="ready", first_turn_verified=False, handoff_delivered=False)
        write_json(path, receipt)
        return receipt
    except Exception as exc:
        receipt["error"] = str(exc)
        write_json(path, receipt)
        raise


def inspect(path, factory=AppServer):
    receipt = read_json(path)
    with factory(receipt["originator"] + "_inspect") as server:
        rows = discover(server, receipt["target"], receipt["project_id"])
        identities = {row["id"] for row in rows if row.get("originator") == receipt["originator"]}
        if receipt.get("thread_id"):
            identities.add(receipt["thread_id"])
        if len(identities) != 1:
            return {"phase": "uncertain", "matches": sorted(identities), "retry_allowed": False}
        identity = next(iter(identities))
        thread = server.call("thread/read", {"threadId": identity, "includeTurns": False})["thread"]
        if canonical_root(thread["cwd"]) != canonical_root(receipt["target"]) or thread.get("projectId") != receipt["project_id"]:
            raise HarnessError("Reconciled thread belongs to another project/root")
        return {"phase": receipt["phase"], "thread_id": identity, "name": thread.get("name"),
                "target": thread.get("cwd"), "retry_allowed": False, "receipt": str(path)}


def resume(path, authority, factory=AppServer):
    if not authority:
        raise HarnessError("Resume only within the real owner's original session creation scope")
    receipt = read_json(path)
    with operation_lock(Path(receipt["target"]) / ".oasis/local/operations.lock"):
        result = inspect(path, factory)
        if not result.get("thread_id"):
            raise HarnessError("Creation identity is unresolved; no automatic retry is permitted")
        receipt["thread_id"] = result["thread_id"]
        write_json(path, receipt)
        return create_metadata(path, receipt, factory)


def source_readiness(target, requested_lane):
    from .skills import check_core
    from .gitops import status
    config = check_core(target)["project"]
    state = status(target)
    if state["profile"] != config["git"]["profile"]:
        raise HarnessError("Desired and active Git profiles differ; complete the reviewed transition before session delivery")
    if config["git"]["profile"] == "unmanaged":
        return {"profile": "unmanaged", "lane_action": "preserve existing workflow"}
    if not state["active"]:
        raise HarnessError("Managed source profile is inactive; repair its binding before session delivery")
    if not requested_lane or state["branch"] != requested_lane:
        raise HarnessError("Managed task needs an explicit lane matching the actual checkout; only its switch owner may transition it")
    return {"profile": state["profile"], "branch": state["branch"], "head": state["head"]}


def refresh_readiness(receipt):
    expected = receipt.get("source_readiness")
    if not isinstance(expected, dict):
        raise HarnessError("Session receipt has no source-readiness evidence; inspect current ownership before resumption")
    actual = source_readiness(receipt["target"], expected.get("branch"))
    if actual != expected:
        raise HarnessError("Source readiness changed; no work may be delivered until the owner reconciles this existing session")


def workflow_pioneer(target, source_id, server=None):
    """Read an established workflow binding; a title cannot assign Pioneer."""
    from .workflows import bound_pioneer
    return bound_pioneer(target, source_id, server)


def register(subparsers):
    parser = subparsers.add_parser("session", help="Codex metadata only; no prompt delivery or model turn")
    commands = parser.add_subparsers(dest="session_command", required=True)
    p = commands.add_parser("inspect")
    p.add_argument("receipt")
    p.set_defaults(func=lambda args: inspect(args.receipt))
    p = commands.add_parser("resume")
    p.add_argument("receipt")
    p.add_argument("--authority", required=True)
    p.set_defaults(func=lambda args: resume(args.receipt, args.authority))
    p = commands.add_parser("discovery")
    p.add_argument("--target", required=True)
    def discovery(args):
        with AppServer("oasis_discovery") as server:
            identity = project_id(server, args.target)
            result = server.call("skills/list", {"cwds": [str(Path(args.target).resolve())], "forceReload": True})
            return {"project_id": identity, "skills": result, "adoption_verified": False}
    p.set_defaults(func=discovery)
    p = commands.add_parser("create")
    p.add_argument("--target", required=True)
    p.add_argument("--role", required=True, choices=("Oasis", "Cameleer", "Camel", "Calf", "Pioneer", "Developer"))
    p.add_argument("--goal")
    p.add_argument("--lane", choices=("main", "test"))
    p.add_argument("--source-thread-id", default=os.environ.get("CODEX_THREAD_ID"))
    p.add_argument("--authority", help="Reference to the real owner request; a string is not independent proof")
    p.add_argument("--apply", action="store_true")
    def command(args):
        if not args.source_thread_id or (os.environ.get("CODEX_THREAD_ID") and args.source_thread_id != os.environ["CODEX_THREAD_ID"]):
            raise HarnessError("Actual caller thread ID is required")
        target = Path(args.target).resolve()
        receipts_root = target / ".oasis/local/sessions"
        if args.apply and not args.authority:
            raise HarnessError("Verify the owner's concrete session request before applying")
        def prepare_receipt():
            workflow_state = target / ".oasis/local/workflows/state.json"
            if workflow_state.exists() and read_json(workflow_state).get("pending_operation"):
                raise HarnessError("A workflow transition owns this project's checkpoint; finish/resume it before creating another role or worker")
            if args.role == "Pioneer":
                from .workflows import _root, effective_mode
                _, project = _root(target)
                if effective_mode(project) != "pioneer":
                    raise HarnessError("Pioneer metadata requires the selected Pioneer mode; use a reviewed workflow transition")
            readiness = source_readiness(target, args.lane)
            originator = "oasis_session_" + uuid.uuid4().hex
            with AppServer(originator) as server:
                identity, settings, source = prepare(server, args.source_thread_id, target)
                if args.role in ("Camel", "Calf", "Developer") and (canonical_root(source["cwd"]) != canonical_root(target) or source.get("projectId") != identity):
                    raise HarnessError("Task caller must belong to the target project")
                receipts = [read_json(path) for path in receipts_root.glob("*/receipt.json")]
                pioneer_id = workflow_pioneer(target, args.source_thread_id, server) if args.role == "Developer" else None
                if args.role == "Developer" and not args.authority:
                    raise HarnessError("An ordinary Developer needs the owner's explicit delegation; do not infer it from Pioneer mode")
                title = title_for(args.role, args.goal, source, discover(server, target, identity), receipts, pioneer_id=pioneer_id)
            return {"schema_version": 1, "originator": originator, "source_thread_id": args.source_thread_id,
                    "target": str(target), "project_id": identity, "settings": settings, "title": title,
                    "role": args.role, "parent_thread_id": args.source_thread_id if args.role in ("Camel", "Calf", "Developer") else None,
                    "assignment_marker": f"[OASIS_SESSION_ROLE {originator} {args.role}]",
                    "source_readiness": readiness,
                    "authority_reference": args.authority, "authority_independently_verified": False, "phase": "prepared"}
        if not args.apply:
            return prepare_receipt()
        with operation_lock(target / ".oasis/local/operations.lock"):
            receipt = prepare_receipt()
            path = receipts_root / receipt["originator"] / "receipt.json"
            write_json(path, receipt)
            return {**create_metadata(path, receipt), "receipt": str(path)}
    p.set_defaults(func=command)
