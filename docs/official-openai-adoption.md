# Official OpenAI methods

These methods follow the documented protocol and skill mechanisms. Their
availability depends on the installed host and version. They do not establish
measured speed or model-quality improvements.

| Applied method | Implementation and reason |
|---|---|
| Progressive skill loading | All 24 skills are available. Concise descriptions identify scope; short bodies read relevant experience first and consolidate it once before final completion. [Build skills](https://learn.chatgpt.com/docs/build-skills), [official prompting guidance](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra). |
| Direct role instruction input | Assignments include the installed role's native `type: skill` item. [App Server: skills](https://learn.chatgpt.com/docs/app-server#skills). |
| Native Plan instructions | Retain model/effort and use `developer_instructions: null` for built-in Plan. Unsupported routes show manual instructions once. [App Server: turns](https://learn.chatgpt.com/docs/app-server#turns). |
| Targeted read and resume | Recovery reads without loading chats. Sends resume only `notLoaded` recipients, explicitly preserving saved model, effort and permission settings. Fresh threads use matching verified creation settings when no turn record exists. Follow-ups reuse the same Camel. [App Server: threads](https://learn.chatgpt.com/docs/app-server#threads). |
| Bounded archival | Check descendant scope and each archived ID. Parent success cannot certify all descendants. [App Server: archive](https://learn.chatgpt.com/docs/app-server#archive-a-thread). |
| Fresh skill inventory | Discovery uses `skills/list` with `forceReload: true` to read updated files. [App Server: skills](https://learn.chatgpt.com/docs/app-server#skills). |
| Active-recipient input | The installed generated contract describes `turn/start` steering an active turn. Direct completion keeps one native delivery path; actual active-turn behavior needs separate evidence. [Version-specific schemas](https://learn.chatgpt.com/docs/app-server#message-schema). |
| Identified recovery | Native `clientUserMessageId`/`clientId` identify accepted messages. Retained delivery and result keys prevent blind replay and repeated integration. [Session implementation](../oasis_harness/sessions.py). |

[Sessions](sessions.md) and [workflows](workflows.md) describe supported operations.
Injected [session](../tests/test_sessions.py) and [workflow](../tests/test_workflows.py)
adapters exercise local behavior. Read-only generated schema inspection establishes
collaboration fields, message IDs, reload and active-turn input for that protocol
version. Native message IDs are reconciliation keys; no server-wide exactly-once
guarantee is assumed.

The native transport bounds writes, message size and buffered events, exposes
nonblocking notification retrieval and keeps stderr diagnostics private. It
connects to an existing supported endpoint; the explicit loopback WebSocket
route is experimental upstream. Unknown server requests receive a protocol
failure response and method diagnostic rather than an approval decision.

[Verification boundaries](validation.md) distinguish schemas, local fixtures,
live backend effects, visible UI and external operations. Historical review
dates, observations and their limits live in [CHANGELOG](CHANGELOG.md).
