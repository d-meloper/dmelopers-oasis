# Project modes and task workflow

Pioneer handles requested work in one visible chat. Oasis uses Cameleer and Camel,
with Oasis maintaining the harness. All 24 skills are active after installation.

## Mode selection

`extensions.workflow.mode` is `pioneer` or `oasis`. Fresh empty projects default
to Pioneer; programs, scaffolds and product data default to Oasis. A valid install
without a mode uses Oasis. The owner selects mode; updates and task pacing
preserve it.

Installation initializes one Pioneer, or Oasis plus Cameleer. An install-only
request leaves roles ready for work; an accompanying task can start immediately.
File installation and native initialization are distinct results. Uncertain
creation retains the existing operation for recovery.

Pioneer implements directly and uses requested workers. Cameleer assigns and
integrates; Camel investigates, implements and checks. Independent assignments
retain their work and locations across mode changes. Installed
`LocalGitWorkflow.md` covers practical coordination.

## Assign, collect and resume

Cameleer keeps `.oasis/state/tasks.md` concise: actual chat ID/link, goal, stage,
dependency, work location, result and performed checks. Update it at assignment,
collection and resume. Read active work or the relevant row; finished entries
retain short outcomes and links.

Source operators use `oasis.py`; adopters use installed `tools/oasis.py`.
Use command help for current IDs and inputs.

| Command | Work |
|---|---|
| `workflow assign` | Create Camel, deliver goal/context and retain its connection |
| `workflow complete` | Send the short terminal result directly to Cameleer |
| `workflow collect` | Record reviewed/integrated result and archive the finished Camel |
| `workflow task-resume` | Restore the same Camel for follow-up or unfinished work |
| `workflow tasks` | Show active work or a requested task; finished history is available |
| `workflow dependency-wait` | Retain the blocked part and producer/consumer IDs |
| `workflow dependency-finish` | Send its terminal result once |

Before calling `workflow complete` or giving the final completion report,
consolidate useful experience once under [knowledge](knowledge.md). The runtime
reminder identifies this step; it does not perform a retrospective after sending
completion or prove that reference edits occurred.

`assign` takes target, Cameleer ID and goal, with optional context, location,
title and request ID. `complete` accepts a free-form result/check summary and
completed, failed or cancelled outcome. Cameleer checks the request, diff and
performed checks, rerunning only checks affected by integration or a concrete
concern. `collect` retains the result/check summary and merged reference.
Duplicate notices do not repeat integration. Incomplete work stays available.

Follow-up uses the existing task ID with `task-resume`. Dependencies name one
blocked portion. Finish independent work, end the turn and resume from the
producer's notice when that portion completes, fails or is cancelled.

## Planning and fast work

A planning request, including `계획작업으로 진행해`, uses actual native Plan
mode and starts the supplied task. `assign --plan` and `task-resume --plan`
use supported settings/update or turn/start fields. Unsupported paths give
the manual mode/start instruction once. Implementation follows the user,
including `task-resume --implementation`.

`빠른 작업으로 진행해` selects prompt implementation and brief relevant checks.
Report deferred verification precisely. Installed `ProjectGuide.md` holds pacing
conventions; pacing preserves project mode.

## Mode transitions

`workflow status`, `plan`, `start`, `inspect` and `resume` retain requested
initialization, switches and recovery. Carry the goal, decisions, work location,
checks and unfinished/resume information while preserving settings and source.

Create required target roles, deliver context through supported native turns
and archive only linked finished scope. Preserve independent and unfinished
work. Parent archive may cascade: inspect concrete descendant IDs and verify
each affected ID. Mode changes after the requested transition completes.
Interrupted operations retain target IDs and outcomes for reconciliation.

## Recovery and evidence

Retained action state binds actual task/chat IDs and result references. Native
rejection and lost replies remain distinct. Reconcile an uncertain send with
actual history before retry; recover the affected action while preserving others.

Local fixtures exercise failure/cancellation, duplicates, renaming, Plan
fallback, archive/restore and preserved files. Actual model behavior, visible UI,
completion arrival and integration require evidence at their respective boundary.
See [sessions](sessions.md), [validation](validation.md) and [CHANGELOG](CHANGELOG.md).
