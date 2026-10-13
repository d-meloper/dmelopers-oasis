# State Integrity experience

These are retained domain methods from the existing skill, selected only when
applicable to the actual project. The [acceptance scenarios](acceptance.md) are
evaluation inputs, not performed outcomes.

## Available inputs and tools

Actual reader/writer implementations, persisted examples, supported compatibility boundaries and disposable test data.

## Methods and recovery

Classify defaults, user state, generated assets, caches and evidence. Locate the durable writer and trace serialized values in both directions across old/new readers. Missing, explicit clear and saved default are different; a format/version label does not guarantee compatible values. Stable user identity is independent of pixel/content equality. New material compatibility consequences outside existing approval require an owner decision with concrete value examples.

Prevent stale whole-state overwrites; acknowledge frontend-owned changes in durable readback before exit or commit. Stage complete validated mutations and enforce final serialized-byte and archive/path limits. Same-filesystem atomic replacement protects the only valid copy; check temporary and final ancestors for links/reparse points before writing.

For multi-file state separate staging, commit and cleanup. Commit catalog removal before deleting assets; report cleanup failure separately from committed success. Preserve ordering and newer state during recovery, and stop if both old/new copies changed ambiguously. Exercise interruptions around the actual commit point. Do not run tests against real user data or restore retired rollback architecture by analogy.
