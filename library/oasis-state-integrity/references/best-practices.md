# State Integrity experience

## Available inputs and tools

Actual reader/writer implementations, persisted examples, supported compatibility boundaries and disposable test data.

## Methods and recovery

Classify defaults, user state, generated assets, caches and evidence. Locate the durable writer and trace serialized values in both directions across old/new readers. Missing, explicit clear and saved default are different; a format/version label does not guarantee compatible values. Stable user identity is independent of pixel/content equality. New material compatibility consequences outside existing approval require an owner decision with concrete value examples.

Prevent stale whole-state overwrites; acknowledge frontend-owned changes in durable readback before exit or commit. Stage complete validated mutations and enforce final serialized-byte and archive/path limits. Same-filesystem atomic replacement protects the only valid copy; check temporary and final ancestors for links/reparse points before writing.

For multi-file state separate staging, commit and cleanup. Commit catalog removal before deleting assets; report cleanup failure separately from committed success. Preserve ordering and newer state during recovery, and stop if both old/new copies changed ambiguously. Exercise interruptions around the actual commit point. Use the current writer's recovery semantics and disposable data for interruption checks.

New immutable evidence needs exclusive creation: checking existence and then
atomically replacing still permits a competing writer to be overwritten. Refuse
collisions; reserve atomic replacement for intentionally mutable state and journals.

## Releasing project knowledge ownership

When an installer relinquishes canonical knowledge ownership, exclude those paths
before constructing write/delete operations and recovery journals. Releasing the
manifest entry alone is sufficient; unchanged, modified, missing and later edits
must remain project-owned. Local installer/Doctor fixtures verify these states
and a project edit after interrupted apply, so recovery cannot replace it.

Use the [evaluation inputs](acceptance.md) for a relevant later evaluation;
they contain requests and conditions, not performed evidence or expected answers.
