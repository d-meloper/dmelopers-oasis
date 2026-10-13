# Codex session adapter

The adapter uses the native App Server protocol to create visible chats,
start requested turns, set Plan mode and archive/restore actual chat IDs.
See the [official App Server contract](https://learn.chatgpt.com/docs/app-server).
The default proxy needs an existing daemon/control socket; a Desktop stdio
process does not provide that endpoint. `OASIS_APP_SERVER_SOCKET` selects an
existing control socket. An explicit process-local `OASIS_APP_SERVER_URL` can
select a caller-managed loopback `ws://127.0.0.1:PORT` endpoint. The upstream
WebSocket transport is experimental and unsupported for production. This
adapter starts no server and edits no private app data or global configuration.
An explicitly requested live trial can own a temporary foreground server and
close it after its scoped chats finish.

## Settings and creation

Inherit the caller's actual model, reasoning and supported permission settings.
Keep project settings and the selected working location. Native protocol errors
remain errors; unsupported representations are reported instead of replaced
with broader defaults. Source, project and target IDs identify where an action
runs, without title-based roles or general readiness/approval/ACK proofs.

`session create` supports Oasis, Cameleer, Camel, Pioneer and existing Developer
workers. Calf requests return a retirement notice without creating a chat.
Historical Calf receipts remain readable. Creation and resume use retained IDs
after an uncertain response; they do not blindly create a replacement.

A new thread can lack saved turn settings before its first input. Use its
verified native creation settings for that first delivery. Otherwise use the
current saved settings. Load only an actual `notLoaded` recipient, explicitly
preserving model, effort, permissions and approval routing: an override-free
resume can replace them with host defaults. Loaded chats need no resume.

Use `session discovery --target <project>` for actual native skill inventory.
All 24 distributed skills are active after installation. Shared/user skills
may also appear; inventory does not prove model selection or old-chat adoption.

## Assignment and completion

The [workflow adapter](workflows.md) connects Cameleer and Camel. Assignment
creates a Camel or restores the existing task's Camel, sends the short goal and
needed context, and updates `.oasis/state/tasks.md`. Actual IDs and result
references connect the task. `camel_A_task` is a naming convention only.

Camel directly notifies its Cameleer after implementation and relevant checks.
Cameleer reviews fulfillment, the diff and performed checks, integrates the
result, then records collection and archives the finished Camel. A later
request restores that same chat. Incomplete work remains in its Camel.

Dependencies name the blocked part and wait after independent work is finished.
The producer sends one terminal result for completion, failure or cancellation.
No progress messages, ACKs, timeout turns or repeated status queries are added.

## Actual Plan mode

A planning request uses supported
`thread/settings/update.collaborationMode` or
`turn/start.collaborationMode`, then starts the supplied planning request.
Use the inherited model/effort and
`settings.developer_instructions: null` for native mode instructions.
Current availability is determined by the installed protocol, rather than
global Codex settings or a prompt claiming to enable Plan.

When the route explicitly reports that native mode setting is unsupported,
give the manual mode/start instruction once in the same Camel. Other native
errors or ambiguous sends remain recoverable errors, not evidence of an
unsupported feature. Planning and implementation remain distinct user requests;
an implementation request introduces no extra planning wait.

## Recovery and limits

Per-action state retains assigned thread IDs, native message references and
outcomes. A lost response is reconciled with actual messages/turns before retry.
Duplicate completion cannot integrate the same result twice. Recover only the
affected action; preserve other tasks, chats and user content.

The adapter is event/action driven. It does not run a listener, polling loop,
scheduler or model wait turn. Local fixtures verify deterministic native calls
and recovery. A requested Windows native trial verified real Plan/model output,
direct completion, automatic collection/archive and same-ID restoration.
Read-only schemas, live backend effects, visual UI state and descendant archive
effects remain distinct [verification](validation.md).
