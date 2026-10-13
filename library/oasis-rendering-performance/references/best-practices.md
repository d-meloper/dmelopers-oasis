# Rendering Performance experience

These are retained domain methods from the existing skill, selected only when
applicable to the actual project. The [acceptance scenarios](acceptance.md) are
evaluation inputs, not performed outcomes.

## Available inputs and tools

Actual rendering backend, relevant frozen reference/cold fixture and measurable work/resource counters; physical GPU claims require actual observations.

## Methods and recovery

Separate geometry, material, camera/crop, animation and native-window causes before changing representation. Preserve alpha, winding, UV ownership, world bounds and contact targets across supported poses. Use independent equivalence references; never refresh an oracle merely to make the implementation pass.

Include each transformed instance in bounds and dispose instance/shared resources correctly. Exercise first draw, not only settled frames. Context replacement must verify actual allocated attributes and a healthy replacement frame before disposing the old owner. Masks must not alter geometry used for fit or health proof.

Reuse previews only within an isolated serial input-free batch; reset authored pose/crop through the owning path and compare A/B/A against a cold renderer. Never reset live input history for preview speed. Gate animation work and drawing appropriately while input remains responsive. Count eliminated work: draw calls, CPU payload, GPU texels, resident memory and native utilization are different metrics. Preserve negative controls and fixed tolerances. Software fixtures cannot establish installed Windows GPU equivalence.
