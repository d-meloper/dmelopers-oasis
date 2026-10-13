---
name: oasis-update-delivery
description: Implement and diagnose update verification, cancellation and durable native handoff.
---

# Update Delivery

Trace the active updater and its channel/trust configuration, preserving durable
user edits through the actual handoff. Verify staged bytes at that boundary and
recover the affected failed or uncertain native transition.
Use [update experience](references/best-practices.md) for cancellation,
concurrent restart, helper compatibility and installed verification.
