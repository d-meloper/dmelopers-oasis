# Project modes and task workflow

Oasis has two persistent modes: Pioneer handles requested work in one visible
chat; Oasis uses Cameleer → Camel with Oasis maintaining the harness. Calf is
retired in Core 2. All 24 skills are active after installation, including the
15 formerly optional capability families.

## Mode selection

`extensions.workflow.mode` is `pioneer` or `oasis`.
Fresh empty projects default to Pioneer; programs/scaffolds/product data default
to Oasis. Legacy valid installs without a mode retain Oasis. Project mode
persists through updates and task pacing until the owner requests a switch.

Installation initializes one Pioneer, or Oasis plus Cameleer. An install-only
request leaves roles ready for later work; a concrete assigned task can start
immediately. File installation and native initialization are distinct results.
Incomplete ownership or native creation retains the existing operation for
recovery rather than creating duplicates.

Pioneer performs implementation directly. Existing visible Developer workers
remain supported. In Oasis, Cameleer assigns and integrates; Camel investigates,
implements and checks. Independent owner-assigned chats retain their work and
locations across mode changes. See installed `LocalGitWorkflow.md` for practical
coordination, without a separate hierarchy or ownership ACK protocol.

## Assign, collect and resume

Cameleer keeps a short `.oasis/state/tasks.md` list containing actual chat IDs
and links, goal, stage, dependencies, location, results and checks. It updates
the list at assignment, collection and resume. Default queries focus on active
tasks or the requested row; completed entries retain short outcomes and links.
This is task context, without a background status collector.

Source operators use `oasis.py`; adopters use installed `tools/oasis.py`.
Use each command's `--help` for native IDs and current inputs:

| Command | Work |
|---|---|
| `workflow assign` | Create a Camel, deliver goal/context and retain its task connection. |
| `workflow complete` | Send Camel's short terminal result directly to Cameleer. |
| `workflow collect` | Record reviewed/integrated result and archive the finished Camel. |
| `workflow task-resume` | Restore the same Camel for follow-up or unfinished work. |
| `workflow tasks` | Show active work or one requested task; completed history is available explicitly. |
| `workflow dependency-wait` | Retain the named blocked part and producer/consumer IDs. |
| `workflow dependency-finish` | Send its terminal result once. |

`assign` takes the target, Cameleer ID and goal, with optional context, location,
title and request ID. `complete` takes the task ID and free-form result/checks,
with completed/failed/cancelled outcome. These are command inputs, not enforced
report phrases, JSON packet fields or title patterns.

Cameleer checks the request, relevant diff and Camel's performed checks. Rerun
checks only where integration changed inputs or a concrete concern remains.
After integration, `collect` retains the result/check summary and merged reference.
A duplicate notice is recorded without repeated integration.
Failed or incomplete work remains available for continuation.

Follow-up uses `task-resume` with the existing task ID and request.
Dependencies have one explicit condition: the blocked part ends, including a
failure or cancellation. Finish independent work, end the turn and resume from
the producer's one terminal notice. Intermediate progress and ACKs are unnecessary.

## Planning and fast work

A planning request, including `계획작업으로 진행해`, uses actual native Plan
mode and immediately starts the supplied planning task. `assign --plan` and
`task-resume --plan` use supported settings/update or turn/start mode fields.
If unsupported, give the manual mode/start instruction once. Implementation
follows the user's instruction, including `task-resume --implementation`;
normal implementation needs no plan-wait stage.

`빠른 작업으로 진행해` applies prompt implementation and brief relevant checks
to the current task without changing mode. Report deferred verification precisely.
Installed `ProjectGuide.md` holds the concise pacing conventions.

## Mode transitions

Existing `workflow status`, `plan`, `start`, `inspect` and `resume` commands
retain requested initialization/switch and recovery. Capture useful goal,
decisions, work locations, performed checks and unfinished/resume information.
Preserve actual settings and project source bytes.

Create the required target roles, deliver their context through supported native
turns and archive only the linked finished old scope. Preserve independent and
unfinished work. Native parent archive may cascade: inspect the concrete
descendant IDs before affected archival. Metadata is not evidence that a model
has adopted a role.

The persistent mode changes only after the requested transition completes.
Interrupted operations keep original target IDs and action outcomes; inspect
uncertainty before retry. Settings, Git profiles and service bindings persist.
No global configuration write or spontaneous new task follows a mode change.

## Recovery and evidence

Durable action state binds actual task/chat IDs and result references.
Explicit native errors and lost responses are distinguished; uncertain sends
remain pending until actual history resolves them. Recovery affects the
individual action, preserving completed work and preventing repeated merge.
Legacy chat/receipt records remain readable without new Calf creation.

Local fixtures exercise assigned calls, failure/cancellation, duplicate notices,
title changes, Plan fallback, archive/restore and preserved files.
Actual first-turn behavior, completion arrival and real Cameleer integration
need separate live evidence. See [sessions](sessions.md) and
[validation](validation.md).
