# Dependency Security experience

## Available inputs and tools

Actual dependency manifests/lockfiles, used build/runtime paths and available vulnerability/licensing tools. Network lookups need the scoped service and current primary evidence.

## Methods and recovery

Trace direct and transitive dependencies that actually execute or ship. Distinguish unused lock entries, development tooling and distributed native components. Verify provenance, integrity constraints, licenses/notices and the changed exposure path rather than treating a version label as risk proof.

Separate known affected ranges, reachable usage, mitigations and unknown evidence. Compare replacement compatibility, support and build consequences before changing a pin. Use the existing project policy and available security tools; do not introduce a universal engine count, scanner, minimum version or ecosystem requirement. Preserve original advisories and exact artifact/source identity.

Refresh generated notices through their owning generator and check distribution inclusion. Reuse still-valid exact-input evidence; a changed report hash alone is not a content review. Never weaken verification, silently accept a finding, widen credentials or upgrade unrelated dependencies to make a gate green. Report source/tool checks independently of published or installed safety.

Use the [acceptance scenarios](acceptance.md) for a relevant later evaluation;
their expected results are inputs, not performed evidence.
