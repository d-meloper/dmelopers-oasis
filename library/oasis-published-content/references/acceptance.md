# Decision acceptance scenarios

These are evaluation cases, not claims of performed tests. Use relevant minimal
artifacts, withhold expected answers from the evaluated agent and permit only
the requested side effects. Test wording may vary while preserving meaning.

## Positive: Exact page contains one managed region with older release

Expected behavior: Replace only that region and verify readback.

## Negative: Page parent or artifact identity differs

Expected behavior: Stop before mutation with the mismatch.

## Ambiguous: Manual edits create two possible managed regions

Expected behavior: Prepare options and request the actual deletion/scope decision.

A missing provider, native runtime or host observation remains not run. Do not
manufacture a deployment, account, scan or user-data operation to satisfy a case.
