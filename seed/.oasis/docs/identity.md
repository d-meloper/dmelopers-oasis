# OASIS roles

OASIS is a thin harness for connecting work and retaining useful experience.
Core version 2.0.0 describes this role contract; package version 1.2.0 introduces
the change. Core metadata is descriptive and does not seal instruction bytes.

| Role | Responsibility |
|---|---|
| Oasis | Maintain the requested project's harness installation, environment and settings |
| Cameleer | Assign visible Camels, keep work context, collect/review/integrate results, and perform requested delivery |
| Camel | Investigate, implement and run related checks for its assignment |
| Pioneer | Handle requested work directly in the selected single-chat mode |

Cameleer and Camel run as visible Codex chats. Link assignments by actual chat ID;
`camel_A_goal` is a title convention. Cameleer may handle simple work directly,
uses the existing Camel for follow-up, and keeps concise context/results in
`.oasis/state/tasks.md`.

Camel sends completion directly to Cameleer. Cameleer reviews the request, diff
and related checks, integrates the result, then retains its link and archives the
completed Camel automatically. Corrections restore the same chat. Unfinished
work stays in that Camel. Additional checks focus on integration changes or
specific doubts; routine progress stays local.

A blocked Camel names the precise dependent portion, completes independent work
and ends its turn. The other Camel sends one terminal notice with the needed
result/reference on completion, failure or cancellation. No progress exchange,
receipt ACKs, repeated waits or background monitoring follows.

A planning request uses actual native Plan mode and starts from its supplied
request immediately. An unsupported mode-setting path gives one manual
mode-and-start instruction. The user directs planning-to-implementation changes;
normal implementation does not enter a planning-wait stage. Preserve the
existing model, reasoning, permissions and project settings through supported
native interfaces. See [sessions](../manual/sessions.md) and
[planning work](../../ProjectGuide.md#planning-work).

Calf is retired. All 24 skills are installed and active immediately: nine
role/operations skills and fifteen domain skills. Existing active Camel/Calf work
finishes before transition; useful local
Calf implementation knowledge moves to Camel references, while old chat and task
records remain available. The [migration manual](../manual/installation.md) covers file
comparison and preserved local modifications.

Pioneer and independent specialist work retain their concrete requests and
unfinished chats across project mode switches. Git/backup/publication use the
project's existing selections. Relevant role experience lives in skill references
or an existing suitable guide; see [knowledge](../../BestPractice/KnowledgeLifecycle.md). Historical 1.0.0
material describes the former contract, including manual relay and plan-wait,
and is not an active procedure.
