---
name: oasis-runtime-lifecycle
description: Diagnose native window, process and listener lifetime behavior across asynchronous effects and durable saves.
---

# Runtime Lifecycle

Trace the owning native effect through its requested, applied and acknowledged
state. Keep listeners, generations, save barriers and teardown connected to the
current lifecycle owner.
Use [lifecycle experience](references/best-practices.md) for immediate replies,
late registration, superseded effects and restart durability.
