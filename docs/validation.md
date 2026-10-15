# Verification boundaries

Run local tests from the source root:

```powershell
python -B -X utf8 -m unittest discover -s tests -t . -v
```

Tests use disposable filesystem/Git projects and injected native/service adapters.
They verify the exercised functions; live chat adoption and remote effects need
their own evidence. Select affected modules for ordinary changes; shared or
unknown Python uses the full suite when passing evidence does not cover the same
inputs. Reuse passed checks with matching code, tests, configuration and other
consumed inputs. Compare the inputs actually consumed, using their retained
fingerprint where available; missing proof remains unknown. Version/documentation
changes alone do not invalidate unaffected functional checks. State a rerun's
changed input or concrete concern in the existing check/result summary, without
a new required form. Independent review still inspects relevant original inputs.
Reuse unchanged source/result reads for the same purpose instead of repeatedly
loading full histories; inspect affected ranges when the inputs or purpose change.

Run checks for changed inputs and retain failed, missing or deferred coverage.
Exact final export, privacy and identity checks still apply to the candidate.
Source delivery accepts a retained verified build receipt explicitly; a bare
log or failed run cannot become a pass.

## Reusing a testcase subset

Passing cases from a normally completed test run remain usable when other cases
failed. Cite the original receipt and exact testcase IDs; keep its overall exit
status and all nonpassing cases visible. A changed input, new verification purpose
or concrete doubt still needs a new check. Independent review remains separate.

For optional machine-checked reuse, `check run` wraps an explicitly selected
JUnit-producing command without installing a runner or modifying its settings:

```powershell
python -B -X utf8 oasis.py check run --root <project> --input src --input tests --input pyproject.toml --runtime-input <consumed-runtime-and-dependency-directory> -- python -m pytest '--junitxml={report}'
python -B -X utf8 oasis.py check reuse --receipt <recorded-receipt.json> --case 'module.Class::test_name'
```

Declare the complete consumed source/test/configuration and external
dependency/runtime files or directories. Repeat `--input`/`--runtime-input` as
needed; without inputs the project directory is inventoried. Hashes are taken
before and after execution and checked again at reuse, together with the actual
runner executable, command, cwd, host runtime and inherited environment. Raw
environment values are not stored. Generated reports/logs use unique private
`.oasis/local/checks/` runs. `--purpose` distinguishes a new verification purpose.

`check reuse` only reads evidence and returns `reusable` or `needs_check` with
reasons; it executes no test or automatic retry. Missing dependency/runtime scope,
changed inputs, infrastructure errors, abnormal exits, skipped/missing/failed or
ambiguous cases prevent automatic reuse. Test exit 1 remains failure; its individually
passed cases may be cited. A raw old report cannot acquire a retrospective
fingerprint. This optional subset evidence never replaces a verified build
receipt or a required publication status and introduces no completion gate.
Keep this optional boundary proportional to the check: hashing an entire runtime
directory can cost more than a tiny subset. Prefer citing already sufficient
case evidence; a broad new fingerprint pass is not a required closing routine.

## Role check evidence

Choose the standard producer from the first JUnit-producing baseline, or cite
already sufficient manual evidence. No runner installation is needed. For example:

```powershell
python -B -X utf8 tools/oasis.py check run --root . --input src --input tests --input pyproject.toml --runtime-input <consumed-runtime-and-dependencies> --environment-profile role-neutral -- python -m pytest '--junitxml={report}'
python -B -X utf8 tools/oasis.py workflow complete --target . --task-id <actual-id> --result <result-reference> --check-receipt <receipt.json>
python -B -X utf8 tools/oasis.py check review --receipt <receipt.json> --case 'module.Class::test_name'
```

Source operators use `oasis.py`. Repeat `--check-receipt` for several runs.
`check review` is the fixed consumer, also for an initial baseline: it checks
the recorded schema/artifacts and current consumed inputs without executing a
runner. Without `--case`, it considers the originally passed cases while retaining
the whole exit and every nonpassing case. Use `--purpose` when the verification
purpose changes. Missing or unsupported original proof is `unknown/needs_check`,
never a guessed `input_hashes` field or a fingerprint constructed after the run.
Schema 2 records an explicit environment profile; complete schema-1 receipts keep
their original strict behavior. Historical manual receipts may still be cited as
manual evidence; automatic unknown coverage does not erase sufficient human review.

`check review --summary` returns the decision, selected counts, original exit,
nonpassing cases, scope, purpose/profile and pinned report/log references without
copying the passed-case table. Its `summary` can be cited directly in existing
`complete/collect --checks`; independent original/code review still applies.
No separate result/review document, copied original/hash inventory or resource
table is required unless it is a requested deliverable. Use consumer output,
rather than guessing `status/artifacts/outcome` in the raw producer receipt.

`fingerprint_changes.during_run/current` distinguishes cwd, command, runner,
host runtime, source/test/config inputs, dependency/runtime inputs and environment.
New executions also retain key-by-key private environment digests; diagnostics
show added/removed/changed key names without values or credential text. Older
receipts keep their original combined environment proof: absent per-key evidence
is explicitly unknown and is never reconstructed. Align diagnosed settings in
the invoking shell only when the intended consumed environment is the same;
meaningful environment/runtime/purpose changes still require checks. No additional
environment key is excluded to make a reuse verdict pass.

The default `strict` profile retains the cleaned inherited environment, including
role identity. Explicit `role-neutral` removes only `CODEX_THREAD_ID`,
`CODEX_SESSION_ID` and `OASIS_APP_SERVER_URL` from the actual runner environment
and its fingerprint.
Choose strict when the test consumes those values. All remaining values, including
PATH and PYTHONPATH, remain hashed; raw environment values are not serialized.
The runner uses the fingerprinted executable path. Reuse applies the recorded
profile, without changing the consumer's environment or ignoring consumed inputs.

