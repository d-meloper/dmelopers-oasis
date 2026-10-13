"""Local evidence cases and explicitly requested, fail-closed portable handoffs."""
from __future__ import annotations

from pathlib import Path
import os
import re

from .common import HarnessError, contained, digest, operation_lock, read_json
from .skills import check_core
from .installation import target_root

KINDS = {"knowledge", "existing-skill", "new-skill", "delete-skill", "core"}
SENSITIVE = (
    ("private path", r"(?i)(?:[a-z]:[\\/]|/Users/|/home/|\\\\[^\s]+\\)"),
    ("credential", r"(?i)(?:gh[pousr]_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]{12,}|-----BEGIN .*PRIVATE KEY-----|Bearer\s+\S+|(?:password|token|secret|api[_-]?key)\s*[:=]\s*[^\s,}]+)"),
    ("email", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    ("live identifier", r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),
    ("external target", r"https?://[^\s)]+"),
)


def validate_case(case):
    """Accept reusable notes without a required evidence or behavior schema."""
    if not isinstance(case, dict):
        raise HarnessError("Knowledge input must be a JSON object")
    if not isinstance(case.get("id"), str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", case["id"]):
        raise HarnessError("Case id must be 3-64 lowercase letters, digits or hyphens")
    if "classification" in case and case["classification"] not in ("generic", "windows", "project"):
        raise HarnessError("Knowledge classification must be generic, windows or project")
    sensitive = contamination(case)
    if sensitive:
        raise HarnessError("Case contains private material: " + ", ".join(sensitive) + "; use opaque evidence labels")
    return {"valid": True, "requires_owner_decision": case.get("change_kind") in {"new-skill", "delete-skill", "core"},
            "proof": "JSON input and bounded contamination checks only; note assertions are not independently verified"}

def contamination(value, project_terms=()):
    import json
    text = json.dumps(value, ensure_ascii=False)
    findings = [label for label, pattern in SENSITIVE if re.search(pattern, text)]
    findings += ["project-specific term" for term in project_terms if term and term.casefold() in text.casefold()]
    return sorted(set(findings))


def capture(root, case):
    root = target_root(root)
    result = validate_case(case)
    with operation_lock(contained(root, ".oasis/local/operations.lock")):
        check_core(root)
        target = contained(root, f"BestPractice/history/{case['id']}.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        import json
        try:
            with target.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(case, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError as exc:
            raise HarnessError("Historical case already exists; preserve it and capture a separately identified correction") from exc
    return {"case": case["id"], "sha256": digest(case), **result,
            "adopted_rule": False, "next": "Review evidence and update the one canonical rule within approved scope"}


def prepare_export(root, case, output, owner_requested=False):
    if not owner_requested:
        raise HarnessError("Export requires the explicit owner request; a flag records operator intent, not human authentication")
    state = check_core(root)
    result = validate_case(case)
    if case.get("classification") == "project":
        raise HarnessError("Project-specific cases require an independently reviewed generic/Windows derivation before export")
    findings = contamination(case, (state["project"]["name"],))
    if findings:
        raise HarnessError("Portable handoff blocked by contamination: " + ", ".join(findings))
    payload = {"schema_version": 1, "kind": "sanitized-upstream-handoff", "case": case,
               "core_version": state["core_version"], "source_case_digest": digest(case),
               "state": "prepared-local-not-sent-not-imported", "validation": result,
               "limits": ["Bounded screening cannot prove complete sanitization", "Owner review of the concrete handoff remains necessary", "No sending or upstream application is authorized by this file"]}
    output = Path(output)
    if output.exists():
        raise HarnessError("Export destination exists; preserve it and select a new local file")
    if output.is_symlink():
        raise HarnessError("Linked export destination is not supported")
    # Check ancestors even when the leaf does not exist.
    from .common import is_reparse
    if any(parent.is_symlink() or is_reparse(parent) for parent in output.absolute().parents):
        raise HarnessError("Linked export ancestor is not supported")
    output.parent.mkdir(parents=True, exist_ok=True)
    import json
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return {"status": payload["state"], "sha256": digest(payload), "sent": False, "imported": False}


def register(subparsers):
    parser = subparsers.add_parser("knowledge", help="Capture evidence cases and prepare owner-requested local handoffs")
    subs = parser.add_subparsers(dest="knowledge_action", required=True)
    for name in ("capture", "validate", "export"):
        item = subs.add_parser(name)
        item.add_argument("--case", required=True)
        if name != "validate":
            item.add_argument("--project", required=True)
        if name == "capture":
            item.set_defaults(func=lambda args: capture(args.project, read_json(args.case)))
        elif name == "validate":
            item.set_defaults(func=lambda args: validate_case(read_json(args.case)))
        else:
            item.add_argument("--output", required=True)
            item.add_argument("--owner-requested", action="store_true")
            item.set_defaults(func=lambda args: prepare_export(args.project, read_json(args.case), args.output, args.owner_requested))
