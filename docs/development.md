# Developing Oasis Harness

This is the primary source for Windows/Codex and Python 3.11+.
`oasis_harness/__init__.py` owns the package version; Core 2.0.0 describes
Cameleer → Camel. All 24 distributed skills are active after installation.
Templates in `seed/` and `library/` are inactive here.

Use `python -B -X utf8 oasis.py` from this root. Select the guide and checks
needed by the changed function. Inspect actual HEAD/index/working bytes and
bindings before Git operations. Preserve concurrent work, settings and private
state. Use disposable adopter fixtures instead of self-installation.

Read applicable experience before choosing an approach. Once before final
completion, consolidate useful lessons in the existing owner under
[knowledge policy](knowledge.md). Preserve project knowledge files and avoid
duplicate closing passes, extra verification or publication caused only by
experience consolidation. Core metadata describes roles and versions; file hashes
protect actual installer bytes and exact public candidates. [Release notes](CHANGELOG.md)
describe public harness changes and required migrations. Operational evidence
stays in ignored local records.

`빠른 작업으로 진행해` applies [fast work](../seed/ProjectGuide.md#fast-work)
immediately: implement, run a brief relevant check and leave deferred commands.
`계획작업으로 진행해` uses the [planning flow](../seed/ProjectGuide.md#planning-work):
native Plan and requested planning, or one manual fallback instruction.
Implementation follows the user's instruction; project mode persists.

## Commit and synchronize

The source uses an isolated ordinary producer on `main`, private recovery
`d-meloper/dmelopers-oasis-harness-backup` and public source
`d-meloper/dmelopers-oasis` on `main`. These are source bindings only.
The owner authorizes routine source-only delivery of requested edits without
another candidate approval; unresolved material decisions need the owner.

1. Record the task's starting commit and keep ordinary checkpoint commits at
   the existing package version. On completion, review the whole task, append
   its predecessor delta to `docs/upgrade-index.json` and finalize one patch
   through the hook using that full baseline commit.
2. Run `backup run`, then `backup status`. Verify the actual account, immutable
   private repository ID/visibility and committed-main match. The selected
   `isolated-unmanaged` policy uses the existing external bare relay.
3. Run `tools/source_delivery.py prepare` with title and notes. Omit
   `--destination` to retain a unique run under `.oasis/local/deliveries/`.
   It compares actual public main, scans the whole retained source
   and selects relevant tests. Supply `--reuse-build-receipt <verified build.json>`
   when that retained run already verified the implementation. The adapter checks
   its source, commands and logs, reuses unchanged test inputs and runs checks for
   the changes since that run. Common/CLI or unknown Python changes without matching
   evidence use the full suite; documentation uses distribution/privacy checks.
   Retain the original and current evidence. Final candidate bytes/privacy are
   scanned again; unchanged functional tests are not restarted merely to publish.
4. Review the exact public diff, target/base, removals, scan and coverage.
   Independent review focuses on proven defects in affected behavior; refresh
   checks invalidated by corrections. Fixed reviewer counts and behavior-policy
   proofs are not required. Check the public title, notes and installed manuals
   against the [public change guidance](#public-change-guidance).
5. Run `tools/source_delivery.py execute` for that candidate. Attach its PR,
   `attest` the checked head and resume `execute`. Keep PR/squash, required
   `oasis-source-checks`, repository protections and identity checks.
6. The adapter reads every anonymous public blob with bounded concurrency and
   verifies parent/tree. Report producer/public SHA, backup catalog, coverage
   and live limits.

Use verified OS-stored OAuth for the selected account without altering shared
account selection or global settings. Verify immutable public/private IDs and
visibility at each operation. Never push the producer directly, reconnect its
public remote, reset/merge to public squash, force history or disable protections.

Retain uncertain commits, candidates and evidence; reconcile remote state before
retry. No tag, release asset, adopter update, monitoring or service activation
follows from source delivery. Repeat restore, fresh install and live discovery
when affected or requested.
`tools/source_delivery.py status --candidate <file> --sha256 <hash>` inspects
retained local progress. Add `--remote` for read-only remote reconciliation; status
does not prepare a new candidate or repeat a publication.

The complete projection retains bounded privacy scanning, regular file/mode
inventory, neutral templates and resource links. Exact path/hash exceptions in
`tools/public-source-policy.json` describe reviewed scanner literals or synthetic
fixtures; actual secrets/private paths cannot be waived. README PNG/SVG artwork
keeps its exact asset pins and static-content checks. These protect the exact export bytes.

## Commit version

Use configured `.githooks/pre-commit` and `tools/bump_commit_version.py`.
A clone does not activate hooks automatically. Local setup preserves other Git
keys and never changes global settings. Development hooks are not installed
into adopters.

Ordinary commits preserve the package version and release identities. Record
the full starting commit before task work. When that task is complete, stage one
chronological predecessor entry in `docs/upgrade-index.json`, listing the exact
net changed paths from that baseline to the index, including earlier checkpoint
commits. Exclude the index and package literal. Finalize package patch Z once:

```powershell
git -c oasis.versionFinalize=<full-task-baseline-commit> commit -m <message>
```

The baseline must be an immutable ancestor in this repository. Finalization
selection is command-local; ordinary and empty checkpoint commits do not bump.
Describe an adopter-facing change through its summary and affected
areas, application and checks. For maintenance with no adopter-facing effect,
leave `summary`, `areas` and `source_only` empty; the version, predecessor and
file inventory retain continuity. Do not add operational prose to `source_only`.
Keep earlier version identities; advisory notes do not replace actual byte review.

`tools/bump_commit_version.py --delta-draft --base <full-task-baseline-commit>`
previews an unfinished release row for the whole task through the current index.
`--output .oasis/local/<run>/delta-draft.json` retains that draft without
changing the index or filling in review judgments. Inspect and finish it before
staging the version index.

Stage the intended scope and use the normal commit path; partial-path/alternate-index
commits refuse before version writes. Repeat the same finalization command after
a failed commit; its pending patch is reused. Never bypass the hook. X/Y and core changes require an explicit
owner request.

An explicitly requested new base records X.Y.(Z+1):

```powershell
git -c oasis.versionFinalize=<full-task-baseline-commit> -c oasis.versionBase=X.Y.Z commit -m <message>
```

An explicitly requested exact version records the staged literal:

```powershell
git -c oasis.versionFinalize=<full-task-baseline-commit> -c oasis.versionTarget=X.Y.Z commit -m <message>
```

The target must change HEAD, remain command-local and have no simultaneous base.
The next ordinary commit retains that version. A later completed task finalizes
its next patch from its own recorded baseline. An owner-requested consolidation
of unpublished versions uses the last released producer commit as baseline and
an exact target, preserving all baseline release identities and Git history.

Keep operational evidence in ignored `.oasis/local/`; put reusable experience in
the nearest reference. [Validation](validation.md) distinguishes fixtures,
native discovery, model behavior and external effects.

## Public change guidance

Write public commit and PR titles around the resulting harness behavior or
maintained source contract. Release descriptions explain the affected capability,
correction, compatibility or required migration in terms useful to an adopter.
Maintenance without an adopter-facing effect needs no CHANGELOG entry or upgrade
description. The source repository still contains its maintained code, tests and
development contracts.

Keep temporary-folder moves, individual test-fixture repairs, interrupted runs,
cleanup incidents, private backup receipts and task retrospectives in the local
operational record. Do not turn each patch commit or verification step into a
public release item. Source validation and evidence storage procedures belong in
this development guide; installed manuals describe the adopting project's
available operations.

Review public wording together with the actual candidate. Automated content
checks can enforce declared boundaries and detect known local-record patterns;
they do not establish whether every sentence is relevant or every claim is true.
When removing operational narrative from current public documents, preserve its
originals in local evidence and existing Git/private recovery history. Preserve
license notices and any migration procedure still needed by existing installs.

## Source checks

Run source tests from this root:

```powershell
python -B -X utf8 -m unittest discover -s tests -t . -v
```

Tests use disposable filesystem/Git projects and injected native/service adapters.
Select checks affected by the changed function and its consumers. Shared or
unknown Python changes use the full suite when matching retained evidence does
not cover them. Keep original outcomes, inputs and logs when reusing coverage;
a bare log, failed or incomplete build cannot establish delivery success.
Live chat adoption and remote effects require their own evidence.

## Local workspaces and cleanup

Keep Oasis test, review and delivery work inside this project, under ignored
`.oasis/local/`; do not create sibling staging folders on the Desktop.
Tests set their temporary root to `.oasis/local/tmp/`. Each `TemporaryDirectory`
owns a unique fixture and removes it on normal or exceptional context exit.
Retained snapshots inside that operational tree share the owning Git checkout's
scratch root; nesting another scratch tree inside a snapshot can exceed native
Windows path limits. Each process still reserves distinct fixture directories.
Do not remove this shared root while checks or native fixture processes are active.
After an interrupted process, inspect its exact orphan before removing it; age or
a matching folder prefix alone does not prove that another writer has finished.

Retain build receipts, exact source snapshots, command logs, outputs, coverage,
review notes and candidate/state files together in `.oasis/local/deliveries/<run>/`.
They remain needed for check reuse, recovery and anonymous readback, including
failed or uncertain operations. These are evidence, not disposable fixtures;
never run broad cleanup over `.oasis/local/` or delete a retained snapshot while
another receipt references it. Archive a retired run only after its users are
finished, with a per-file hash manifest and verified archive readback; preserve
original path/reference mappings. Existing historical archives remain untouched.

Explicit external build/delivery destinations remain compatible, but ordinary
source work uses the internal paths above. Internal build and publication paths
must be ignored, untracked descendants of `.oasis/local/`, with no links/reparse
points. The source checkout and its ancestors cannot be output destinations.
The external bare backup relay keeps its separate recovery ownership.
