# Support Automation experience

These are retained domain methods from the existing skill, selected only when
applicable to the actual project. The [acceptance scenarios](acceptance.md) are
evaluation inputs, not performed outcomes.

## Available inputs and tools

Exact authorized sources, execution owner, recipient, provider capabilities and existing checkpoint/outbox contract. Loading this skill creates no job or trigger.

## Methods and recovery

Keep collection, durable state and delivery roles separate. Bind the exact approved accounts/resources and least necessary permissions; configuration hashes detect drift but do not authenticate approval. Gather full pagination under an immutable cutoff, deduplicate stable IDs, bound retry/deadline/size and preserve the checkpoint if any collection is incomplete. A first activation baseline does not imply historical backfill.

Persist intent before sending and accepted outcome before checkpoint advancement. An interrupted sending state or delivery exception is uncertain: no atomic transaction spans an external mail provider and a local outbox. Do not resend automatically or clear the ledger to solve credentials. Inspect exact batch/provider/recipient evidence and obtain an operator outcome when required; absent inbox arrival does not prove non-acceptance.

Keep user content and contact data out of diagnostics; encode untrusted HTML and spreadsheet values safely. Preview must not advance checkpoints or send. Use offline adapters for fault tests, not synthetic production inquiries. Source upload, actual trigger registration, scheduled execution, provider acceptance and delivery are distinct proofs. Pause only the requested trigger and preserve unrelated automation. No perpetual Harness monitor is created.
