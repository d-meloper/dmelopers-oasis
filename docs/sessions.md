# Codex session adapter

The adapter uses native App Server to create chats, start requested
turns, set Plan mode and archive/restore actual IDs. Its
[official protocol](https://learn.chatgpt.com/docs/app-server) describes available
methods; installed availability and actual effects need their own evidence.

## Transport and RPC

The default proxy connects to an existing daemon/control socket.
`OASIS_APP_SERVER_SOCKET` selects that socket. A Desktop standard-I/O process
does not provide this endpoint. Explicit process-local `OASIS_APP_SERVER_URL`
selects an existing caller-managed loopback WebSocket endpoint, such as
`ws://127.0.0.1:PORT`. Upstream WebSocket support is experimental and unsupported
for production. The adapter owns its client connection/proxy, with bounded
close; it does not start or stop the host service or its turns.

`AppServer` retains its `call`, `pages`, `close` and context-manager interface.
RPC IDs dispatch responses to pending calls; request deadlines include writes
for standard-I/O and WebSocket. Native notifications enter a separate FIFO.
`drain_events()` returns buffered notification dictionaries without waiting.
It does not interpret task completion, poll a model or automatically collect work.

The public `AppServer` defaults to all notifications. `command_server` opts out
of the five unused text/output deltas: agent-message, reasoning summary/text,
command output and file-change output. It retains lifecycle events and requests.
Only an explicit unsupported opt-out parameter permits one initialization retry
without that parameter; other errors keep their original failure boundary.

Both transports cap protocol messages at 64 MiB. The event buffer is bounded
at 256 notifications and 64 MiB in aggregate. Protocol errors or overflow end
the connection and wake pending calls with an explicit failure; already
buffered accepted responses/notifications remain available. `drain_events()`
raises its event error once, then permits buffered retrieval; `diagnostics()`
retains the `event_error` for inspection.

Standard-I/O stderr is continuously drained into a private 64 KiB ring.
`diagnostics()` exposes backend/state, unsupported-method information and private
`stderr_tail`. Raw stderr is not appended automatically to public errors or logs.
Keep those diagnostics in local evidence. Unsupported server requests receive
`-32601` and a diagnostic method name; this dispatcher supplies no automatic
approval decision or native approval UI.

## Settings and creation

Inherit the caller's actual model, reasoning and supported permission settings.
Keep project settings and work location. Unsupported or contradictory settings
remain errors instead of receiving broader defaults.

`session create` supports Oasis, Cameleer, Camel, Pioneer and Developer workers.
Creation and resume reconcile retained IDs after uncertain replies.
A fresh thread may lack saved turn settings; use matching verified native
creation settings only for that first input. Otherwise use current saved
settings. Resume only a `notLoaded` recipient and explicitly preserve model,
effort, permissions and approval routing. Loaded chats need no resume.
Known validation, unsupported-method and overload creation rejections retain a
retryable rejected operation. Unknown or lost outcomes retain uncertainty; they
do not authorize another create.

`session discovery --target <project>` reads actual native skill inventory.
All 24 distributed skills are active; shared/user skills may also appear.
Inspect actual source paths, enabled state, duplicate names and host warnings.
All bundled files being available does not prove every description fits the
host's metadata budget or was selected. Inventory does not establish model use.

## Assignment and completion

The [workflow adapter](workflows.md) creates or restores Camel, delivers its goal
and relevant context, and updates `.oasis/state/tasks.md`. Actual IDs and result
references connect work; `camel_A_task` is a naming convention.

Camel implements and checks its assignment, consolidates useful experience before
completion, and directly notifies Cameleer. Cameleer reviews, integrates, retains
the result and archives the finished Camel. Follow-up restores that same chat.
Successful collection binds the assigned latest turn to native `completed`
status, nonempty `agentMessage.phase=final_answer` output and an `idle` or
`notLoaded` chat. A direct completion notice or user-prompt marker alone does
not establish that boundary. A scoped `fs/watch`/`fs/changed` wait can observe
rollout changes during collection; fresh native reads determine the outcome.
The call removes its watch before returning. See [collection](workflows.md#assign-collect-and-resume)
for pending, failed and unverifiable results.

Dependencies name a blocked portion. After independent work, end the turn and
resume from the producer's one terminal result on completion, failure or
cancellation. Transport notifications alone are not a role workflow or task result.

## Actual Plan mode

Use supported `thread/settings/update.collaborationMode` or
`turn/start.collaborationMode` and start the supplied planning request.
Retain model/effort and `settings.developer_instructions: null` for native
mode instructions. Global settings and prompt wording do not establish mode.

When native mode setting is explicitly unsupported, give manual mode/start
guidance once in the same chat. Other errors and ambiguous sends retain their
recovery boundary. Implementation follows the user's instruction.

## Recovery and limits

Action state retains thread IDs, native message references and outcomes.
Reconcile lost replies with actual history before retrying; duplicate completion
must not repeat integration. Recover only the affected operation.
Sends bind actual thread/root/project identity. Receipts may hold a latest-turn/item
anchor or a full baseline. Recovery reads newer turns/items; unsupported paging
falls back within the retained evidence boundary, preserving each receipt's form.
Weak text matches outside the retained boundary remain uncertain, with no replay.

Transport I/O and buffered events do not provide a managed server, cross-process
lease/IPC bridge, automatic terminal collection or model polling. Protocol schema,
local fixtures, live backend effects, visible UI and descendant archive effects
have separate evidence boundaries. See [validation](validation.md) and recorded
observations in [CHANGELOG](CHANGELOG.md).
