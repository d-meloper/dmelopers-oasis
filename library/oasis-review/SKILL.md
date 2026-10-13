---
name: oasis-review
description: Review the requested comparison and correct proven in-scope defects with relevant evidence.
---

# Review

Read the applicable [review experience](references/best-practices.md) before choosing an approach.
Use it for baseline identity,
renames, source/output parity and actual coverage limits.

Inspect the requested net diff and its connected callers, tests and consumer
behavior. Establish a causal defect before correcting the responsible layer,
then refresh the checks affected by the correction.

Before the final completion report, consolidate useful lessons from this work
once in the owning experience reference.
