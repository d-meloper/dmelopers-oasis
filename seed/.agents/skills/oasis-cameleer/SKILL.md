---
name: oasis-cameleer
description: Coordinate visible Camel assignments, collect and integrate results, and carry out the project's requested delivery.
---

# Cameleer

Read the applicable [coordination experience](references/best-practices.md) before choosing an approach.

For a new actionable request, dispatch the Camel first with a compact goal,
known constraints and context references through one `workflow assign` operation.
Target accepted task delivery within 60 seconds of the owner's instruction;
report actual host/model delays without promising a hard wall-clock guarantee.
Follow the [dispatch boundary](references/best-practices.md#dispatch-before-product-investigation):
leave product investigation to Camel and continue once delivery is accepted,
without waiting for its ready reply. The owner must remain able to steer the
Camel chat. Simple work can stay here. Keep actual chat IDs and result links in
`.oasis/state/tasks.md`; `camel_A_goal` is a title convention. Collect the
terminal-ready result and inspect the requested diff and original evidence once.
Use [check review](../../../.oasis/manual/validation.md#role-check-evidence) for
submitted receipts; keep sufficient manual evidence and unknown coverage distinct.
The consumer's `summary`, `fingerprint_changes` and pinned `artifacts` explain its
decision without guessing raw receipt fields. Cite the existing summary/references
in `collect --checks` after original/code review; no separate review document or
copied case/hash/scope table is required.
Finish independent review, integration and useful experience consolidation before
`workflow collect`. Its successful `collection_receipt` binds task/cycle/result,
native final/idle and accepted archive. Cite it, release remaining writers and
give the final result when the requested work is complete. Retain the existing
recovery path for uncertain collection or changed inputs/assignments.
Restore that same Camel for follow-up. Use the project's selected Git/publication
workflow for delivery included in the request.

When only assigned results remain, follow
[dependency waiting](../../../LocalGitWorkflow.md#dependency-waiting-and-resumption):
finish independent work and end the turn until its existing assignment notice.
Do not add a whole-task dependency to yourself or a closing dependency-finish.

Before the final completion report, consolidate useful lessons from this work
once in the owning experience reference.
