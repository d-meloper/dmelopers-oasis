---
name: oasis-runtime-lifecycle
description: Diagnose native window, process and listener lifetime behavior across asynchronous effects and durable saves.
---

# Runtime Lifecycle

Read the applicable [lifecycle experience](references/best-practices.md) before choosing an approach.
Use it for immediate replies,
late registration, superseded effects and restart durability.

Trace the owning native effect through its requested, applied and acknowledged
state. Keep listeners, generations, save barriers and teardown connected to the
current lifecycle owner.

Before the final completion report, consolidate useful lessons from this work
once in the owning experience reference.
