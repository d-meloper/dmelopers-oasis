# Knowledge lifecycle
Capture a repeatable failure, data-loss/security/compatibility risk, recurring
rework or subtle verified behavior. Separate observations from hypotheses. Bind
evidence to actual inputs/version/host and state the exercised proof boundary.
Keep secrets, personal paths, live account/chat identifiers and raw user content
outside retained portable cases. Raw private evidence stays with its local owner.

Classify generic, Windows-specific or project-specific. Compare conditions,
exceptions, authority and compatibility before consolidating. Keep one current
rule in its nearest guide and preserve unique symptom, failed approach, observed
consequence and verification limits in history. Similar wording is not equivalence.

Choose the smallest useful update: existing guidance, meaningful fixture, or
existing-skill decision guidance. Structural/core changes need owner approval.
Use positive, negative and ambiguous scenarios. Test behavior rather than merely
matching wording. Independent evaluation with withheld expected answers is useful
when authorized; do not create extra agents or external effects just for a score.

Distinguish schema/static checks, fixtures, semantic review, installed behavior,
actual catalog adoption and external effects. Missing/failed/unknown is not PASS.
A successful commit does not prove a hook ran, a backup completed or a publication
was reflected. Confirm each claimed boundary separately.

Preserve historical cases unchanged; capture a correction with a new identity.
Deprecate current advice when its assumptions change and link the replacement,
without erasing original evidence. Do not remove a compatibility rule solely to
make a current test pass. Event-driven upkeep remains inside authorized work.

Projects learn independently. On explicit owner request only, prepare a local
sanitized handoff containing problem, evidence, proposed delta, tests, conditions,
impact and limits. A hash is provenance, not semantic review. Bounded screening
cannot prove complete privacy. Sending and importing remain distinct authorized
operations; nothing automatically flows to the original kit or other projects.

## CLI case format
`knowledge validate --case <file>` checks exact fields and bounded contamination.
`knowledge capture --project <root> --case <file>` creates one immutable local
history case. It never edits current guidance or certifies adoption.
`knowledge export --project <root> --case <file> --output <new-file>
--owner-requested` prepares a local handoff only. The flag records caller intent;
it is not evidence that a human authorized an action.

Schema 1 fields: id, classification (generic/windows/project), problem, observed
(text list), hypotheses (text list), evidence (label/sha256/scope objects), delta,
conditions, impact, tests (case/outcome/boundary/evidence_sha256 objects),
canonical_rule, change_kind (knowledge/existing-skill/new-skill/delete-skill/core),
status (observed/evaluated/adopted/superseded), limits (text list), schema_version.
Test outcomes: pass/fail/not-run/unknown. Proof boundaries: static/fixture/semantic/
installed/live. Performed outcomes require a digest. Evidence paths remain private;
use non-sensitive labels. Structural cases cannot self-declare adopted status.
