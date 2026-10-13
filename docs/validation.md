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
consumed inputs. Version/documentation changes alone do not invalidate unaffected
functional checks.

Run checks for changed inputs and retain failed, missing or deferred coverage.
Exact final export, privacy and identity checks still apply to the candidate.
Source delivery accepts a retained verified build receipt explicitly; a bare
log or failed run cannot become a pass.

| Surface | Local verification | Separate live evidence |
|---|---|---|
| Install/update | All 24 active skills, three-way conflicts, recovery and preserved project knowledge/settings | Actual adopter conflicts, discovery and chat adoption |
| Roles/tasks | Actual-ID assignment, title changes, direct completion, collection/archive/restore and task-list updates | Visible chats, real completion arrival and integration |
| Dependencies | One terminal notice, failure/cancellation, duplicates and uncertain-send recovery | Ended-turn idle and authorized follow-up |
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

`빠른 작업으로 진행해` selects brief relevant checks and exact deferred commands
under installed `ProjectGuide.md`'s fast-work rule. Report not-run coverage.
Read-only protocol schemas establish field availability only. Separate requested
live trials need their concrete scope, settings and cleanup; source maintenance
does not create diagnostic chats or model turns.

The transport exposes bounded notification retrieval and private diagnostics.
It supplies no host startup, cross-process bridge, approval UI or automatic
workflow integration. Standard-I/O/WebSocket fixtures cannot establish Desktop
surface availability; see [sessions](sessions.md).

For dependency costs, separate elapsed wait, tool wait and model requests.
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
