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
| `workflow complete` | Record result submission; notify Cameleer after native terminal readiness |
| `workflow collect` | Record reviewed/integrated result and archive the finished Camel |
| `workflow task-resume` | Restore the same Camel for follow-up or unfinished work |
| `workflow tasks` | Show active work or a requested task; `--summary` adds dependencies, pending handoffs and warnings |
| `workflow dependency-wait` | Retain the blocked part and producer/consumer IDs |
| `workflow dependency-finish` | Send its terminal result once |

Before calling `workflow complete` or giving the final completion report,
consolidate useful experience once under [knowledge](knowledge.md). The runtime
reminder identifies this step; it does not perform a retrospective after sending
completion or prove that reference edits occurred.

`assign` takes target, Cameleer ID and goal, with optional context, location,
title and request ID. `complete` accepts a free-form result/check summary and
completed, failed or cancelled outcome and returns after submission. It does not
wake Cameleer before the assigned native turn is terminal-ready. Cameleer checks
the request, diff and performed checks, reusing matching consumed-input evidence
and rerunning checks affected by integration or a concrete concern. State the
reason for a repeated check in the existing result; independent review still
examines relevant original inputs. `collect` retains the result/check summary and merged reference.
Duplicate notices do not repeat integration. Incomplete work stays available.
For a successful result, `collect` verifies the assigned turn is still latest,
has native `completed` status and nonempty `agentMessage.phase=final_answer`
output, and its chat is `idle` or `notLoaded`, before integration and again
before archival. Result submission can arrive earlier and stays distinct from
ready notification. Exact lifecycle events are preferred; a scoped native
filesystem watch is the bounded fallback. `collect --timeout` defaults to a
30-second whole budget covering connection, RPC, I/O and cleanup. The Python
`wait_timeout` remains an event budget bounded by that whole deadline.
Collection returns `awaiting_terminal` if still pending or observation is
unavailable. Unverified assignment identity
returns `terminal_unverified`; native failure/interruption returns failed or
cancelled. These boundaries leave the chat available without marking successful
collection. Call-owned watches are removed when the call ends; the separate
[scoped observer](sessions.md#workflow-observation) owns registered future
notification without keeping a model turn alive.
Waiting leaves the project mutation lock free. Collection then reloads current
state under the lock; a changed assignment returns `collection_changed` without
applying the caller's review, merging or archiving.
Location is assignment context and does not silently change the native cwd.
Reused request IDs must match their retained meaning; existing delivery keys and
message text are preserved.

Follow-up uses the existing task ID with `task-resume`.

## Waiting and resumption

`assign` already subscribes its Cameleer to whole-assignment completion. End the
turn, resume from that notice, review and collect/archive; no second whole-task
dependency, confirmation turn or dependency-finish is needed. A dependency from
the assigned Camel to that Cameleer reuses this task/cycle/result subscription by
default. `--purpose assignment` makes the intent explicit; `--purpose partial`
keeps a distinct partial result or resource notice, including while the producer
continues. Other consumers retain their own notices. Existing untyped records
keep their original scope and are not reinterpreted from free-form text.

All roles, including Developer and independent specialists, register the blocked
portion and its producer/consumer IDs, finish independent work, and end their
turn. Resume from its meaningful result, failure or cancellation notice. Do not
keep a model turn open to inspect status, result files or elapsed time.
Waiting turn termination does not complete the assignment or trigger its final
experience pass.
A registered consumer dependency preserves that waiting state instead of sending
a missing-result notice. Its verified delivery binds a continuation turn to the
same task/cycle while retaining the original assignment receipt. Collection uses
that recorded continuation, never an arbitrary latest turn. Earlier-cycle
dependencies cannot resume a newer assignment.

Partial dependency notices still concern only their named portion, without
waiting for the producer's whole assignment to end.
Whole-assignment notices require native terminal readiness. Failure, cancellation
and missing result submission remain distinct. Duplicate events, reconnects or
earlier task cycles do not repeat a confirmed notice or integration. Delivery to
an active recipient is retained until idle. Uncertain sends
are reconciled without automatic replay; no backend-wide exactly-once guarantee
is inferred from local deduplication.

One project/backend observer shares scoped command connections, with a default
24-hour observation lease and 60-second idle exit after requests and registered
work end. It starts no App Server and makes no model polling requests. It makes one reconnect
attempt before leaving an exact explicit recovery step. Unsupported or expired
observation keeps the task available for the next requested operation.
Exact covered lifecycle events trigger completion reconciliation; progress
output does not. Uncovered threads use changed-only filesystem fallback, at most
one reconciliation per five seconds per target. Status reports native RPC and
local IPC activity separately; reading status does not keep the owner alive.
The table updates after completion and dependency changes. Follow-up displays its
current goal while retaining the original goal and history. Self-dependency is
rejected; cycle warnings are advisory and do not modify the graph.

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
Transition plans bind their reviewed basis. A changed basis needs a fresh plan;
waiting and independent bindings remain visible rather than being replaced.

## Recovery and evidence

Retained action state binds actual task/chat IDs and result references. Native
rejection and lost replies remain distinct. Reconcile an uncertain send with
actual history before retry; recover the affected action while preserving others.

Local fixtures exercise failure/cancellation, duplicates, renaming, Plan
fallback, archive/restore and preserved files. Actual model behavior, visible UI,
completion arrival and integration require evidence at their respective boundary.
See [sessions](sessions.md), [validation](validation.md) and [CHANGELOG](CHANGELOG.md).
