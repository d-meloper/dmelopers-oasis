# Build Package experience

These are retained domain methods from the existing skill, selected only when
applicable to the actual project. The [acceptance scenarios](acceptance.md) are
evaluation inputs, not performed outcomes.

## Available inputs and tools

Installed project producer, declared target profiles, compatible pinned toolchain, writable isolated output and cache ownership. Missing platform capability is a reported prerequisite, not a fabricated command.

## Methods and recovery

Freeze actual source and intended dirty inputs before producing a candidate. Read the real producer and dependency lockfiles; prefer a complete compatible retained candidate over another build. Use project-configured commands as argument arrays, not copied donor CLI strings. Keep caches and outputs owned and isolated; a filename or successful launcher is not a completed artifact.

Verify the complete output set, versions, architecture, source/producer binding, package inventory, signatures when applicable and declared source-to-variant parity. Source, editable input, generated output, release defaults and live user data have different owners. Build once outside a clean-source lock and promote the same verified bytes. A requested store/package profile must use its actual registered identity and supported producer; do not infer another channel's capability.

On partial build preserve logs and actual outputs, identify the failed stage and retry only from a valid input boundary. Stop before upload, installation or publication unless explicitly requested. Report built bytes and their hashes separately from installed behavior.
