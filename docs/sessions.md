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
2. Inspect `session create --target <folder> --role Oasis` without `--apply`
   for an authorized role request. For selected-mode initialization or switching,
   use the [workflow lifecycle](workflows.md) rather than separate unbound creates.
   The caller is `CODEX_THREAD_ID`; a forged alternate caller is rejected.
3. With the real owner's concrete request, add `--apply --authority <reference>`.
   The reference is an audit pointer, not independently verified consent.
4. The command creates metadata, names the chat, saves settings, and cold-resumes
   to check persistence. It does not call `turn/start` or send a prompt.
5. Show the actual chat to the owner. Initial role assignment, skill discovery,
   first-turn behavior and existing-chat adoption are separate verification steps.

For coordinated Oasis work, `계획작업으로 진행해` routes an owner-assigned bundle to Camel `plan-wait`;
the shared rule is in the project's `ProjectGuide.md` under "Planning work".
Supply the waiting instruction in the initial handoff, so Camel performs no
reads or tools before acknowledging and asking the owner to enable actual Codex
Plan mode and start the conversation in that Camel. The adapter still creates
metadata only. Its CLI and the currently exposed app creation/messaging tools
have no native Plan mode setter; an authored prompt or `/plan` message is not
proof of a mode change. The owner enables the actual mode in the Camel UI, then
explicitly starts planning there. Mode selection, planning start, plan approval
and implementation start remain distinct. No global settings are changed.
In Pioneer mode the same phrase stays in the current Pioneer: tool-free waiting
acknowledgement requesting actual Plan mode and planning start, with no Camel
creation. The adapter never silently toggles either chat's collaboration mode.

An owner-established independent Oasis chat instead waits in its current chat
under the single `LocalGitWorkflow.md#independent-specialist-sessions` contract.
The guide is at the installed project's root, or `seed/LocalGitWorkflow.md` in
the source distribution. An independent specialty is an actual owner assignment,
not a new adapter role or authority inferred from a title or discovery. Use
that contract for shared resource ownership, messages and application timing.
Mode transitions preserve these chats, concrete requests and unfinished work.

Only the actual named Cameleer creates grouped Camels; only a grouped Camel
creates its Calfs. Native thread identity, project and root must agree; title
alone does not establish authority. Managed profiles require an explicit
`--lane main|test` matching the actual active checkout. The lane's switch owner
must complete the acknowledged writer boundary before creation/delivery. The
adapter never switches branches or acquires broad resource ownership.

Pioneer initialization belongs to a reviewed workflow operation. An ordinary
Developer worker requires the actual initialized Pioneer binding plus the human's
worker assignment; `session create --role Developer --goal <English_goal>` does
not create a Calf or authorize a count. The assigning agent uses the owner's
count, or one for an explicit visible-worker request without a count. Native
project/root/caller identity and assignment establish ownership, not titles.
Worker result delivery remains within the explicit human messaging scope.
New worker receipts provide an `assignment_marker`. Include that exact marker
at the start of the authorized initial role prompt. A later workflow plan can
verify its native first message against the retained role/parent/authority receipt
and bind the complete actual message hash. The marker records provenance; it
does not send a prompt or grant authority. Created-but-unassigned, mismatching or
uncertain workers need reconciliation before a mode switch.

On an interrupted creation, retain its receipt. Run `session inspect <receipt>`
to query actual matching threads. `session resume <receipt> --authority <reference>`
resumes only one reconciled existing ID; it never repeats `thread/start` after an
uncertain response. If no unique identity is found, the state remains uncertain.
An operator must inspect native evidence; deleting the receipt to retry is not
recovery. Pending receipts block competing creates in that project.

Workflow receipts preserve fresh target IDs and exact prompts through partial
initialization and switches. The supported app tools deliver first role/context
prompts in the owner's language; workflow inspection verifies actual user-message
bytes, completed waiting responses, inherited saved settings and exact archival
scope. `session create` remains metadata-only. A metadata receipt's
`first_turn_verified: false` is not changed into a claim of model adoption merely
because a workflow planned a prompt. See [workflows](workflows.md) for private
journals, prompt attempt reservation and pending/resume behavior.

`session discovery --target <folder>` calls native `skills/list` with reload.
Compare exact paths/names against installed core and selected optional skills;
unrelated global skills may also be returned. The result deliberately does not
claim that an existing chat has adopted instructions or that the model selected
the right skill. Test positive, negative and ambiguous requests separately.

`packet <file> --send` only validates a compact English packet. It never sends
one or proves authority. Keep original language in explicit literal data.
Camel/Calf to Cameleer delivery is forbidden, including through other sessions.
Actual dispatch uses only the owner's authorized scope and a supported app tool.
