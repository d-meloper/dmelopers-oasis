# Codex session adapter

The adapter implements the installed native App Server contract. See the
[official contract](https://learn.chatgpt.com/docs/app-server) and
[permissions](https://learn.chatgpt.com/docs/permissions). Experimental fields
are feature-tested; unsupported settings stop before creation. No private app
database is edited. It preserves actual saved model, reasoning, permission
profile, approval policy and reviewer, then checks cold-resume persistence.
The adapter accepts supported legacy effective policies and the current exact
disabled-policy representation only when its saved built-in profile agrees.
Unrecognized or richer current policy representations remain unsupported and
stop before creation; an absent policy never defaults to broader access.

1. Install into an existing folder and open/register it as a Codex project.
2. Inspect `session create --target <folder> --role Oasis` without `--apply`.
   The caller is `CODEX_THREAD_ID`; a forged alternate caller is rejected.
3. With the real owner's concrete request, add `--apply --authority <reference>`.
   The reference is an audit pointer, not independently verified consent.
4. The command creates metadata, names the chat, saves settings, and cold-resumes
   to check persistence. It does not call `turn/start` or send a prompt.
5. Show the actual chat to the owner. Initial role assignment, skill discovery,
   first-turn behavior and existing-chat adoption are separate verification steps.

`계획작업으로 진행해` routes an owner-assigned bundle to Camel `plan-wait`;
the shared rule is in the project's `ProjectGuide.md` under "Planning work".
Supply the waiting instruction in the initial handoff, so Camel performs no
reads or tools before acknowledging and asking the owner to enable actual Codex
Plan mode and start the conversation in that Camel. The adapter still creates
metadata only. Its CLI and the currently exposed app creation/messaging tools
have no native Plan mode setter; an authored prompt or `/plan` message is not
proof of a mode change. The owner enables the actual mode in the Camel UI, then
explicitly starts planning there. Mode selection, planning start, plan approval
and implementation start remain distinct. No global settings are changed.

Only the actual named Cameleer creates grouped Camels; only a grouped Camel
creates its Calfs. Native thread identity, project and root must agree; title
alone does not establish authority. Managed profiles require an explicit
`--lane main|test` matching the actual active checkout. The lane's switch owner
must complete the acknowledged writer boundary before creation/delivery. The
adapter never switches branches or acquires broad resource ownership.

On an interrupted creation, retain its receipt. Run `session inspect <receipt>`
to query actual matching threads. `session resume <receipt> --authority <reference>`
resumes only one reconciled existing ID; it never repeats `thread/start` after an
uncertain response. If no unique identity is found, the state remains uncertain.
An operator must inspect native evidence; deleting the receipt to retry is not
recovery. Pending receipts block competing creates in that project.

`session discovery --target <folder>` calls native `skills/list` with reload.
Compare exact paths/names against installed core and selected optional skills;
unrelated global skills may also be returned. The result deliberately does not
claim that an existing chat has adopted instructions or that the model selected
the right skill. Test positive, negative and ambiguous requests separately.

`packet <file> --send` only validates a compact English packet. It never sends
one or proves authority. Keep original language in explicit literal data.
Camel/Calf to Cameleer delivery is forbidden, including through other sessions.
Actual dispatch uses only the owner's authorized scope and a supported app tool.
