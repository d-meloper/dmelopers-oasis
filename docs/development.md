# Developing Oasis Harness

This root is the Oasis Harness source of record and primary development project.
It maintains the package on Windows/Codex with Python 3.11+, eight protected
core skills, default Harness Doctor and Pioneer, and fifteen optional skills. The original
baseline is v1.0.0. Protected core meaning, digest and version remain v1.0.0.
The owner approved Doctor and Pioneer creation and the mode runtime/manual,
with this mode addition explicitly selecting package v1.1.0. Protected core
meaning, digest and version remain v1.0.0; package and core versions are distinct.
The `__version__` literal in `oasis_harness/__init__.py` is the package version's
source of truth; inspect `oasis.py --version` for the current value. Static guide
headings do not select a version.

`oasis_harness/` implements the runtime; `oasis.py` is the source CLI entry point.
`tests/` contains disposable local fixtures. `docs/` holds neutral manuals,
verification boundaries and migration knowledge. `seed/` supplies adopter
defaults, eight protected core skills, default Harness Doctor/Pioneer and protected
contracts. `library/` supplies fifteen
inactive optional skill families. Keep adopter-specific tools, paths, accounts,
credentials, chats and approval records outside these distribution inputs.

Run from this root:

```powershell
python -B -X utf8 oasis.py --version
python -B -X utf8 oasis.py --help
python -B -X utf8 oasis.py skills list
python -B -X utf8 -m unittest discover -s tests -t . -v
python -B -X utf8 oasis.py session discovery --target .
```

`skills list` inventories package templates. Native discovery checks the actual
root catalog; it does not prove adoption by this or another chat. Shared skills
and connectors remain host facilities and do not establish project bindings or
authority. Read only the relevant template skill when reviewing its implementation.
Do not treat template AGENTS.md or project.json as active root settings.

Harness health/update requests route through the default `oasis-harness-doctor`;
see [Doctor](doctor.md). Keep source Git comparison separate from adopter
manifest/baseline upgrades. Doctor can refresh selected active optional skills
through reviewed three-way plans; ordinary upgrades still preserve them. The
helper performs local audit/planning only, with no implicit fetch, apply or remote
approval. The skill obtains the complete pinned upstream, reviews deltas and
asks the owner for every unresolved material conflict/structural/authority decision.
For this source, the owner selected the approved public repository's `main`
latest commit. Pin it and verify the complete source path/mode projection;
producer/public squash SHAs differ, with a public-only release manifest.
This choice does not pre-bind installing projects or select a release-tag channel.

The task pacing name is `빠른 작업` (`fast work`); its shared rule is in
`seed/ProjectGuide.md`, under "Fast work" (adopters use installed ProjectGuide).
`빠른 작업으로 진행해` immediately selects it for the current authorized task
without another confirmation. Implement promptly, keep inspection/checks brief,
and leave a runnable verification entry point and exact deferred checks. Full
suites are the normal-depth path and are deferred when this task pacing is
explicitly selected. Project mode, role and authority remain unchanged.

The two persistent adopter modes are [Pioneer and Oasis](workflows.md). This
primary source retains its existing Oasis responsibilities and never installs
the mode runtime or Pioneer as active adopter configuration. Review distributed
mode changes using disposable adopter fixtures and distinguish local/native
evidence. Existing adopter upgrades preserve mode and do not initialize chats.

