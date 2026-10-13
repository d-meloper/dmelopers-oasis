# Project guide

`.oasis/project.json` owns project selections and adapter bindings. Its default
Git profile is unmanaged; installation itself does not initialize or alter Git.
Set the project name and select only requested capabilities. Keep the exact
schema; project mode is `extensions.workflow.mode`, either `pioneer` or `oasis`.

The eight protected core skills, `oasis-harness-doctor` and `oasis-pioneer` live
in `.agents/skills`: ten defaults. Optional families remain outside that discovery
directory until explicitly selected and activated. Inspect the relevant family
workflow and prerequisites before selection. Tool availability, provider
registration and actual execution are separate from skill installation.

Use [BestPractice](BestPractice/README.md) for selective durable knowledge and
[identity](.oasis/docs/identity.md) for protected decisions. Adopting projects own
their product knowledge, commands and settings. Keep source/runtime, user state,
generated output, packages and public exports distinguished in their closest
project guide. Adapters cannot override core routing or grant external authority.

## Project modes

| Selection | Goal and visible owners |
|---|---|
| 개척 모드 / Pioneer (`pioneer`) | Develop or investigate the owner's requested scope promptly in one Pioneer chat |
| 오아시스 모드 / Oasis (`oasis`) | Use the existing Oasis, Cameleer, Camel and Calf responsibilities and rules |

A fresh empty project starts in Pioneer. Git, a license, guidance and development
environment preparation alone do not make it an existing program; application
source, a code-bearing scaffold, inline application code in setup configuration
or product data do. Ambiguous/malformed package configuration stays visible for
review under the conservative Oasis default. A fresh existing program
starts in Oasis. A partial installation needs ownership/recovery review. An
already installed configuration without a mode resolves to Oasis and an update
does not create chats or change that selection. An explicit initial choice wins.

The mode persists until the owner explicitly switches it. Project size never
switches it automatically and there is no temporary per-task prototype override.
Recognize an explicit switch using these names or `프로토타입 개발` / `운영`.
Definitions, quotations and requests to document the names do not switch modes.
Observed coordination or repeated-delivery needs may justify one brief switch
suggestion; do not repeat a declined suggestion for the same reason or monitor
the project in the background.

In Pioneer, use `$oasis-pioneer` and the relevant engineering knowledge below.
Handle the requested development, investigation, checks and compatible local
harness/guide upkeep directly. There is no fixed product-completion threshold;
the owner's purpose and scope decide the result. Default to solo work and short,
useful checks. An explicit visible-worker request uses ordinary Developer chats,
one when no count is given; they are not Calfs. Subagents require the owner's
requested count/scope. On `서브에이전트로만 작업해`, Pioneer coordinates, reads,
reviews and reports; delegate code edits, tests and integration edits. Keep
already authorized operations within their existing scope.

Installation authorizes initialization of the selected mode's visible owners:
Pioneer alone, or Oasis plus Cameleer. An install-only request leaves them waiting;
an installation accompanied by a concrete product task may deliver that task to
the new primary. File apply itself creates no chats. A genuine later switch uses
fresh target chats, verified inherited settings, bounded context and waiting
acknowledgements before archiving explicitly linked old owners/workers. Preserve
unrelated chats and unfinished saved work. Follow the installed
[workflow manual](.oasis/manual/workflows.md) for native evidence, failures and
resumption. A name or discovery entry never assigns a role.

