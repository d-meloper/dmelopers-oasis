# Project experience

Useful reusable experience belongs in the relevant skill's
`references/best-practices.md` or an existing suitable reference. Update it while
working when the conditions, encountered problem, helpful method and evidence
are clear enough to guide a future decision. There is no per-task retrospective,
fixed prose form, mandatory evidence field set or empty placeholder.

Keep one source for shared experience and link it from other roles. Merge
duplicates and update stale advice when its assumptions change. Preserve unique
historical observations with a replacement link; Git retains earlier bytes.
Distinguish observed behavior, hypotheses, local fixtures, installed behavior and
live effects. A later pass does not erase a failed or deferred check.

Project knowledge and settings remain local. Raw transcripts, host paths,
account/chat IDs and operational evidence belong in `.oasis/local/`. Portable
lessons use sanitized examples and describe their limits. Requested upstream
handoffs prepare only the relevant material; knowledge does not automatically
propagate to other projects.

The initial Calf implementation guidance now lives in
`.agents/skills/oasis-camel/references/best-practices.md` (under `seed/` in source).
It transfers investigation, consumer/tool reuse, interfaces/data/encoding,
scope-selected checks and dependency recovery experience. Retired reporting,
manager creation, approval and ownership ACK procedures are omitted. Legacy
projects transfer useful locally modified Calf material before deleting the
skill and preserve old chat/task references.

## Optional structured cases

The existing `knowledge validate`, `knowledge capture` and `knowledge export`
commands handle structured cases when useful. Their input schema belongs to
those commands, not ordinary skill-reference prose. Capture keeps a local
historical case; export prepares a requested sanitized local handoff and does
not send or import it. Inspect command help for the supported fields and paths.

Schema 1 retains id, classification, problem, observed, hypotheses, evidence,
delta, conditions, impact, tests, canonical rule, change kind, status and limits.
Proof boundaries distinguish static, fixture, semantic, installed and live
evidence; not-run and unknown remain explicit. These optional records complement
the nearest current reference rather than becoming an approval or work ledger.
