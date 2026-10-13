# Project guide
`.oasis/project.json` owns project selections and adapter bindings. Its default
Git profile is unmanaged; installation itself does not initialize or alter Git.
Set the project name and select only requested capabilities. Core roles do not
create chats until the corresponding human assignment/request exists.

The eight protected core skills and default `oasis-harness-doctor` live in
`.agents/skills`. Optional families remain outside
that discovery directory until explicitly selected and activated. Inspect the
available family workflow and prerequisites before selection. Tool availability,
provider registration and actual execution are separate from skill installation.

Use [BestPractice](BestPractice/README.md) for selective durable knowledge and
[identity](.oasis/docs/identity.md) for protected decisions. Keep source/runtime,
user state, generated output, packages and public exports explicitly distinguished
in the relevant project's domain guide. Do not copy private state into defaults.

Adapters describe real project commands, readers/writers, artifact variants and
verification boundaries. They cannot override core routing or grant external
authority. Free-form config needs semantic review; structural validation is limited.

## Harness health and updates

Use `oasis-harness-doctor` on an owner-requested harness health/update task.
It compares the complete selected upstream at an exact commit with actual local
ownership, diagnoses defects/missing resources and applies compatible owned
updates. Project specializations are not automatically defects. No upstream
binding is selected by installation; obtain the actual project's repository/ref
selection before fetching. Preserve settings and local knowledge. Present every
unresolved material conflict, new/removed skill, structural or authority/core
change for the owner's decision. Core meaning changes require versioning and
migration. An audit-only request performs no application, and the source checkout
uses its Git workflow rather than self-installation.

## Planning work

When the owner says `계획작업으로 진행해`, immediately select the existing
Camel `plan-wait` assignment flow without another mode-selection question.
Recognize `계획 작업으로 진행해` and a clear request to assign a bundle for a
Plan mode conversation as the same intent. Quoting the phrase, asking what it
means or asking to add this guidance does not assign or dispatch a Camel.

Cameleer carries the actual owner-assigned bundle into one visible Camel, reusing
its existing owner for follow-up or resumption. Preserve the selected profile's
source/lane readiness and existing chat/message authorization. If no bundle is
identifiable, resolve that missing scope before creation. This trigger does not
assign Cameleer to an ordinary chat or authorize extra workers.

Deliver a self-contained `mode: plan-wait` handoff. Include the actual goal,
owner authority reference, scope, source/lane, conversation language, and an
instruction to give only the waiting acknowledgement below. Include that
instruction in the initial prompt; a waiting Camel must not read files to learn
what to do. The initial response requests the actual Codex Plan mode conversation,
without tools, reads, research, planning questions, plans, implementation or Calfs.
For a Korean owner, use:

> 계획 작업을 맡고 대기하겠습니다. 이 채팅에서 Codex 계획 모드를 켠 뒤,
> 계획 대화를 시작해 주세요.

