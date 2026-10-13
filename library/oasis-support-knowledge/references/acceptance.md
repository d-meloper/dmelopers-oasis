# Decision acceptance scenarios

These are evaluation cases, not claims of performed tests. Use relevant minimal
artifacts, withhold expected answers from the evaluated agent and permit only
the requested side effects. Test wording may vary while preserving meaning.

## Positive: Current consumer confirms a renamed UI action

Expected behavior: Update paired facts and source mapping with actual labels.

## Negative: Old locale key exists but no UI uses it

Expected behavior: Do not present it as a current action.

## Ambiguous: Local checks pass but live model has not been queried

Expected behavior: Report live answer evaluation NOT RUN.

A missing provider, native runtime or host observation remains not run. Do not
manufacture a deployment, account, scan or user-data operation to satisfy a case.
