# Project guide

`.oasis/project.json` records the project name, Git profile, skill inventory,
adapter bindings and `extensions.workflow.mode`. Installation uses
the unmanaged Git profile unless this project selects another workflow.

All 24 skills are installed and active in `.agents/skills`: nine role/operations
skills and fifteen domain skills. The role/operations skills are Cameleer, Camel,
Oasis maintenance, Pioneer, Skill Manager, Knowledge, Git Operations, GitHub
Publication and Harness Doctor. Domain skills cover build/package, dependency and
artifact security, distribution reputation, published content, review, support,
interfaces, assets, rendering, input timing, state, lifecycle and updates. Use the
relevant skill without a separate selection or activation step. Tools and provider
setup are separate from the skill files. Use [role guidance](.oasis/docs/identity.md)
and the relevant skill's references for the current task.

## Project modes

| Selection | Work |
|---|---|
| 개척 모드 / Pioneer (`pioneer`) | Handle the requested development or investigation directly in one Pioneer chat |
| 오아시스 모드 / Oasis (`oasis`) | Oasis maintains the harness; Cameleer assigns visible Camels that investigate, implement and check work |

A fresh empty project defaults to Pioneer; an existing program defaults to
Oasis. Git, licensing and environment preparation alone do not count as program
content. Installations without a mode retain Oasis. An explicit choice
wins and persists until the owner requests a switch; project size does not switch
modes. `프로토타입 개발` and `운영` are aliases when used as actual mode requests.

Initialization creates Pioneer, or Oasis plus Cameleer. Installation alone leaves
them ready for a task; an accompanying product request can start immediately.
The file installer does not create chats. A later switch carries useful context
to the target roles, preserves unfinished and unrelated chats, and archives the
replaced roles only after the new roles are available. Follow the
[workflow manual](.oasis/manual/workflows.md) for commands and recovery.

Pioneer works directly and may use the workers requested for its task. A request
for visible workers without a count uses one Developer chat. On
`서브에이전트로만 작업해`, Pioneer coordinates and reviews while the requested
subagents edit and check. Independent specialist assignments remain in their
existing chats across mode switches; see the
[session reference](LocalGitWorkflow.md#independent-specialist-sessions).

## Camel work and task context

Cameleer creates a Camel for a new assignment, or restores the same Camel for
follow-up. `camel_A_goal` is a title convention; actual chat IDs identify work.
In `.oasis/state/tasks.md`, keep the chat ID/link, goal, current stage/dependency,
work location/result reference and final result/check summary. Update this short
list when assigning, collecting or resuming work. Focus reads on active tasks or
the relevant entry; completed entries keep a brief result and link.

Follow the [role contract](.oasis/manual/identity.md) for direct completion,
collection, archival and corrections.
Required deployment follows this project's request and configured workflow.
Reuse passing checks while their code, tests and consumed inputs still match;
individually recorded passing cases can cover a subset even when other cases in
the same run failed. See [testcase evidence](.oasis/manual/validation.md#reusing-a-testcase-subset).
Version labels or handoffs alone do not require repeating functional checks.
Reuse unchanged source/result reads for the same purpose; inspect changed inputs
or a concrete concern and briefly state why a check is repeated in the existing
result. Independent review still examines the relevant original inputs.
Verify changed inputs and the final deliverable's actual bytes separately.
See [communication](.oasis/docs/communication.md) for concise handoffs and
[dependencies](LocalGitWorkflow.md#dependency-waiting-and-resumption) for waits.
Every role ends its turn after independent work when only such a dependency
remains. Runtime observes it without model requests; waiting is not task completion.

## Engineering knowledge

Read applicable experience before choosing an approach. Immediately before the
final completion report, consolidate useful lessons once under the existing
project knowledge owner; the [knowledge policy](.oasis/manual/knowledge.md) covers
shared sources, current applicability and scoped edits. If this project has its
own canonical policy, link to its actual file and heading here and keep it there.

Camel and Pioneer share the applicable
[implementation experience](.agents/skills/oasis-camel/references/best-practices.md).
Consult the section relevant to the affected interface, data, encoding or checks,
and the relevant domain skill when its subject is involved. Project commands,
product behavior and local knowledge stay in this project.

## Harness health and updates

Use `oasis-harness-doctor` for harness health/update requests. It compares complete
bytes from the selected upstream, preserves local settings, installed skills and
knowledge, and applies compatible owned changes through the installer. Conflicts
and unresolved material choices stay visible. Source checkouts use source Git
review. Updates preserve unfinished work, project-owned knowledge and historical task
links. Version-specific transition procedures are in the installed CHANGELOG. See the
[Doctor manual](.oasis/manual/doctor.md).

## Planning work

`계획작업으로 진행해`, `계획 작업으로 진행해`, or a clear Plan request selects
planning for the supplied task. Use a supported native
`thread/settings/update.collaborationMode` or `turn/start.collaborationMode`
interface to select actual Plan mode with the current model and reasoning
settings, then start investigating and planning from that request immediately.
The native Plan instructions apply; no extra planning-start signal is needed.
See the [official App Server documentation](https://learn.chatgpt.com/docs/app-server).

For coordinated Oasis work, assign or reuse its Camel. Pioneer and independent
specialist work use their current chat. If the available interface cannot set
actual Plan mode, give the manual instruction once: enable Plan mode in the
assigned chat and start its planning conversation. Resume planning when that
happens. Implementation follows the user's instruction. Ordinary implementation
assignments start directly.

## Fast work

`빠른 작업` / `fast work` names task pacing. On `빠른 작업으로 진행해`, apply it
to the current requested task without another confirmation. Implement promptly,
use a brief relevant check and leave a runnable verification entry point plus
exact deferred checks and resume steps. Describe limited verification accurately.
The setting ends with that task or a changed instruction and preserves project
mode. Mentioning, quoting or documenting either trigger does not invoke it.

## Command references

Invoke `python -B -X utf8 tools/oasis.py` in an installed project. Detailed
manuals remain available after separating it from the source distribution:
[installation](.oasis/manual/installation.md), [workflows](.oasis/manual/workflows.md),
[sessions](.oasis/manual/sessions.md), [Git and backup](.oasis/manual/git-backup.md),
[publication](.oasis/manual/publication.md), and
[verification boundaries](.oasis/manual/validation.md).
For learning, use [the knowledge policy](.oasis/manual/knowledge.md).
