# Release notes

These notes describe changes to harness behavior, compatibility and required
migrations. Maintenance revisions without an adopter-facing change are omitted.
The [upgrade index](upgrade-index.json) supports predecessor checks; actual file
differences and local conflicts still determine the complete upgrade plan.

## 2.1.0

Initialization distinguishes an unassigned same-root role chat from a foreign
project or root conflict. Read-only plans record missing project links;
initialization applies journaled metadata-only repairs and verifies actual
membership and preserved settings before reusing the role. Lost replies retain
the existing chat and recovery receipt without repeating the update.

Desktop membership is read from the application's stored chat inventory.
Desktop and App Server use their own project IDs and are verified separately.
Unknown membership or an unsupported metadata interface returns a concrete
recovery instruction. Apply an inspected ordinary upgrade; existing roles,
settings and work remain preserved. Core remains 2.0.0.

## 2.0.13

Desktop assignment readback accepts the native complete-text output envelope,
and waits for the new chat's first saved settings record within its existing
native deadline. Scoped file events trigger the recheck. Truncated inputs and
actual settings mismatches remain unverified; a timeout retains the created ID
without replay. Apply an inspected ordinary upgrade and recover retained tasks
by their existing Camel ID.

## 2.0.11

Fresh installation and ordinary upgrades include the Desktop task adapter and
its native pipe transport.

## 2.0.9

Desktop Camel assignment creates the chat and delivers its initial task through
the application's native tools, keeping the chat available for owner steering.
Follow-up, terminal notices and archive/restore retain the same actual chat IDs.
Uncertain creation or delivery is recovered without automatic replay.

Cameleer dispatches compact goals and constraints first, targeting accepted
delivery within one minute without a separate readiness turn. The native I/O
budget is 30 seconds; host availability and model preparation remain separate.
Apply an inspected ordinary upgrade to installed projects. Existing chats owned
by an external host keep their current work and ownership. Unsupported custom
permission inheritance fails before creation; native Plan uses one manual step.

## 2.0.8

Upgrade summaries show changes affecting the installed harness. Maintenance-only
revisions no longer add release descriptions to those summaries. Complete file
comparison and conflict review remain part of every upgrade. Core remains 2.0.0.

Source publication preserves the reviewed PR description without appending
operational metadata.

## 2.0.1

First-install initialization can connect through the default control-socket
proxy using the WebSocket protocol expected by a compatible running host. The
previous protocol mismatch could leave initialization pending. Explicit loopback
URLs and socket selection retain their existing meanings.

Apply an inspected ordinary upgrade and resume any retained initialization
operation. Reconcile an uncertain native outcome before creating another role.
A missing or incompatible host endpoint still requires its actual prerequisite.

## 2.0.0

Optional schema-2 JUnit receipts support read-only `check review`, concise
summaries and declared product, experience and protected change boundaries.
Diagnostics identify changed fingerprint fields and environment key names
without exposing values. The strict environment profile retains role identity;
explicit `role-neutral` removes only the documented role and transport keys.
Existing schema-1 receipts keep their strict behavior.

Camel can attach receipts through `complete --check-receipt`; sufficient manual
evidence remains valid. Successful collection retains exact task, cycle and result
proof. Repeated collection reuses it; follow-up preserves the original receipt
in task history.

Successful assign, complete and collect output is more concise and presents
collection proof before large evidence arrays. Python APIs, `--full`, saved state
and recovery diagnostics retain complete information. Invalid change declarations
fail before expensive fingerprinting.

Apply an inspected ordinary three-way upgrade, preserving project settings,
knowledge, user skills, unfinished tasks and historical links. Saved prompts and
receipts remain valid. The role contract remains Core 2.0.0.

## 1.2.9

Whole-assignment waits to the assigning Cameleer reuse the existing task, cycle
and result notice. Collection and archival require no separate dependency-finish
or confirmation turn. Partial waits, other consumers, terminal failures,
cancellation and new cycles retain their own scope.

