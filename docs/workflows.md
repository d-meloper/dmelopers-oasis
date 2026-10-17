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

Successful CLI `assign`, `complete` and `collect` responses omit instruction
bodies and history already retained in `task_state`. IDs, phase, delivery identity,
result/check references and the exact collection receipt remain in the response.
The collection receipt is displayed first, with native final/idle/archive and
task/cycle/result proof before large evidence arrays, so bounded output can retain
the completion decision. This changes display order only, preserving all receipt values.
Use `--full` for the legacy complete row or `workflow tasks --task-id` to inspect
retained state. Python APIs still return the full row. Uncertain, failed or
changed-operation responses retain full recovery diagnostics.

| Command | Work |
|---|---|
| `workflow assign` | Create Camel with goal/context and retain its actual chat/turn IDs |
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
title and request ID. Inside Desktop it uses the inherited native tools pipe:
one create starts the initial assignment in the application's own chat, so the
owner can open it and steer the work. It does not load that chat in an external
App Server. Dispatch the compact goal, constraints and known references first;
leave product investigation and validation to Camel. Aim to finish creation and
accepted delivery within one minute, without a separate readiness turn or
unrelated preparation. The command has a 30-second I/O budget; model preparation
and application availability remain outside that bound.
Known created IDs survive readback failures. An uncertain create is never
automatically repeated. If the create response lost its ID, `task-resume
--camel-id <actual-created-chat-id>` verifies that chat's exact original input
and settings before binding it to the retained task. Existing chats owned by an external host retain their
current ownership; this path does not stop their work or change installed projects.

`complete` accepts a free-form result/check summary and
completed, failed or cancelled outcome and returns after submission. It does not
wake Cameleer before the assigned native turn is terminal-ready. Cameleer checks
the request, diff and performed checks, reusing matching consumed-input evidence
and rerunning checks affected by integration or a concrete concern. State the
reason for a repeated check in the existing result; independent review still
examines relevant original inputs. `collect` retains the result/check summary and merged reference.
Optional repeatable `complete --check-receipt` binds receipt paths/hashes and
original outcomes to this task/cycle/result, includes references in its notice
and exposes them in task status. Use the [standard consumer](validation.md#role-check-evidence)
before collection; attaching receipts does not declare that every case passed or
replace independent review. Collection checks retained artifact integrity without
rerunning tests or reconstructing missing historical inputs. Sufficient manual
summaries remain valid.
When receipts are supplied and `--checks` is omitted, completion fills that
existing summary with original counts/exit/evidence status and receipt references.
`--result` or a separate report file is optional. The consumer can cite
`check review --summary` directly in `collect --checks` after independent review;
it need not transcribe the same cases, hashes or scope into another document.
Duplicate notices do not repeat integration. Incomplete work stays available.
Finish independent review and useful experience consolidation before collection.
On success, `collection_receipt.status=collected` retains task/cycle, assignment
and terminal turn IDs (including the verified effective assignment for legacy or
dependency continuation), result key, native completed/final, idle state, accepted
archive, result and check references. Release remaining writers and use it for
the final reply when requested work is complete. This receipt is retained with
the task; no extra closeout artifact or native status query is needed. A duplicate
collection returns it without native calls or evidence rereads. A new cycle clears
the active receipt and preserves it in task history. Pending, uncertain, failed,
interrupted, changed or active work does not receive a success receipt.
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

For reused role chats, `plan` records `project_bindings` without changing native
metadata. A matching root with an explicit null membership is `unassigned`;
another assigned project or a different root remains a conflict. Missing
membership information and a missing or ambiguous registered project stop
planning. In Desktop, the plan checks its actual stored membership separately
from App Server, using each catalog's own project ID.

`start` checks both catalogs before effects and repairs only planned missing
memberships. The local binding journal records intent, previous assignment,
RPC outcome, readback and model/permission selections. Strict binding checks
still run after repair. Metadata repair starts no turn and does not resume the
current chat; reusing an existing role creates no duplicate role chat.

`binding_uncertain`, `binding_not_applied` and `binding_unsupported` keep the
same initialization receipt with recovery instructions. Resume to reconcile
actual metadata; an issued update is not replayed. A compatible App Server
must support `thread/metadata/update` with `projectId`. When that interface is
unavailable, repair through a supported existing host, verify its stored
assignment and resume. Desktop membership alone does not establish App Server
membership. A Desktop check retained in the plan requires that Desktop tools
environment during recovery.

## Recovery and evidence

Retained action state binds actual task/chat IDs and result references. Native
rejection and lost replies remain distinct. Reconcile an uncertain send with
actual history before retry; recover the affected action while preserving others.

Local fixtures exercise failure/cancellation, duplicates, renaming, Plan
fallback, archive/restore and preserved files. Actual model behavior, visible UI,
completion arrival and integration require evidence at their respective boundary.
See [sessions](sessions.md), [validation](validation.md) and [CHANGELOG](CHANGELOG.md).
