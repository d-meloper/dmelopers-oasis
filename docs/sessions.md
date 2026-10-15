# Codex session adapter

The adapter uses native App Server to create chats, start requested
turns, set Plan mode and archive/restore actual IDs. Its
[official protocol](https://learn.chatgpt.com/docs/app-server) describes available
methods; installed availability and actual effects need their own evidence.

## Transport and RPC

The default client connects to an existing daemon/control socket through
`codex app-server proxy`. The proxy forwards bytes: the client performs the
HTTP Upgrade handshake and sends masked WebSocket frames before native RPC.
It does not send JSONL directly to the socket. `OASIS_APP_SERVER_SOCKET`
selects a socket; when absent, the CLI selects its default control socket.
A Desktop standard-I/O process alone does not provide this endpoint.
Explicit process-local `OASIS_APP_SERVER_URL`
selects an existing caller-managed loopback WebSocket endpoint, such as
`ws://127.0.0.1:PORT`. Upstream WebSocket support is experimental and unsupported
for production. The adapter owns its client connection/proxy, with bounded
close; it does not start or stop the host service or its turns.
When an existing compatible socket is available, the first initialization
needs no separate socket-configuration request. An absent or incompatible
endpoint remains an explicit failure; no server is automatically started.

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

Project-scoped commands share connections through the same transient workflow
observer. It preserves separate upstream connections for creation originators;
later calls for a known thread return to its creation connection. This retains
native lifecycle events without resuming a thread merely to observe it.
Direct `AppServer` callers retain their own connections and event contract.

The local bridge uses bounded authenticated UTF-8 JSON over a same-user Windows
named pipe, binding project/backend and owner generation. It does not deserialize
pickle. A command releases its usage lease when it ends, rather than closing an
upstream connection used by another command or registered task. Uncertain IPC
delivery never authorizes a direct-connect mutation retry. Read-only status
does not launch the owner or renew its lifetime.
For an issued turn without verified completion-event coverage, a global idle
transition triggers one bounded metadata check of its exact turn ID before
releasing usage. Duplicate idle events coalesce; a newer or active turn remains
owned. This adds no periodic history queries.

Both transports cap protocol messages at 64 MiB. The event buffer is bounded
at 256 notifications and 64 MiB in aggregate. Protocol errors or overflow end
the connection and wake pending calls with an explicit failure; already
buffered accepted responses/notifications remain available. `drain_events()`
raises its event error once, then permits buffered retrieval; `diagnostics()`
retains the `event_error` for inspection.

Proxy stderr is continuously drained into a private 64 KiB ring. Its raw
stdout queue holds at most sixteen 64 KiB chunks and applies backpressure;
the same WebSocket message/event limits apply to both connection paths.
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
completion, and submits its result. Runtime notifies Cameleer when the assigned
native turn is terminal-ready. Cameleer reviews, integrates, retains
the result and archives the finished Camel. Follow-up restores that same chat.
Successful collection binds the assigned latest turn to native `completed`
status, nonempty `agentMessage.phase=final_answer` output and an `idle` or
`notLoaded` chat. A direct completion notice or user-prompt marker alone does
not establish that boundary. Exact thread/turn lifecycle events wake a fresh
state read; scoped `fs/watch`/`fs/changed` is the fallback. See
[collection](workflows.md#assign-collect-and-resume)
for pending, failed and unverifiable results.

Dependencies name a blocked portion. After independent work, end the turn and
resume from the producer's one terminal result on completion, failure or
cancellation. Transport notifications alone are not a role workflow or task result.

## Workflow observation

Registered work uses a verified host notification path where available. Otherwise
one non-model observer per project/backend owns shared client connections and
scoped watches. It connects to the existing App Server; it does not start a host service,
install a scheduler or change global settings. `thread/read` alone does not
subscribe to events or prove that a backend supplies lifecycle notifications.

The observer binds events and delivery to actual task/thread/turn, cycle, recipient
and result identity. A submitted result remains distinct from native terminal
readiness. Failed and interrupted turns retain their own outcome; missing result
submission is visible without inventing successful output or checks. A registered
consumer dependency makes an ended waiting turn distinct from a missing result.
Its verified delivery can continue the same task/cycle on a new native turn,
retaining both the continuation identity and original assignment receipt. Partial
dependency readiness concerns its named artifact/resource, not producer shutdown.
Delivery to an active recipient is retained until the recipient is idle; an
unverified native queue is not used. Collection and review remain the role's work.

Confirmed event coverage uses exact turn completion and needed recipient-idle
transitions. Progress text, tool output and token updates do not trigger history
reads. Same-purpose concurrent reads can share a result; mutation and archival
boundaries still recheck current identity and state.
For threads without verified event coverage, filesystem alerts are coalesced:
debounce 250 ms, maximum batching delay one second and at most one state snapshot
per five seconds per changed target. No-change waiting makes no periodic history
or model requests. Initial registration and terminal-boundary checks still verify
actual native state. A fallback rate limit can extend the batching delay.

Ownership includes project/backend, generation and actual process identity.
When no request or registered work remains, the shared owner exits after 60
seconds idle; an unspecified work observation expires after 24 hours. Connection
loss permits one reconnect and reconciliation.
Unsupported observation, exhausted recovery or an expired lease retains state and
an exact explicit resume step. The next requested workflow operation can restore
observation. No unknown native send is automatically repeated, and duplicate
events or old task cycles do not authorize another notice or integration.

The whole collection budget is 30 seconds by default, including connection, RPC,
I/O and cleanup. Its optional event-wait budget cannot exceed the remaining whole
deadline. Observer waits do not hold the project's mutation lock. Watches and
owned connections are released at their owner boundary; cleanup failures remain
visible with retained recovery state. Diagnostics distinguish native RPC counts,
local IPC requests, connections and reconciliation causes without retaining
prompt/result bodies. An active owner without a compatible bridge completes its
lease; shared routing begins with a compatible owner without replacing active work.

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

Transport I/O and buffered events do not provide a managed server, approval UI
or automatic result review/integration. The scoped workflow observer supplies
terminal notification without model polling. Protocol schema,
local fixtures, live backend effects, visible UI and descendant archive effects
have separate evidence boundaries. See [validation](validation.md) and recorded
observations in [CHANGELOG](CHANGELOG.md).