For an authorized change comparison, the first `check run` may additionally
declare repeatable `--scope-input`, `--allow-product`, `--allow-experience` and
`--protect` relative paths. Scope includes directories and initially absent paths
for planned additions. Allowed/protected paths must be inside that scope; protected
paths take precedence.
Scope/allowed/protected declaration format, membership, ownership and link
boundaries are checked before input/runtime hashing. Invalid Windows backslash
paths remain rejected; use portable relative paths such as `tests/test_case.py`.
The error identifies the offending option/path. Valid declarations retain the
same full inventories, hashes and before/after/current evidence.

`check review --changes` compares the original scope with
current bytes and reports product/experience changes separately. Protected or
unassigned changes make the review `needs_review`; `check_status` separately
retains the testcase reuse decision. Missing original boundaries are unknown.
This covers declared paths only, so choose a scope containing the full assignment
and its protected inputs. It does not waive changed check inputs or replace diff
review. Submit the existing result summary and finish independent review/experience
before collection; use its retained [success receipt](workflows.md#assign-collect-and-resume)
to release writers and reply when the requested work is complete.

## Verification surfaces

| Surface | Local verification | Separate live evidence |
|---|---|---|
| Install/update | All 24 active skills, three-way conflicts, recovery and preserved project knowledge/settings | Actual adopter conflicts, discovery and chat adoption |
| Roles/tasks | Actual-ID assignment, submitted/terminal-ready separation, collection/archive/restore and task-list updates | Visible chats, real completion arrival and integration |
| Dependencies | Partial readiness, failure/cancellation, cycle/delivery deduplication and uncertain-send recovery | All-role ended-turn idle, active-recipient delivery and authorized follow-up |
| Plan | Supported settings/update or turn/start fields and manual fallback | Actual native Plan selection and model planning |
| Project modes | Preserved selection, interrupted transitions and unfinished/independent work | UI navigation and native archive cascades |
| Native transport | RPC dispatch, write/close deadlines, notification ordering/limits and private diagnostics | Actual host endpoint, supported methods, UI and active-turn behavior |
| Git/backup | Disposable branches, refs/index preservation, backup and inactive restore | Selected repository identity, exact snapshot and affected restore |
| Publication | Exact projection, privacy, PR/squash and uncertain responses | Checked head, merged tree and anonymous readback |
| Knowledge/skills | Metadata, resources, ownership preservation and applicable experience flows | Appropriate skill selection and useful application |

Core metadata describes roles and versions. Verify real input validation,
filesystem collision/link protection, concurrency, saved settings and native
errors. Inspect experience flows through relevant task scenarios; resource
presence or a completion reminder does not prove that useful advice was applied.
[Knowledge policy](knowledge.md) requires no wording, length or completion gate.
Resource checks cover local links and headings in skill bodies/references using
source candidate or actual installed bytes. They do not fetch external links or
validate general YAML. Selected model evaluations use input-only project artifacts;
their expectations remain outside the installed payload and model context.

`빠른 작업으로 진행해` selects brief relevant checks and exact deferred commands
under installed `ProjectGuide.md`'s fast-work rule. Report not-run coverage.
Read-only protocol schemas establish field availability only. Separate requested
live trials need their concrete scope, settings and cleanup; source maintenance
does not create diagnostic chats or model turns.

The transport exposes bounded notification retrieval and private diagnostics.
The scoped workflow observer owns shared command connections and future terminal
notification, without host startup, approval UI or automatic review/integration.
Test actual installed clients across process boundaries, same-user/generation
identity, creation-originator connection reuse, simultaneous calls, response loss
without mutation replay and caller deadlines that do not close a peer's work.
Test exact turn identity,
registration races, burst coalescing, rate limits, lifecycle/FS fallback, finite
reconnect, unsupported APIs, lost/duplicate/old-cycle events, lease expiry and
cleanup failure. Whole deadlines include connection, RPC, I/O and cleanup.
Standard-I/O/WebSocket fixtures cannot establish Desktop
surface availability; see [sessions](sessions.md).

For dependency costs, separate elapsed wait, tool wait and model requests.
An unchanged dependency should cause zero periodic model requests and a confirmed
meaningful transition should produce no duplicate wake-up. Measure a fixed task
on the selected candidate, retaining source identity and consumed fixture inputs.
The fixed installed protocol fixture repeats the same model-free task three
times. Count native RPC by method,
local IPC, response bytes, connections/processes and completion delivery delay
separately. A retained historical run is context, not a controlled speedup or
token-saving measurement; do not rerun an old version merely to populate a report.
Model-free fixtures cannot establish model behavior or quality. Count
experiment-observer queries separately from
product/runtime queries and model polling. A role's total input includes actual
assignment, review and collection work; do not classify it all as waiting cost.
Do not infer unmeasured Camel behavior or unnecessary tests from Cameleer traces.
Count distinct native usage response IDs; cached input and reasoning output are
subsets. Missing telemetry is unknown. A local duplicate guard prevents repeated
integration, but cannot prevent every duplicate native message invoking a model.

On Windows, atomic writes retry only replacement-sharing errors 5 and 32 with
the same flushed temporary bytes, at most six attempts and 0.62 seconds of delay,
rechecking links each time. Permanent failures preserve original bytes. A
replacement-blocking fixture cannot identify a prior holder or prove live
publication. See [Windows sharing semantics](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew).

Reports identify what ran, failed, remains uncertain and was deferred. Static
inventory/links, installed runtime, model adoption, backend effects, visible UI
and external delivery have separate evidence boundaries. Versioned observations
and their original limits live in [CHANGELOG](CHANGELOG.md).
