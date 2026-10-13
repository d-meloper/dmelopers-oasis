# Official OpenAI methods adopted

Official information reviewed on 2026-10-13 informed these Package 1.2.0 changes.
The benefits below follow documented mechanisms; they are not measured live
speed or model-quality claims.

| Applied method | Implementation and reason |
|---|---|
| Progressive skill loading | All 24 skills are available immediately. Concise descriptions identify their scope; short bodies link relevant experience. This reduces unnecessary instruction loading and catalog truncation. [Build skills](https://learn.chatgpt.com/docs/build-skills), [official prompting guidance](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra). |
| Direct role instruction input | Assignments include the installed role's native `type: skill` item, avoiding name-only lookup. [App Server: skills](https://learn.chatgpt.com/docs/app-server#skills). |
| Native Plan instructions | Retain model/effort and use `developer_instructions: null` for built-in Plan. Unsupported routes show manual instructions once. [App Server: turns](https://learn.chatgpt.com/docs/app-server#turns). |
| Targeted read and resume | Recovery reads without loading chats. Sends resume only `notLoaded` recipients, explicitly preserving saved model, effort and permission settings; fresh threads use verified creation settings when no turn record exists. Live inspection found an override-free resume applied host defaults. Follow-ups reuse the same Camel. [App Server: threads](https://learn.chatgpt.com/docs/app-server#threads). |
| Bounded archival | Check descendant scope and each archived ID. Parent success cannot certify all descendants. [App Server: archive](https://learn.chatgpt.com/docs/app-server#archive-a-thread). |
| Fresh skill inventory | Discovery uses `skills/list` with `forceReload: true` to read updated files without a watcher. [App Server: skills](https://learn.chatgpt.com/docs/app-server#skills). |
| Active-recipient input | The current generated contract describes `turn/start` steering an active turn. Direct completion therefore keeps one native delivery path. [Version-specific schemas](https://learn.chatgpt.com/docs/app-server#message-schema). |
| Identified recovery | Native `clientUserMessageId`/`clientId` identify accepted messages; retained delivery and result keys prevent blind replay and repeated integration. [Session implementation](../oasis_harness/sessions.py). |

[Sessions](../oasis_harness/sessions.py) and
[workflows](../oasis_harness/workflows.py) implement the native operations.
Verification uses injected adapters in [session tests](../tests/test_sessions.py)
and [workflow tests](../tests/test_workflows.py), plus read-only generated schema
inspection for collaboration fields, message IDs, reload and active-turn input.
The schema-backed rows describe this installed protocol version, not every host.
See [verification boundaries](validation.md) for actual runs and live limits.

Native message IDs are reconciliation keys. Oasis journals and collected-result
keys prevent blind replay and repeated integration; no server-wide exactly-once
guarantee is assumed. A separately requested Windows native trial verified Plan
output with the installed role input, direct completion, model-driven collection,
archive and same-ID restoration. It also exposed the fresh-settings and cold
resume defects corrected above. Visual toolbar state, active-turn steering and
descendant archive effects remain unverified. The harness starts no diagnostic
turn, server or background monitor automatically and changes no global settings.
