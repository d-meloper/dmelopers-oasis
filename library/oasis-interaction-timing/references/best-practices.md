# Interaction Timing experience

These are retained domain methods from the existing skill, selected only when
applicable to the actual project. The [acceptance scenarios](acceptance.md) are
evaluation inputs, not performed outcomes.

## Available inputs and tools

Actual collection/normalization/dispatch/animation path, time model and relevant deterministic fixtures. No raw input history is required.

## Methods and recovery

Trace the event through the actual active path, not just an isolated animator. Validate semantics and epochs again after asynchronous normalization; serialize native session commands and reset only owned device state. Separate saved preferences from temporary lifecycle suspension.

Collect input independently from frame throttling and advance motion by elapsed time. Define exact timestamp endpoint behavior, fractional rounding, idle/resume and overlapping windows. Inject deterministic randomness for repeatable burst decisions. Preserve displacement and velocity when replacing pulses; discard expired state and prevent scratch vectors from aliasing saved poses or another solver.

Keep coordinate transforms and contact targets consistent with current device/layout settings. A smooth helper does not prove dispatch delivers an event exactly once without reinitializing state. Preserve bounded semantic reaction state; do not add typed text or raw key histories. Use deterministic timing/pose tests and separately report physical-input/native animation observations. Settings layout, GPU representation and asset rigging retain their own owners.
