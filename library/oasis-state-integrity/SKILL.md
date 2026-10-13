---
name: oasis-state-integrity
description: Preserve durable state and compatibility across readers, writers, import/reset and transactional recovery.
---

# State Integrity

Read the applicable [state experience](references/best-practices.md) before choosing an approach.
Use it for stale saves, atomic files,
multi-file commit order and ambiguous recovery.

Follow persisted values through their actual readers and durable writer,
preserving default, clear and user-state meanings. Apply complete changes through
the project's transaction boundary and test the relevant interruptions.

Before the final completion report, consolidate useful lessons from this work
once in the owning experience reference.
