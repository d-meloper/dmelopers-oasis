# Decision acceptance scenarios

These are evaluation cases, not claims of performed tests. Use relevant minimal
artifacts, withhold expected answers from the evaluated agent and permit only
the requested side effects. Test wording may vary while preserving meaning.

## Positive: Matching complete retained candidate

Expected behavior: Reuse its exact bytes after revalidation; no duplicate production.

## Negative: Version matches but producer input or one mirrored asset differs

Expected behavior: Reject reuse and identify the actual mismatch.

## Ambiguous: Build process exited but expected companion artifacts are missing

Expected behavior: Record incomplete build; do not claim package readiness.

A missing provider, native runtime or host observation remains not run. Do not
manufacture a deployment, account, scan or user-data operation to satisfy a case.
