# Decision acceptance scenarios

These are evaluation cases, not claims of performed tests. Use relevant minimal
artifacts, withhold expected answers from the evaluated agent and permit only
the requested side effects. Test wording may vary while preserving meaning.

## Positive: Committed deletion followed by failed asset cleanup

Expected behavior: Load the committed catalog and retry only owned unreferenced cleanup.

## Negative: Omitted field is treated as an explicit clear

Expected behavior: Preserve the reader contract and reject stale overwrite.

## Ambiguous: Both recovery baseline and current collection changed

Expected behavior: Stop rather than choose by timestamp or matching members.

A missing provider, native runtime or host observation remains not run. Do not
manufacture a deployment, account, scan or user-data operation to satisfy a case.
