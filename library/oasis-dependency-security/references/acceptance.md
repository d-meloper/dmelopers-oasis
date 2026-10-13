# Decision acceptance scenarios

These are evaluation cases, not claims of performed tests. Use relevant minimal
artifacts, withhold expected answers from the evaluated agent and permit only
the requested side effects. Test wording may vary while preserving meaning.

## Positive: Changed library is used in shipped parser

Expected behavior: Trace the reachable input and apply matching advisory/policy evidence.

## Negative: Old unused lock entry resembles an advisory

Expected behavior: Do not label shipped product vulnerable without usage evidence.

## Ambiguous: Scanner unavailable or severity disputed

Expected behavior: Retain unknown/raw findings and the missing decision; no invented PASS.

A missing provider, native runtime or host observation remains not run. Do not
manufacture a deployment, account, scan or user-data operation to satisfy a case.
