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

When another Camel's result or overlapping edit blocks work, name the precise
portion and the terminal result needed to resume. Agree who sends that result.
Finish independently possible work, leave the dependency reference and end the
turn while it is unchanged.

The other Camel sends one notice when that portion completes, fails or is
cancelled. Include the outcome and the result/reference needed for resumption.
Keep routine progress local and end the turn after independent work. Resume
from the named terminal result. The consumer resumes
from the relevant result and current affected files. A duplicate terminal notice
does not repeat the same work or integration.

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
