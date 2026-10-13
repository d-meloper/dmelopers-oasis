---
name: oasis-harness-doctor
description: Audit Oasis Harness against its selected upstream, diagnose drift or missing resources, and apply compatible updates while preserving project knowledge and owner decisions.
---

# Harness Doctor

Use for an owner-requested Oasis Harness health check or update, including `$oasis-harness-doctor` and clear requests to inspect this harness. It is a default maintenance skill, not a new role. Product bugs and arbitrary dependency upgrades stay with their own owners.

Follow [the Doctor workflow](references/workflow.md). Inspect the actual root, installation/source status, bindings and writers. Fetch the complete selected upstream into an isolated staging folder; verify repository identity and pin the exact commit. Version labels alone do not establish freshness. Do not infer the upstream or credentials from a donor's private state or old host approvals.

Diagnose differences before calling them defects. Preserve project specializations and user settings. On a normal Doctor maintenance request, apply compatible owned updates after inspecting the concrete plan; an audit-only request performs no application. Ask the owner about every unresolved material decision, including conflicts, intentional local deletions, new/removed skills, structure, authority, core migrations, source divergence and binding changes. Present exact affected files, choices and consequences together; a version or valid plan is not approval.

Use the existing transaction/recovery machinery for installed projects. Include the runtime, manuals, knowledge, default skills, inactive library and explicitly selected active skills; keep each skill's responsibility and local knowledge. For a source checkout use its selected Git workflow and preserve local commits; never self-install, reset or force-push it to make it match upstream.

Verify the exact applied bytes and required resources, then check native discovery at the authorized application boundary. Report fetched commit, real findings, applied changes, all pending owner decisions and unperformed checks. Keep raw evidence local. No automatic monitoring, upstream export, account switching or service activation follows from this skill.

Use [protected identity](../../../.oasis/docs/identity.md) and [knowledge lifecycle](../../../BestPractice/KnowledgeLifecycle.md) as relevant. [Evaluation scenarios](references/scenarios.md) distinguish fixtures from real model adoption.