If the current runtime already establishes Plan mode, say that the Camel is
waiting for the owner to start the planning conversation in that mode; no second
toggle is needed. Prompt wording and a handoff label do not change native Codex
mode. The current session adapter creates metadata only and the exposed app
creation/messaging tools provide no Plan mode setter. Ask the owner to enable it
in that Camel's UI (the official `/plan` command is documented where supported).
Do not send `/plan` as an agent-authored message and assume it toggled the UI,
edit saved settings or a private app database, or silently plan in Default mode.
See [official Plan mode guidance](https://developers.openai.com/blog/run-long-horizon-tasks-with-codex).

Remain waiting until the owner explicitly starts the planning conversation in
that same Camel and the actual runtime establishes Plan mode. A mode toggle
alone is not a planning-start instruction. Once started, discuss the assigned
scope and prepare the plan; plan approval still does not start implementation.
Implementation needs a separate owner instruction and a native mode that permits
it. Keep questions/results local for manual owner relay to Cameleer. Quick mode
cannot bypass these gates; it applies to implementation only when separately
authorized. No polling or recurring reminder follows from waiting.

Recognition examples for later behavioral evaluation:

| Request/state | Expected behavior |
|---|---|
| Owner assigns X with `계획작업으로 진행해` | Cameleer assigns/reuses X's Camel with `plan-wait`; Camel asks for a Plan mode conversation and waits |
| `계획작업으로 진행해` 지침을 추가해줘 | Maintain the guidance; do not create or message a Camel |
| Owner enables Plan mode without starting discussion | Keep waiting; the toggle alone starts neither planning nor implementation |
| Owner says to start planning in that Camel; runtime is Plan | Begin the planning conversation; implementation remains pending |
| Owner approves the plan or requests Quick mode while waiting | Do not infer implementation start; retain the separate owner instruction requirement |

## Quick mode

The owner selected `퀵 모드` (`Quick mode`) as the canonical name. When the owner
says `퀵 모드로 진행해`, recognize and apply this pacing immediately to the current
assigned, authorized work without another mode-selection question or confirmation.
Also recognize `퀵모드로 진행해` and `퀵 모드로 X 구현해`. Equivalent requests such
as `검토는 짧게, 빠르게 구현해`,
`검증에 오래 쓰지 말고 구현부터`, and `빠르게 검증할 수 있게 만들어` select the
same pacing when the implementation-first intent is clear. Mentioning the term,
quoting an example or asking to document/name the mode does not activate it.
Apply the mode to the current
requested task/bundle; return to normal depth when it ends or the owner changes it.

Inspect only the responsible code, immediate contracts and inputs needed to
implement the requested scope. Implement promptly in small, complete changes.
Avoid broad research, architecture reconsideration, exhaustive reviews, long
full-suite runs and extra reviewers created just for coverage. Do not spend the
time saved designing a large new verification system.

Keep the result easy to check immediately: preserve a runnable/reproducible entry
point, prepare the shortest useful command or manual action, and perform only a
brief directly relevant check when available. Leave exact remaining verification
steps, necessary inputs and a clear resume point. If even a brief check is costly
or unavailable, record that it was not run and finish in a verification-ready
state. Existing full-suite instructions are the normal-depth path; while this mode
is explicitly selected, defer them instead of blocking implementation on them.

Report what was implemented, the quick check actually performed, and the deferred
checks or observed failures. Mark the outcome as implementation complete with
limited verification or ready for quick verification, not fully verified. Do not
hide a known defect or claim an unperformed check passed. This pacing changes no
role, plan-wait, implementation permission, manual relay, user-setting protection
or external-effect authority. Keep required identity/byte checks before an
authorized external write; private source sync does not establish release readiness.

Recognition examples for later behavioral evaluation:

| Request | Expected pacing |
|---|---|
| `퀵 모드로 진행해` | Immediately apply Quick mode to the current authorized task; no confirmation loop |
| `퀵모드로 X를 구현하고 실행 명령을 남겨줘` | Implement X promptly; brief relevant check and exact remaining checks |
| `퀵 모드 지침을 설명해줘` | Explain the definition; do not start implementation or switch pacing from a mention |
| `이 부분 빨리 봐줘` | Use the assigned review scope; do not infer an implementation request or a full-suite waiver |

### Fast verification mode

`빠른 검증 모드` and `fast verification mode` remain compatibility names for
[Quick mode](#quick-mode), with the same scope and behavior. This heading retains
older guidance links; it does not define a second mode.

Installed command guides are retained in `.oasis/manual`: [installation](.oasis/manual/installation.md),
[sessions](.oasis/manual/sessions.md), [Doctor](.oasis/manual/doctor.md), [Git and backup](.oasis/manual/git-backup.md),
[publication](.oasis/manual/publication.md), and [verification limits](.oasis/manual/validation.md).
Invoke commands through `python -B -X utf8 tools/oasis.py`; these manuals remain
available after the original distribution folder is no longer present.
