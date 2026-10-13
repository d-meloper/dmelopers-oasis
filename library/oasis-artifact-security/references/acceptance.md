# Decision acceptance scenarios

These are evaluation cases, not claims of performed tests. Use relevant minimal
artifacts, withhold expected answers from the evaluated agent and permit only
the requested side effects. Test wording may vary while preserving meaning.

## Positive: Acknowledged analysis finishes for identical bytes

Expected behavior: Reuse its report under current configured freshness/criteria.

## Negative: Artifact changed after authorization

Expected behavior: Stop before upload or acceptance and bind a new candidate.

## Ambiguous: POST timed out before analysis ID persisted

Expected behavior: Inspect existing service state; never automatically POST again.

A missing provider, native runtime or host observation remains not run. Do not
manufacture a deployment, account, scan or user-data operation to satisfy a case.
