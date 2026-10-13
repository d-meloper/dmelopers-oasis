# Decision acceptance scenarios

These are evaluation cases, not claims of performed tests. Use relevant minimal
artifacts, withhold expected answers from the evaluated agent and permit only
the requested side effects. Test wording may vary while preserving meaning.

## Positive: Listener finishes registering after owner unmounts

Expected behavior: Dispose it and send no new work.

## Negative: Late initial query replaces a newer pushed state

Expected behavior: Reject the stale update.

## Ambiguous: Native command issued but readback absent

Expected behavior: Preserve uncertainty rather than claim cancellation or success.

A missing provider, native runtime or host observation remains not run. Do not
manufacture a deployment, account, scan or user-data operation to satisfy a case.
