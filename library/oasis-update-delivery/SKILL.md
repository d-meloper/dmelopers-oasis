---
name: oasis-update-delivery
description: Implement and diagnose update verification, cancellation and durable native handoff.
---

# Update Delivery

Read the applicable [update experience](references/best-practices.md) before choosing an approach.
Use it for cancellation,
concurrent restart, helper compatibility and installed verification.

Trace the active updater and its channel/trust configuration, preserving durable
user edits through the actual handoff. Verify staged bytes at that boundary and
recover the affected failed or uncertain native transition.

Before the final completion report, consolidate useful lessons from this work
once in the owning experience reference.