Owner-established independent Oasis work follows the single
[independent specialist session contract](../seed/LocalGitWorkflow.md#independent-specialist-sessions).
It changes no protected core role and transfers no source account or external
authorization to adopters. Keep domain entry points in target domain skills.

`계획작업으로 진행해` uses the shared "Planning work" rule in
`seed/ProjectGuide.md`: an established independent Oasis chat stays in that same
chat for tool-free waiting; ordinary coordinated work retains the Camel
`plan-wait` handoff. The assigned waiting chat asks for actual Codex Plan mode and
the owner's planning start. Do not claim a native mode toggle from prompt text.
Starting planning and starting implementation remain separate owner instructions.
A request to add or explain this trigger is source maintenance, not a dispatch.

Installing the package into itself is a separate material decision. It would
add active skills, root contracts, installed manuals, a manifest and a duplicate
runtime. First review an installation plan and resolve actual conflicts. For
ordinary source development, invoke the source CLI and use disposable adopter
fixtures instead. [Installation](installation.md) documents those boundaries.

The owner selected an independent ordinary Git producer on `main`, retaining the
development patch hook and inactive templates. Public source is
`d-meloper/dmelopers-oasis`; committed recovery is the distinct private
`d-meloper/dmelopers-oasis-harness-backup`. Preserve prior remote/configuration
in private evidence before removing the producer's public remote/upstream.
No managed profile or self-installation is implied.

The explicitly selected `isolated-unmanaged` backup policy verifies development
hooks and uses the existing external bare relay/catalog and inactive restore.
Run backup manually at each completion; no automatic post-commit or scheduled
job is selected. Actual IDs, relay paths, exported bindings and restore receipts
stay private. `seed/` stays unmanaged and unbound; `tools/source-publication.json`
is this source's public binding, never an adopter default. Consult
[Git and backup](git-backup.md) and [publication](publication.md).

## Commit and synchronize

This source's default delivery is the lightweight path. These rules apply only
to this primary development checkout. They are not installed into adopters and
never select an adopter's account, Git profile, publication policy or services.
The owner requested faster individual updates; retain privacy and exact target/
byte checks while avoiding repeated broad tests and demonstrations.

1. Inspect the actual owned diff, main HEAD/index and isolated binding. Preserve
   other writers and user settings. Stage the ready scope and use the patch hook
   with plain `git commit`; exclude private/ignored material.
2. Run one `backup run`, then confirm `backup status` matches committed main and
   actual private ID/account. Repeat independent restore only for new backup
   setup, storage/restore changes, failures or an explicit owner request.
3. Use `tools/source_delivery.py prepare` with a new external destination, title
   and short notes. It compares the committed files/modes with actual public main,
   scans the complete retained source and selects relevant local test modules.
   The retained run is the validation evidence; do not rerun it in the working
   tree solely for a second receipt. Documentation edits use distribution/privacy
   smoke checks. Runtime/test changes add their affected suites; shared CLI/common
   or unknown Python changes fall back to the full suite. `--full` explicitly
   requests all tests. Show selected/deferred coverage and exact candidate hash.
4. Inspect the final public diff, complete scan, exact target/base and intended
   removals. The owner approved routine source-only delivery of requested ordinary
   edits under this guide; no additional candidate-approval prompt is needed
   within that fixed scope. Before public writes use two independent subagents
   for precision review in parallel. Review the affected behavior and boundaries;
   require evidence or a concrete reproduction before classifying a defect.
   Correct clear, proven defects and rerun only checks invalidated by the fix.
   Style preferences or hypothetical issues alone do not block delivery. Record
   the actual outcomes locally; a fabricated review label proves nothing.
   Binding/protection/authority changes, new skills, core meaning, licenses,
   new assets or expanded exports still need concrete owner decisions.
5. Use `tools/source_delivery.py execute` for the same candidate. Attach the created
   PR immediately; use `attest` for its exact checked head and resume `execute`.
   Keep PR/squash, strict required `oasis-source-checks`, identity checks, secret
   scanning, push protection and force/deletion bans. The status describes the
   actual selected coverage, not a claim that the full suite ran.
6. The source adapter verifies every anonymous public blob with at most eight
   concurrent reads, plus exact parent/tree. Report local/public SHA and private
   catalog. Do not repeat a full clone, fresh install, native discovery or restore
   demonstration on every update. Repeat only affected live checks or an explicit
   owner request; fixtures are not live model-adoption evidence.

The runtime publisher remains generic. Source-specific scan policy, test
selection, concurrent source readback and repository binding live in `tools/`.
Source candidates require the explicitly supplied development policy and refuse
through the generic installed CLI. No tag, release, asset or automatic adopter
update is created by this source-only path. Unchanged old source-only files are
retired by adopter upgrade; locally edited retired files remain for owner review.

Use the verified OS-stored OAuth for `d-meloper`, preserving shared GitHub CLI
account selection and global settings. Any separate `GH_CONFIG_DIR` is process
local account metadata without copied tokens. Verify immutable public/private
IDs and visibility for each operation. Never reconnect a producer public remote,
reset to the public squash, force history or disable protections.

If an operation fails or its response is uncertain, retain the commit, candidate,
state and private evidence. Reconcile actual remote identities before resuming;
report pending synchronization instead of inventing completion. No background
monitoring, automatic service activation or new scheduling is implied.

The privacy gate always covers the whole public projection, including inherited
files and original export paths. Existing neutral namespaces, core/default/
optional resources and complete regular modes remain checked. Only exact
path/hash/reason scanner-literal or synthetic-fixture exceptions are permitted in
`tools/public-source-policy.json`; changed bytes require a fresh scoped review.
Actual credentials, private settings, unknown files and binaries cannot be
exempted. The owner-selected README hero is the sole binary exception: its exact
PNG path and inspected SHA256 are pinned in `tools/source_policy.py`; changed
bytes or any other binary image path fail. The two UTF-8/XML SVG source files
`assets/readme-title.svg` and `assets/readme-hero.svg` have separate exact path/hash
pins and restricted markup with no external or executable references. These
text pins grant no additional binary exception; changed bytes need fresh scoped
review. Artwork stays in this source repository, outside the installed adopter
payload. Bounded scans do not prove absence of all unknown secrets.

## Commit version

On the owner's separate version-automation request, this source repository uses
`.githooks/pre-commit` and `tools/bump_commit_version.py`. The local
`core.hooksPath` is `.githooks`; setup preserves other local Git keys and does not
write global Git/Codex settings. The prior hook setting/files were absent. A clone
does not activate hooks merely by checkout; inspect actual existing hooks before
the owner-authorized local setup. These development files are outside `seed/` and
do not activate a harness Git profile or an adopter's hooks.

For each ordinary source commit, the hook changes only package `Z` in `X.Y.Z` by one.
It reads the last committed literal, stages the new version, preserves unrelated
unstaged edits in that file and checks index readback. A failed commit may leave
one pending patch in the index/worktree; retry against unchanged HEAD uses that
same target instead of incrementing again. The protected core version does not
follow package commits. X/Y and other version changes require an explicit owner
request; routine work never chooses a minor or major increment automatically.

Stage exactly the ready files and use `git commit`. Do not use `--no-verify` or
override hooks for routine source commits. Partial-path/alternate-index commits
are refused before version mutation to preserve staged state; stage the desired
subset first. An intentionally empty Git commit uses `--allow-empty`, and amend
also produces a new patch version; history rewrites still require their own
authority under the source delivery policy.

For an explicitly owner-selected new base, update and stage the package literal
and pass that exact base for this command only:

```powershell
git -c oasis.versionBase=X.Y.Z commit -m <message>
```

The hook records `X.Y.(Z+1)` in that commit. The flag is intent data, not proof
that the owner requested the change. Do not save a persistent base or use it to
choose other version components autonomously. Recheck the actual committed
literal, stage scope and remote SHA. Read package version through `oasis.py
--version`; do not duplicate a current patch number into guide headings.

When the owner explicitly requests an exact version, stage that literal and use
`git -c oasis.versionTarget=X.Y.Z commit -m <message>` for that command only.
This exceptional path records the selected value without the ordinary increment;
it rejects persistent configuration, an unchanged HEAD version, an unstaged
target or simultaneous `versionBase`. The next ordinary commit increments the
new HEAD patch. The flag records the requested target, not owner authority.
Never choose a reset or a different version autonomously.

Put machine-specific reports, pending operations and raw evidence under
`.oasis/local/`. Do not export that directory or treat it as durable knowledge.
Generalize verified findings into the nearest existing guide, preserving evidence
scope and remaining unknowns. Keep private paths and identifiers out of portable
knowledge; see [knowledge lifecycle](knowledge.md). Core meaning changes require
approval, an explicit version and migration; local results do not authorize an
upstream handoff or external application.

Report which selected checks actually ran and which suites were deferred. Historical live trials in
[validation](validation.md) do not transfer approval to this root. Python versions,
model behavior, restored settings, installed runtime and external service writes
need their own evidence when relevant. No new chat or external write follows
from a successful test or catalog read.
