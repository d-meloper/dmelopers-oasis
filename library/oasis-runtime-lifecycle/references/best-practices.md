# Runtime Lifecycle experience

These are retained domain methods from the existing skill, selected only when
applicable to the actual project. The [acceptance scenarios](acceptance.md) are
evaluation inputs, not performed outcomes.

## Available inputs and tools

Actual effect owners, lifecycle states, asynchronous transport and startup/restart/save contracts; do not assume close means hide.

## Methods and recovery

Separate requested, issued, applied and acknowledged state. A stale-response guard cannot undo an already issued native effect. Subscribe before sending work that may reply immediately, serialize shared effects, recheck intent after awaits and bind listeners/leases to the current generation. Dispose late registrations after their owner ends.

Initial queries must not overwrite newer pushed status. Startup waits for registered readiness; quit/restart uses the actual durable-state owner rather than a stale copy in another window. Parent exit, pending flags and child launch alone do not prove save durability or successor readiness. Keep development supervision distinct from packaged restart and bind process identity as the platform supports.

Retain presentation obligations through superseded requests and distinguish intentional cancellation from new renderer failure. Saving cannot wait forever on hidden/paused rendering. Bound teardown and flush required peer acknowledgements. Use the existing diagnostic owner and avoid ordinary input/user-content telemetry. Test delayed registration, native failure and cleanup failure through the real owner; mocked effects do not establish installed/native behavior.