In Oasis, owner-established independent specialty work follows the single
[independent specialist session contract](LocalGitWorkflow.md#independent-specialist-sessions).
It preserves the existing core roles and their reporting boundaries. Mode
transitions preserve those independent chats, concrete requests and unfinished
work. Pioneer introduces no independent specialist role.

## Engineering knowledge

Pioneer and Calf use the same relevant engineering principles while keeping
their own authority and reporting routes. Verify scope, actual source/lane and
owned files before mutation. Investigate the responsible layer and connected
callers/tests; inspect existing project capabilities, platform/library facilities
and installed tools before adding code. Choose a complete architectural fit.
An investigation-only request or uncertain cause does not require an invented
change. Preserve public interfaces, persisted meanings, encodings and
authorization. Select checks matching the changed behavior and requested pace;
ordinary work does not imply builds, scans or publication. Coordinate overlapping
files/resources and serialize Git ownership. Retain failures, deferred checks
and an exact resume point. Read applicable project/BestPractice knowledge and
optional skill resources selectively; consulting them does not activate a skill
or assign another role. Do not load every guide for a small task.

## Harness health and updates

Use `oasis-harness-doctor` on an owner-requested harness health/update task.
It compares the complete selected upstream at an exact commit with actual local
ownership, diagnoses defects/missing resources and applies compatible owned
updates. Project specializations are not automatically defects. Obtain the
actual project's upstream selection before fetching. Preserve mode, settings,
capabilities and local knowledge; no update initializes or switches role chats.
Present every unresolved material conflict, new/removed skill, structural or
authority/core change for the owner. Core meaning changes require versioning and
migration. Audit-only requests do not apply. Source checkouts use their own Git
workflow rather than self-installation.

## Planning work

On `계획작업으로 진행해`, select the mode's waiting flow without another choice
question. Recognize `계획 작업으로 진행해` and a clear request for a Plan mode
conversation as the same intent. Mentioning or documenting the trigger does not
dispatch a chat or start planning.

In Pioneer, stay in the same Pioneer chat. An owner-established independent
Oasis chat also stays in that same chat under the
[independent session contract](LocalGitWorkflow.md#independent-specialist-sessions).
Give only the waiting acknowledgement below, without tools, reads, research,
planning questions, plans or workers. Create no Camel for either case. Ordinary
coordinated Oasis work preserves the existing Camel `plan-wait` assignment:
Cameleer carries the actual bundle into its visible Camel, reusing that bundle's
owner for follow-up/resumption. Preserve the selected source/lane readiness and
existing messaging authorization. Resolve missing bundle scope before creation.

For a coordinated Oasis handoff, include the goal, owner authority reference, scope,
source/lane, conversation language and the self-contained waiting instruction
in the initial `mode: plan-wait` prompt. A waiting Camel cannot read guidance to
learn its first response. For a Korean owner, the assigned waiting chat says:

> 계획 작업을 맡고 대기하겠습니다. 이 채팅에서 Codex 계획 모드를 켠 뒤,
> 계획 대화를 시작해 주세요.

If the runtime already establishes Plan mode, ask only for the planning
conversation to start. Prompt labels do not change native Codex mode. The session
adapter creates metadata only and currently exposed creation/messaging tools
have no Plan mode setter. The owner enables actual Plan mode in that chat's UI
(the official `/plan` command is documented where supported). Do not send an
agent-authored `/plan` and assume a toggle, alter saved settings/private app data,
or silently plan in Default mode. See
[official Plan mode guidance](https://developers.openai.com/blog/run-long-horizon-tasks-with-codex).

Wait until the owner starts planning in that same chat and the actual runtime
establishes Plan mode. A toggle alone starts no planning. Plan approval starts
no implementation; require a separate implementation instruction and a native
mode that permits it. Camel questions/results stay local for manual owner relay
to Cameleer. Fast work changes none of these gates. No polling or recurring
reminder follows from waiting.

## Fast work

`빠른 작업` / `fast work` is the named task pacing option. On
`빠른 작업으로 진행해` or `fast work` requested for the current authorized work, apply it
immediately without another confirmation. It ends with that task or the owner's
changed instruction; it does not change project mode, role or authority. A
definition, quotation or naming request does not invoke it. Generic requests to
look quickly retain their actual review/implementation scope and do not alone
select a named full-suite waiver.

Inspect the responsible code, immediate contracts and inputs needed for the
scope, then implement promptly in small complete changes. Keep review/checks
brief and relevant. Defer broad research, architecture reconsideration, full
suites and extra reviewers created only for coverage. Preserve a reproducible
entry point, perform the shortest useful check when practical, and leave exact
deferred commands/actions, inputs and resume steps. If no brief check is
practical, record it as not run. Do not replace the saved time with a large new
verification system.

Report the implemented scope, performed check, failures and deferred coverage.
Describe limited verification accurately; do not claim an unperformed check
passed. Keep required identity/byte checks before an authorized external write,
implementation permission, manual relay and user-setting protection. Pioneer's
ordinary short checks and explicitly selected fast work are separate choices.

Installed command guides live in `.oasis/manual`: [installation](.oasis/manual/installation.md),
[workflows](.oasis/manual/workflows.md), [sessions](.oasis/manual/sessions.md),
[Doctor](.oasis/manual/doctor.md), [Git and backup](.oasis/manual/git-backup.md),
[publication](.oasis/manual/publication.md) and [verification limits](.oasis/manual/validation.md).
Invoke `python -B -X utf8 tools/oasis.py`; these manuals remain available without
the original distribution folder.
