# Developing Oasis Harness

This is the primary source for Windows/Codex and Python 3.11+.
`oasis_harness/__init__.py` owns the package version; Core 2.0.0 describes
Cameleer → Camel. All 24 distributed skills are active after installation.
Templates in `seed/` and `library/` are inactive here.

Use `python -B -X utf8 oasis.py` from this root. Select the guide and checks
needed by the changed function. Inspect actual HEAD/index/working bytes and
bindings before Git operations. Preserve concurrent work, settings and private
state. Use disposable adopter fixtures instead of self-installation.

The confirmed Package 1.2.0 / Core 2.0.0 change retires Calf, moves implementation
to Camel, enables direct completion and simplifies guidance/runtime.
Core metadata is descriptive; file hashes still protect actual installer bytes
and exact public candidates. See [migration](installation.md#core-2-migration).

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

1. Review and stage the ready scope. Append its predecessor delta to
   `docs/upgrade-index.json` and commit through the patch hook.
2. Run `backup run`, then `backup status`. Verify the actual account, immutable
   private repository ID/visibility and committed-main match. The selected
   `isolated-unmanaged` policy uses the existing external bare relay.
3. Run `tools/source_delivery.py prepare` with a new external destination, title
   and notes. It compares actual public main, scans the whole retained source
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
   proofs are not required.
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

The complete projection retains bounded privacy scanning, regular file/mode
inventory, neutral templates and resource links. Exact path/hash exceptions in
`tools/public-source-policy.json` describe reviewed scanner literals or synthetic
fixtures; actual secrets/private paths cannot be waived. README PNG/SVG artwork
keeps its exact asset pins and static-content checks. These protect export bytes
and are separate from the removed behavioral core seals.

## Commit version

Use configured `.githooks/pre-commit` and `tools/bump_commit_version.py`.
A clone does not activate hooks automatically. Local setup preserves other Git
keys and never changes global settings. Development hooks are not installed
into adopters.

An ordinary commit reads HEAD and increments package patch Z once. Stage one
chronological predecessor entry in `docs/upgrade-index.json`, listing changed
paths, adopter application/checks and source-only effects. Its inventory matches
staged files except the index and package literal. Keep earlier identities;
advisory notes do not replace actual byte review.

Stage the scope and use plain `git commit`; partial-path/alternate-index commits
refuse before version writes. A failed retry against unchanged HEAD reuses the
pending patch. Never bypass the hook. X/Y and core changes require an explicit
owner request.

An explicitly requested new base records X.Y.(Z+1):

```powershell
git -c oasis.versionBase=X.Y.Z commit -m <message>
```

An explicitly requested exact version records the staged literal:

```powershell
git -c oasis.versionTarget=X.Y.Z commit -m <message>
```

The target must change HEAD, remain command-local and have no simultaneous base.
The next ordinary commit increments the new HEAD patch. The confirmed overhaul
selects exact Package 1.2.0 and Core 2.0.0.

Keep operational evidence in ignored `.oasis/local/`; put reusable experience in
the nearest reference. [Validation](validation.md) distinguishes fixtures,
native discovery, model behavior and external effects.
