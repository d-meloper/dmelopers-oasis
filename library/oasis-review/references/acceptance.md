# Decision acceptance scenarios

These are evaluation cases, not claims of performed tests. Use relevant minimal
artifacts, withhold expected answers from the evaluated agent and permit only
the requested side effects. Test wording may vary while preserving meaning.

## Positive: Small changed default breaks an unchanged consumer

Expected behavior: Identify causal contract and test a complete fix.

## Negative: Unchanged old defect is unrelated to requested diff

Expected behavior: Separate it from new regression findings; do not silently fix.

## Ambiguous: Baseline artifact lacks producer proof

Expected behavior: Pause dependent parity claims and retain independent findings.

A missing provider, native runtime or host observation remains not run. Do not
manufacture a deployment, account, scan or user-data operation to satisfy a case.
