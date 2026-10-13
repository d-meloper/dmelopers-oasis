# Implementation experience

This reference carries forward the useful implementation material from the
retired `oasis-calf/SKILL.md` and its linked ProjectGuide, LocalGitWorkflow and
knowledge guidance. The original Calf bytes remain in Git history. Legacy
reporting, manager creation, approval, ownership ACK and hierarchy procedures
are not part of this implementation reference.

## Find the consuming layer

When a symptom crosses source, generated assets or installed runtime, trace the
actual caller and producer before changing the visible output. Existing project
helpers, platform/library facilities and connected tests can reveal the complete
repair point. In an investigation task, a supported explanation can be the result
without an invented patch.

Retained case K13 found source integration passing while a distribution asset
comparison failed; K14 later closed the byte mismatch without establishing visual
acceptance. K41 found live chats with discoverable skills but missing manuals.
These observations support checking the consuming path rather than assuming a
source fix reached every output. The
[migration cases](../../../../.oasis/manual/migration-lessons.md) record their limits.

## Interface and persisted-data compatibility

For API or stored-data changes, follow values through the old and new consumers:
missing, explicit clear and saved default can have different meanings. Reusing
the project reader/writer or generator avoids changing only a derived copy.
Inspect a concrete old value and a newly written value when compatibility is
affected. Consult State Integrity or Update Delivery references when
those mechanisms are involved.

Installer cases K25-K28 reproduced stale preflight, lock ownership, interrupted
apply and discarded-specialization risks in disposable fixtures. Keeping
expected-old bytes, upstream baselines and current local bytes distinct allowed
conflicts to be detected at the actual write boundary. These are file-update
mechanisms, not proof of every project's data-format compatibility.

## Windows paths and protocol encodings

For native subprocesses, hooks, receipts or line-oriented protocols on Windows,
make the encoding and native path representation explicit. K15 found inherited
Git repository variables redirecting isolated children; K16 observed MSYS paths
failing at a native PowerShell boundary; K17 observed a UTF-8 receipt decoded with
legacy defaults. Scope repository-environment cleanup to the isolated child.

K36 used byte-encoded subprocess input to avoid text-mode LF-to-CRLF changes in
Git objects and protocol transactions. K40 observed completed work followed by
CLI reporting failure on a Unicode path; ASCII-safe JSON reporting and checking
retained outputs before retry avoided doing the work twice. These cases include
local fixtures and narrow live observations, not universal host coverage.

## Checks and reproducible recovery

Choose checks for the changed contract and connected consumer. Keep the command,
required inputs and a precise resume point when coverage is deferred. Reuse
passed evidence when its actual consumed source, configuration, tool and data
still match; a different unrelated HEAD alone does not explain invalidation.
Changes to shared or unknown inputs need the applicable checks.

K18 showed benign stderr promoted into process failure; preserve exit status and
diagnostic output separately. K22 retained failed, manual and deferred product
checks alongside completed migration. K31 exercised content-addressed baseline
bytes with Git autocrlf in a real disposable repository. K13/K14 demonstrate why
source tests, output-byte checks and installed acceptance are different results.
For `빠른 작업으로 진행해`, use the
[brief-check pacing](../../../../ProjectGuide.md#fast-work) and leave exact deferred
verification rather than claiming broad coverage.

## Repeated operations and dependencies

When another task owns an overlapping input, agree the required portion rather
than waiting for its unrelated work. K24 found an export consuming the entire
checkout, including new untracked files; filename splits alone did not isolate
that consumer. Coordinate its actual input boundary and serialize shared Git
operations.

Use the [one terminal notice](../../../../LocalGitWorkflow.md#dependency-waiting-and-resumption)
when the named dependency completes, fails or is cancelled. Finish independent
work and end the turn while unchanged. K35 retained unresolved external intent
after process termination; a lost response can coexist with a completed effect.
Reconcile the affected create/send/write before retrying it, and keep duplicate
notices from repeating the same integration.

Retain new applicable experience in this reference when it helps a future
decision. Shared domain knowledge can stay in its existing source with a link;
there is no per-task retrospective.
