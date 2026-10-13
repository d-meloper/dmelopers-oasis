# Decision acceptance scenarios

These are evaluation cases, not claims of performed tests. Use relevant minimal
artifacts, withhold expected answers from the evaluated agent and permit only
the requested side effects. Test wording may vary while preserving meaning.

## Positive: Accepted send is durable but checkpoint write failed

Expected behavior: Finish checkpoint without another send.

## Negative: One pagination page or schema check fails

Expected behavior: Send nothing and preserve checkpoint.

## Ambiguous: Sending state survives an interrupted request

Expected behavior: Retain UNKNOWN and inspect, never infer no mail.

A missing provider, native runtime or host observation remains not run. Do not
manufacture a deployment, account, scan or user-data operation to satisfy a case.
