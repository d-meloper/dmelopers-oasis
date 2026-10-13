"""Validate transport facts without manufacturing authority or truth."""
from __future__ import annotations

import re
from .common import HarnessError, read_json

WAIT = "PLAN-WAIT: reply with a brief owner-facing waiting acknowledgement only. No tools, reads, research, questions, implementation or workers. The owner starts planning here and explicitly requests implementation separately."
FIELDS = {
    "handoff": {"goal", "authority", "scope", "done", "mode", "source", "route"},
    "result": {"result", "scope", "source", "checks", "remaining"},
    "ownership": {"scope", "state", "window"},
    "knowledge": {"observation", "evidence", "scope", "uncertainty"},
}


def validate_source(source):
    if not isinstance(source, dict) or source.get("state") not in ("absent", "unborn", "committed"):
        raise HarnessError("Source state must be absent, unborn or committed")
    if source["state"] != "committed":
        if source.get("commit") or source.get("tree"):
            raise HarnessError("Uninitialized source cannot claim commit/tree evidence")
        return
    algorithm = source.get("object_format")
    length = {"sha1": 40, "sha256": 64}.get(algorithm)
    if not length or not re.fullmatch(r"[0-9a-f]{" + str(length) + "}", source.get("commit", "")) or set(source["commit"]) == {"0"}:
        raise HarnessError("A full typed nonzero commit ID is required")
    if source.get("tree") == source["commit"]:
        raise HarnessError("Commit and tree identity must not be conflated")


def validate(packet, *, send=False):
    if not isinstance(packet, dict) or packet.get("kind") not in FIELDS:
        raise HarnessError("Unknown packet kind")
    required = FIELDS[packet["kind"]]
    if any(key not in packet or packet[key] in (None, "", []) for key in required):
        raise HarnessError("Packet is missing material fields: " + ", ".join(sorted(required)))
    for key, value in packet.items():
        if key not in ("literals", "source") and isinstance(value, str) and any(c.isalpha() and not c.isascii() for c in value):
            raise HarnessError("Authored internal prose must be English; put exact localized data in literals")
    if "source" in packet:
        validate_source(packet["source"])
    if packet["kind"] == "handoff" and packet["mode"] not in ("execute", "plan-wait"):
        raise HarnessError("Unknown handoff mode")
    if packet["kind"] == "ownership" and packet["state"] not in ("request", "acknowledged", "released"):
        raise HarnessError("Delivery is not acknowledged ownership")
    if send:
        if not all(packet.get(key) for key in ("recipient", "sender_role", "recipient_role", "trigger", "need", "authority")):
            raise HarnessError("Sending needs actual authority, roles, recipient, trigger and required action")
        if packet["recipient_role"] == "Cameleer" and packet["sender_role"] in ("Camel", "Calf", "descendant"):
            raise HarnessError("Descendants cannot message Cameleer; the human relays locally retained results")
        if packet["trigger"] not in ("dispatch", "conflict", "decision", "dependency_ready", "completion", "owner_request"):
            raise HarnessError("Routine progress or acknowledgement loops do not authorize a send")
    return {"valid": True, "meaning_verified": False, "authority_verified": False,
            "rendered": (WAIT + "\n" if packet.get("mode") == "plan-wait" else "") + __import__("json").dumps(packet, ensure_ascii=False)}


def register(subparsers):
    parser = subparsers.add_parser("packet", help="Check an internal packet; this command never sends")
    parser.add_argument("path")
    parser.add_argument("--send", action="store_true", help="Validate delivery shape, not authorization")
    parser.set_defaults(func=lambda args: validate(read_json(args.path), send=args.send))
