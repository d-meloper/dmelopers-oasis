# Local Git workflow

Use the project's selected unmanaged, single-main or main-test workflow, and the
[Git skill](.agents/skills/oasis-git-operations/SKILL.md) for relevant commands.
Keep existing branch, worktree and backup choices. Worktrees are useful when
isolation helps; shared work can use the current checkout.

Agree a simple scope split when edits overlap. Serialize shared stage, hooks,
commit and checkout operations, preserving other writers' staged, dirty,
untracked and ignored bytes. A whole-checkout build or export can consume files
outside its author's edit scope; coordinate that operation's input boundary.
See [implementation experience](.agents/skills/oasis-camel/references/best-practices.md)
for check-input reuse and encoding conditions.

## Dependency waiting and resumption

This rule applies to Cameleer, Camel, Pioneer, Developer and independent
specialists. When a result or shared resource blocks work, register the precise
portion, producer/consumer IDs and outcome needed to resume. Finish independently
possible work, retain its reference and end the turn. Do not keep a model turn
open to inspect status, result files or elapsed time; runtime handles observation.

An assigned Camel already has a whole-assignment completion subscription to its
Cameleer. End the waiting turn and use that notice; do not register a second
dependency on the same whole assignment or finish one after collection/archive.
`dependency-wait` from that Camel to its assigning Cameleer reuses the assignment
subscription by default (`--purpose assignment` is explicit). For a distinct
partial result or resource, use `--purpose partial`; other consumers keep their
own notices. Prior untyped dependency records keep their original meaning.

Resume once from a meaningful result, failure or cancellation notice, using its
reference and current affected inputs. A whole-assignment notice waits for the
assigned native turn to finish; a named partial result or resource release can
resume its consumer while the producer continues. Duplicate or earlier-cycle
notices do not repeat work or integration. Runtime retains a notice for an active
recipient until that recipient is idle.

Ending a waiting turn does not complete the assignment or trigger its closing
experience pass. Keep routine progress local. If observation expires or is
unsupported, leave the exact explicit resume step and end the turn instead of
creating a model retry loop.

If delivery fails or is uncertain, retain that operation and reconcile its
actual result before retrying. Recover the affected handoff without resending
unrelated messages. Native service errors and unavailable messaging remain
visible with the exact resume step.

## Independent specialist sessions

An owner-established independent specialty works on its requested scope in its
existing chat. It can coordinate overlapping files or resources with the relevant
Camel under the same simple dependency boundary. Oasis maintains the environment;
Cameleer manages coordinated work. The assignment's goal decides the work, and
the actual chat ID identifies it.

Keep independent requests, useful context and unfinished work through project
mode switches. Preserve unrelated chats when archiving managed roles. Follow-up
continues in the existing chat; planning uses
[the shared native Plan path](ProjectGuide.md#planning-work). Domain experience
belongs in the relevant project skill/reference. Source accounts and service
bindings remain with their owning project.
