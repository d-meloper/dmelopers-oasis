# Asset Pipeline experience

## Available inputs and tools

Available authoring tool, original asset, actual consumer rig/axis/texture contract and output ownership. Tool-guided execution is supported; no generic autorig executable is bundled.

## Methods and recovery

Preserve untouched input, editable source, review export and consumer asset separately. Inspect real mesh/armature/weights/textures: a visible pose proves none of them. Identify units, axes, primary meshes and supported motion before changing the asset. Resolve ambiguous multiple subjects or incompatible pose rather than inventing missing geometry.

Fix rigging/segmentation in the asset authority instead of runtime stretching or filler. Select rigid component versus smooth boundary weights from actual topology; disconnected voxel surfaces and rounded multi-patch surfaces need different treatment. Use full normalized bounds, not only component centers or copied absolute thresholds. Diagnose stranded pieces by which bone they actually follow. Do not impose a donor skeleton, static legs, clip prohibition or armless markers without consumer need.

For generated assets edit the owning generator, not only outputs. Validate normals/winding/UVs, required bones, normalized weights and deformation under independent joints and supported poses. Preserve source/preview/installed resource hashes and force the real packaging stage when resource paths change; hot reload may retain stale assets. A bind-pose image or matching bone names is insufficient. Re-run the reproduced motion failure before retaining a general lesson.

Use the [acceptance scenarios](acceptance.md) for a relevant later evaluation;
their expected results are inputs, not performed evidence.
