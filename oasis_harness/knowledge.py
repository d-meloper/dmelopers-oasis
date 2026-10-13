"""Local evidence cases and explicitly requested, fail-closed portable handoffs."""
from __future__ import annotations

from pathlib import Path
import os
import re

from .common import HarnessError, contained, digest, operation_lock, read_json
from .skills import check_core
from .installation import target_root

FIELDS = {"schema_version", "id", "classification", "problem", "observed", "hypotheses", "evidence",
          "delta", "conditions", "impact", "tests", "canonical_rule", "change_kind", "status", "limits"}
KINDS = {"knowledge", "existing-skill", "new-skill", "delete-skill", "core"}
SENSITIVE = (
    ("private path", r"(?i)(?:[a-z]:[\\/]|/Users/|/home/|\\\\[^\s]+\\)"),
    ("credential", r"(?i)(?:gh[pousr]_[A-Za-z0-9_]{8,}|github_pat_[A-Za-z0-9_]+|sk-[A-Za-z0-9_-]{12,}|-----BEGIN .*PRIVATE KEY-----|Bearer\s+\S+|(?:password|token|secret|api[_-]?key)\s*[:=]\s*[^\s,}]+)"),
    ("email", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    ("live identifier", r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),
    ("external target", r"https?://[^\s)]+"),
)
INTRUSION = re.compile(r"(?i)(?:bypass|disable|remove|ignore|override)\s+(?:all\s+)?(?:approval|permission|core|manual.relay|plan.wait)|(?:automatically|auto)\s+(?:publish|send|import|propagate)|(?:grant|enable)\s+(?:unrestricted|full.access)|(?:Camel|Calf)\s+(?:may|can|should|must)\s+(?:send|contact)[^.\n]*Cameleer")


def validate_case(case):
    if not isinstance(case, dict) or set(case) != FIELDS or case.get("schema_version") != 1:
        raise HarnessError("Knowledge case has unknown/missing fields or schema; use the documented case schema")
    if not isinstance(case["id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", case["id"]):
        raise HarnessError("Case id must be 3-64 lowercase letters, digits or hyphens")
    if case["classification"] not in {"generic", "windows", "project"} or case["change_kind"] not in KINDS:
        raise HarnessError("Unknown knowledge classification or change kind")
    if case["status"] not in {"observed", "evaluated", "adopted", "superseded"}:
        raise HarnessError("Unknown case status")
    for key in ("problem", "delta", "conditions", "impact", "canonical_rule"):
        if not isinstance(case[key], str) or not case[key].strip():
            raise HarnessError(f"Case {key} must contain substantive text")
    for key in ("observed", "hypotheses", "evidence", "tests", "limits"):
        if not isinstance(case[key], list):
            raise HarnessError(f"Case {key} must be a list")
    if not case["observed"] or not case["evidence"]:
        raise HarnessError("Capture requires an observation and evidence; a hypothesis alone is not a finding")
    for key in ("observed", "hypotheses", "limits"):
        if any(not isinstance(value, str) or not value.strip() for value in case[key]):
            raise HarnessError(f"Case {key} entries must be nonempty text")
    for evidence in case["evidence"]:
        if not isinstance(evidence, dict) or set(evidence) != {"label", "sha256", "scope"} or not all(isinstance(evidence[k], str) and evidence[k] for k in evidence):
            raise HarnessError("Evidence requires label, sha256 and scope; keep private raw paths outside the case")
        if not re.fullmatch(r"[0-9a-f]{64}", evidence["sha256"]):
            raise HarnessError("Evidence SHA256 is invalid")
    for test in case["tests"]:
        if not isinstance(test, dict) or set(test) != {"case", "outcome", "boundary", "evidence_sha256"}:
            raise HarnessError("Tests require case, outcome, boundary and evidence_sha256")
        if test["outcome"] not in {"pass", "fail", "not-run", "unknown"} or test["boundary"] not in {"static", "fixture", "semantic", "installed", "live"}:
            raise HarnessError("Invalid test outcome or proof boundary")
        if not isinstance(test["case"], str) or not test["case"]:
            raise HarnessError("Test case must be named")
        proof = test["evidence_sha256"]
        if test["outcome"] in {"pass", "fail"} and not (isinstance(proof, str) and re.fullmatch(r"[0-9a-f]{64}", proof)):
            raise HarnessError("Performed tests require an evidence digest")
        if proof is not None and (not isinstance(proof, str) or not re.fullmatch(r"[0-9a-f]{64}", proof)):
            raise HarnessError("Test evidence digest is invalid")
    if case["status"] in {"evaluated", "adopted"} and not case["tests"]:
        raise HarnessError("Evaluated/adopted cases require tests; labels alone are not proof")
    if case["status"] == "adopted" and not any(test["outcome"] == "pass" and test["boundary"] in {"semantic", "installed", "live"} for test in case["tests"]):
        raise HarnessError("Static/fixture checks alone do not establish adoption; retain the actual consumer evaluation")
    sensitive = contamination(case)
    if sensitive:
        raise HarnessError("Case contains private material: " + ", ".join(sensitive) + "; use opaque evidence labels")
    needs_approval = case["change_kind"] in {"new-skill", "delete-skill", "core"} or bool(INTRUSION.search(case["delta"]))
    if needs_approval and case["status"] == "adopted":
        raise HarnessError("Structural/core case cannot self-declare adoption; use the owner-approved versioned migration")
    return {"valid": True, "requires_owner_decision": needs_approval, "semantic_authority_review": "required",
            "proof": "schema and bounded contamination checks only; evidence assertions are not independently verified"}


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
    if case["classification"] == "project":
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
