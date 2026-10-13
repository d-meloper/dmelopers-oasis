# Decision acceptance scenarios

These are evaluation cases, not claims of performed tests. Use relevant minimal
artifacts, withhold expected answers from the evaluated agent and permit only
the requested side effects. Test wording may vary while preserving meaning.

## Positive: Verified bytes and current save acknowledgement reach handoff

Expected behavior: Launch the allowed updater once with bound operation identity.

## Negative: Cross-channel metadata or bytes change after verification

Expected behavior: Reject before handoff.

## Ambiguous: Launcher returns without successor readback

Expected behavior: Report attempted handoff, not installed success.

A missing provider, native runtime or host observation remains not run. Do not
manufacture a deployment, account, scan or user-data operation to satisfy a case.