Optional `check run` and `check reuse` commands record JUnit case outcomes and
consumed inputs. Individually passed, unchanged cases from a normally finished
exit-1 run can be reused while the overall failure stays visible. Changed or
missing inputs, infrastructure failures and nonpassing cases prevent automatic
reuse. See [validation](validation.md#reusing-a-testcase-subset).

## 1.2.8

The transient observer is notified when its final issued-turn verifier releases
usage, allowing it to enter idle grace after completed work.

## 1.2.7

An issued turn on an externally loaded chat can finish through a global idle
event without a connection-specific completion event. Exact terminal identity
now releases the completed usage. Duplicate idle events are coalesced; active,
newer or unidentified work remains owned with bounded recovery diagnostics.

## 1.2.6

Pending observation without an eligible transition stays read-only, avoiding
contention with foreground completion. Actual terminal and dependency deliveries
retain their lock and fresh-state checks.

## 1.2.4

Project commands and terminal observation share a transient project/backend
connection owner. Command exit does not close a peer's connection. Creation
originators remain available for reconciling uncertain native results; request
identity and independent deadlines preserve recovery without replaying mutations.

Progress and token events do not trigger native history queries. Terminal and
needed idle transitions request fresh native state. Result submission remains
separate from actual latest-turn completion, nonempty final output and project
binding. Uncovered chats use bounded, changed-only filesystem observation.

The owner permits a short idle reuse period and ends after its observation
lease. This adds no installed service or automatic App Server startup. See
[sessions](sessions.md#workflow-observation) for operation and recovery.

## 1.2.3

Roles finish independent work and end their turn while a registered dependency
blocks progress. A named partial result can resume its consumer before the
producer finishes. Failure, cancellation, missing submissions and uncertain
delivery remain distinct.

A bounded project/backend observer delivers one retained notice after the
assigned native turn actually ends. Active recipients retain pending delivery
until idle. Confirmed same-cycle continuation preserves the original assignment;
previous-cycle dependencies cannot wake new work.

Observation connects to an existing selected backend and ends when pending
notices resolve or its lease expires. Unsupported observation leaves an explicit
resume action. Connection loss permits bounded reconciliation without replaying
an uncertain mutation. Whole-operation deadlines cover connection, RPC, event
waiting, writes and cleanup; `collect --timeout` exposes that budget.

## 1.2.2

Reused request keys compare original input fingerprints before native mutations.
Definite creation rejection and uncertain delivery have separate recovery paths.
Project/root checks cover completion and restoration, and mode changes preserve
independent roles. New transition plans reject stale starting state.

Task and skill listings offer concise summaries and inspect actual installed
skill files. Follow-ups retain the original goal while tracking current work.
Managed task rows reflect result and notice state without replacing user notes.
Assignments carry the requested location without changing native working folders.
Self-dependencies fail at input; cycles remain advisory warnings.

Collection verifies the actual completed assignment turn and nonempty final
agent output before integrating or archiving it. Pending and interrupted turns
remain resumable. Send recovery uses retained turn and item anchors, including
input added to an active turn.

Installation diff and local status commands add read-only inspection. Fifteen
unused capability descriptors leave the payload: upgrades remove unchanged
copies, preserve edited copies without management and do not recreate missing
copies. All 24 skills remain active.

## 1.2.1

All skills read applicable experience before choosing an approach and consolidate
useful lessons once before final completion. The knowledge policy preserves
existing project owners, combines duplicate advice and replaces advice only
when its actual conditions are disproved or superseded. Existing project-owned
knowledge files are preserved when upstream ownership ends.

The native client bounds standard-I/O and WebSocket RPC writes while preserving
concurrent replies and notifications. First-turn Plan uses matching verified
creation settings only when native saved settings are absent. Cold recipients
retain current model, effort and permission selections.

## 1.2.0

Core 2.0.0 assigns investigation, implementation and checks to Camel, with direct
completion to Cameleer and same-ID collection, archival and restoration. Calf is
retired; useful implementation guidance moves into Camel references. Behavioral
packets, core seals and approval/ownership ACK requirements are removed.

Planning starts from the supplied request through native Plan or one manual
mode/start instruction. All 24 bundled skill families are active after
installation. Explicit caller-owned loopback WebSocket connections support
bounded sends and close.

### Core 1 to Core 2 migration procedure

Use the inspected incoming source's `oasis.py` for audit, plan and apply. The
old installed helper still enforces the old core seal and cannot apply this
transition:

```powershell
python -B -X utf8 <incoming-source>/oasis.py doctor audit --target <project> --package <incoming-source> --output <new-audit-file>
python -B -X utf8 <incoming-source>/oasis.py doctor plan --target <project> --package <incoming-source> --output <new-plan-file>
python -B -X utf8 <incoming-source>/oasis.py install apply --plan <reviewed-plan-file>
```

Let ongoing Camel/Calf assignments finish before transition. Preserve actual
chat IDs, work locations, result links, mode, Git choices, settings, user skills
and project knowledge. The upgrade plan reports unfinished legacy work before
writes and can be prepared again after its terminal result.

Baseline Calf implementation guidance is in Camel's `references/best-practices.md`.
For project-modified Calf files, preserve exact originals as inactive migration
history and move reviewed useful notes to Camel before retirement. Ambiguous
custom content remains a conflict; retired reporting and administrative procedures
do not become active Camel rules.

Supply `--calf-migration <file>` to `install upgrade` or `doctor audit|plan` when
custom Calf content needs resolution. Schema 1 has a `files` array of `path`,
`before_sha256` and `after_base64`: the existing Calf path, its actual current
hash and reviewed useful-note UTF-8 bytes. Empty note bytes preserve the inactive
original only. The hash binds current content rather than granting authority.

Exact custom originals remain under
`.oasis/state/retired-skills/oasis-calf/<sha256>/<relative>`; useful notes go to
`.agents/skills/oasis-camel/references/calf-migration/<relative>` with a link from
best practices. Existing destination edits remain file conflicts.

Earlier chat/task records stay readable. New Calf creation returns a retirement
notice without creating a chat. Subsequent assignments use actual Camel chat IDs,
direct terminal notification and restoration of the same archived Camel.

## 1.1.3

Doctor adds predecessor-aware upgrade guidance intersected with actual changed
managed files. Skipped versions retain complete three-way review; missing,
cyclic, repeated-version or unmapped history falls back to actual byte review.

## 1.1.1

Independent specialist chats retain their identities, requested scope and
unfinished work across mode changes and unrelated role archival. Their shared
contract lives in `LocalGitWorkflow.md`.

## 1.1.0

Persistent Pioneer and Oasis modes define the project's working arrangement.
Fresh empty projects default to Pioneer; legacy projects preserve Oasis and
their existing roles. Doctor supports reviewed compatible upgrades while
preserving settings and project knowledge.
