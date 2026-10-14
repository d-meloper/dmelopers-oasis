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
The scoped workflow observer owns future terminal notification, without host
startup, approval UI or automatic review/integration. Test exact turn identity,
registration races, burst coalescing, rate limits, lifecycle/FS fallback, finite
reconnect, unsupported APIs, lost/duplicate/old-cycle events, lease expiry and
cleanup failure. Whole deadlines include connection, RPC, I/O and cleanup.
Standard-I/O/WebSocket fixtures cannot establish Desktop
surface availability; see [sessions](sessions.md).

For dependency costs, separate elapsed wait, tool wait and model requests.
An unchanged dependency should cause zero periodic model requests and a confirmed
meaningful transition should produce no duplicate wake-up. Compare the same fixed
task on baseline and candidate: elapsed time, role-specific waiting tokens, RPC
counts and output quality. Count experiment-observer queries separately from
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
