# Oasis Harness development

A Camel assigned in `plan-wait` only gives the supplied waiting acknowledgement;
it performs no reads or tools, including the setup reads below.

Read [README.md](README.md), [development guidance](docs/development.md), and
[verification boundaries](docs/validation.md) before changing this package.
Use the source entry point `python -B -X utf8 oasis.py` from this root.

The task pacing name is `빠른 작업` (`fast work`). On `빠른 작업으로 진행해`,
apply it immediately to the current authorized task without another confirmation.
Use the shared [fast-work rule](seed/ProjectGuide.md#fast-work): implement
promptly, keep checks brief, and leave exact verification/resume steps. It
overrides normal verification depth for that task, preserving project mode and
authority. Mentioning, defining or naming it is not an invocation.

On `계획작업으로 진행해`, select the existing Camel `plan-wait` assignment
flow without another mode-choice question. Follow the shared
[planning-work rule](seed/ProjectGuide.md#planning-work): carry the request to
enable actual Codex Plan mode and start the planning conversation in that Camel,
then wait. The phrase assigns waiting, not planning or implementation start.
Documenting or quoting it does not dispatch a chat.

This is the independent Oasis Harness source of record and primary development
project; [the package literal](oasis_harness/__init__.py) owns its current version.
Protected core remains v1.0.0 (original package baseline v1.0.0),
for Windows/Codex and Python 3.11+. Keep distributed guidance product-neutral;
adopting projects own domain knowledge. `seed/` and `library/` are distribution
templates, not this root's active configuration or discovered skills.
This source keeps the existing Oasis operating responsibilities. Adopters use
[persistent project modes](docs/workflows.md); the default Pioneer is outside
the unchanged eight protected core skills and does not self-install here.

The default `oasis-harness-doctor` maintenance skill audits the selected upstream
and applies compatible owned updates after concrete review. It is separate from
the eight protected core roles/skills. Use [Doctor guidance](docs/doctor.md),
preserve local knowledge/settings, and request all unresolved material decisions.
This source checkout uses source Git review; never self-install to obtain parity.
Its owner-selected delivery target is public `d-meloper/dmelopers-oasis`
on `main`. Pin the exact remote commit and reviewed source projection; public
squash SHA differs from local producer SHA. Adopters select their own bindings.

Preserve [role and authority meaning](docs/identity.md): Oasis maintains the
harness and knowledge; Cameleer manages priorities; Camel owns a bundle; Calf
investigates, implements and verifies. Camel questions/results stay local for
manual owner relay. Plan-wait, planning and implementation authorization are
distinct. Discovery or a title does not assign a role.

Evidence-backed changes within existing skill responsibilities may proceed
within the owner's requested work. Skill creation/deletion, structural or
authority changes require owner approval. Core meaning changes also require
explicit versioning and migration. Follow [knowledge guidance](docs/knowledge.md).

Audit actual Git state and bindings before operational changes. Preserve user
settings; previous host settings, hooks, backup bindings, credentials, chats and
approvals grant no authority here. Obtain concrete owner approval for material
decisions or external writes. Upstream preparation and delivery need explicit
requests and sanitized evidence. Do not infer publication, messaging, monitoring
or service activation from maintenance.

For this assigned primary source, finish authorized edits with validation, a
scoped patch-hook commit, verified private backup and a reviewed exact public
candidate. Use the lightweight impact-selected delivery in development guidance. Public
delivery keeps PR/squash, required `oasis-source-checks` and concurrent full
anonymous readback; broad tests, restore and fresh-install demonstrations run
only when affected or explicitly requested. The approved private backup is
`d-meloper/dmelopers-oasis-harness-backup`; verify immutable IDs/account/private
state at each operation. Preserve other writers, settings and private/ignored
state. Do not directly push the producer, reconnect a public source remote, or
merge/reset it to the public SHA. Never disable protections or force history to
complete delivery. Retain uncertain operations and reconcile remote state. Use
[development guidance](docs/development.md#commit-and-synchronize). This assignment
does not authorize another project, new product work, release assets, expanded
exports or unresolved material decisions. Scans and receipts are evidence, not approval. The owner authorized routine
source-only delivery of requested ordinary edits to this fixed target without
another candidate-approval prompt. Before public writes use two independent
subagents for precision review in parallel; correct only clear, proven defects
and refresh affected checks. Unresolved material decisions still require approval.

The owner requires every source commit to increment only the package patch `Z`
in `X.Y.Z` by one. X/Y and protected core versions change only on explicit owner
request. An explicitly requested exact version reset uses command-local
`oasis.versionTarget`, with the exact literal staged, as documented in development
guidance; the next ordinary commit resumes HEAD-based patch increments.
Use the repository's `.githooks/pre-commit`; do not bypass it for routine
commits or manually advance patch from a pending working value. Its HEAD-based
increment is idempotent after a failed commit. Stage the intended scope and use
plain `git commit`; partial-path/alternate-index commits refuse before version
writes. An owner-selected new base uses a command-local `oasis.versionBase`, as
documented in [development guidance](docs/development.md#commit-version).

Keep private operational evidence in `.oasis/local/`; it is not a permanent
knowledge ledger or an approval source. Retain reusable knowledge in the closest
existing guide with evidence and limits. Use impact-selected tests by default for this source; shared/unknown Python
changes fall back to the full suite. Explicit fast work still applies to the
current task. Report deferred coverage accurately. Distinguish fixtures, catalog discovery and live
behavior.
