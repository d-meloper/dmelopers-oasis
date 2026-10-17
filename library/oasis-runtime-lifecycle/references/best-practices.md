# Runtime Lifecycle experience

## Available inputs and tools

Actual effect owners, lifecycle states, asynchronous transport and startup/restart/save contracts; do not assume close means hide.

## Methods and recovery

Separate requested, issued, applied and acknowledged state. A stale-response guard cannot undo an already issued native effect. Subscribe before sending work that may reply immediately, serialize shared effects, recheck intent after awaits and bind listeners/leases to the current generation. Dispose late registrations after their owner ends.

Initial queries must not overwrite newer pushed status. Startup waits for registered readiness; quit/restart uses the actual durable-state owner rather than a stale copy in another window. Parent exit, pending flags and child launch alone do not prove save durability or successor readiness. Keep development supervision distinct from packaged restart and bind process identity as the platform supports.

On Windows, a recorded parent PID can identify a later unrelated process after
PID reuse. Before stopping a process tree, authenticate every edge against parent
creation time and the operation's launch record; reject children older than the
current parent or any uncertain relationship. A child's unchanged PID and creation
time alone do not establish that relationship. Prefer a retained process handle
or owned job boundary over reconstructing ownership from a process snapshot.

Retain presentation obligations through superseded requests and distinguish intentional cancellation from new renderer failure. Saving cannot wait forever on hidden/paused rendering. Bound teardown and flush required peer acknowledgements. Use the existing diagnostic owner and avoid ordinary input/user-content telemetry. Test delayed registration, native failure and cleanup failure through the real owner; mocked effects do not establish installed/native behavior.

## Concurrent protocol dispatch

Separate a byte-forwarding proxy from its endpoint's framing protocol. A running
control socket can require HTTP Upgrade and masked WebSocket frames even when
the proxy exposes stdin/stdout; JSONL on that stream can simply time out. Verify
the endpoint handshake before declaring it missing or starting another host.
Use the same connection and a bounded metadata read to establish the boundary;
retain process/stdout/stderr ownership and deadlines through failed handshakes.

For concurrent RPCs and native notifications, dispatch in the reader by response
ID and keep events in a separate bounded FIFO. A caller waiting for one response
must not consume another call's response or a terminal event. Preserve accepted
buffers after EOF or failure; report protocol/overflow failure once to the event
reader and retain its diagnostic state.

When several commands share a retained native client, preserve its creation
originator and fan events out to bounded independent consumers. A caller's
deadline must not become the upstream connection's lifetime or expire a peer's
request. Publish endpoint readiness separately from process-running state;
otherwise a startup race silently creates duplicate direct connections.
An accepted repeated completion should return before acquiring a connection or
starting an observer. Exercise that path with the actual default factory;
injected factories can hide process-start effects.
Native callbacks can belong to the client that loaded a chat. A successful send
does not prove completion-event coverage. For an otherwise unsubscribed issued
turn, verify its exact terminal ID once after idle before releasing usage;
stale idle alone cannot release newer active work.

Matching a root in a project catalog does not establish stored chat membership.
Treat explicit null as unassigned and a missing field or inventory row as unknown.
Desktop and App Server catalogs can use different IDs for the same root; bind
each metadata repair to its own catalog, actual chat and before value. Inspect
without mutation during planning, journal the apply intent before sending, then
re-read membership and model/permission selections without resuming the chat.
An unobserved effect after a lost reply does not authorize repeating the update.

When a Desktop chat must stay steerable in its application, create and send
through that application's own tools. Loading it in an independent App Server
can acquire the writer and make the UI report that it is open elsewhere.
An unsubscribe acknowledgement does not establish immediate writer release.
For combined create-and-first-input tools, persist the actual returned chat ID
before settings/input readback; a later verification failure must not lose that
known creation. Verify exact delegation source, input and native turn identity,
including native function-output representations. Native history can wrap that
output in an object with `text` and `truncated`; accept only explicit complete
text and retain the wrapper in fixtures, rather than flattening it in the fake
transport. Truncated or incompletely described output cannot prove delivery.
An acknowledged child ID can precede its rollout and first saved settings.
Before native history reads, wait for that UUID's file and saved context in the
verified session tree. Subscribe before rereading and ignore unrelated filenames;
keep this scoped wait within the original deadline. Missing context is not a settings
mismatch. Keep a real mismatch or expired wait unverified and retain the known ID.
The same call ID does not
authorize replay after response loss. Recover a lost ID only against the retained
original input and settings, rather than a title or a new creation.

For bounded history recovery, verify whether a cursor includes its anchor and
include changes to an active turn. Reject older text matches; if paging becomes
unsupported, use strong delivery identity or retain uncertainty.

Before archiving a delivering worker, bind the assignment to its latest native
turn, completed status, retained nonempty final-phase output and idle chat.
A completion report or marker in a user prompt can arrive before that boundary.
Use a scoped change notification to wake a fresh state read, not as proof of
completion. Same-target change batches can each amplify history reads even when
unrelated-watch filtering is correct; coalesce them and cap state-query frequency
per target. A native transition on another target must not release a deferred
filesystem read early. Verified lifecycle coverage can ignore progress events;
clear resolved targets during idle grace. Reuse observation reads only within
their read phase, retaining fresh validation at the mutation boundary.
Separate result submission from terminal-ready delivery. Observation must have a
non-model owner that survives a waiting role's turn, with a finite lease/recovery
path; release listeners when that owner ends. Preserve newer work or
uncertain identity instead of archiving an arbitrary finished turn.
An assigned worker can end a turn while its registered consumer dependency is
unresolved; that is not missing result submission. Retain the dependency's
verified delivery turn as a same-task/cycle continuation, preserving the original
assignment receipt. Otherwise a valid resume looks like unrelated newer work,
and stale dependency deliveries can wake a later assignment.
Wait outside the project mutation lock. After reacquiring it, reload current
state and verify the assignment/result binding before applying review or archive
inputs; independent workers must remain able to complete during the wait.

Include actual write/flush time in the request deadline. Recheck the absolute
deadline after encoding/framing and immediately before I/O after taking the
writer lock: even an expired zero-time wait can acquire a free lock. Bound teardown.
Drain stderr continuously into a bounded private diagnostic buffer instead of
attaching it to public errors. Injected protocol and standard-I/O fixtures verify
these mechanisms; they do not establish live host, model or native UI behavior.

Give disposable protocol servers separate handshake and connection lifetimes.
An idle read timeout can close an initialized fixture during suite scheduling
and masquerade as a client protocol failure. Let the fixture's explicit shutdown
release application reads, and include an idle gap as a negative control.
Treat normal owner expiry separately from a native request failure. Release
owned handles with an independent bounded cleanup budget even after the request
deadline expires. Count native sends at the actual writer, separately from local
IPC requests and pre-send attempts; retain consumed source hashes with the run
rather than reconstructing them from later files.

Windows overlapped cancellation retains buffer/handle ownership until kernel
completion. A scoped filesystem wait must also tolerate unrelated same-directory
changes and spurious condition wakeups until its fixed deadline; returning an
empty batch early can be misread as a disconnected observer. A bounded recency
list cannot prove the absence of archive descendants. Use an exhaustive native
inventory or an exact-owner read-only persisted spawn-edge snapshot, failing
before archival on unknown schema, ambiguity or incomplete closure.

Use the [evaluation inputs](acceptance.md) for a relevant later evaluation;
they contain requests and conditions, not performed evidence or expected answers.
