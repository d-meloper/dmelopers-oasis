# Local Git profiles and private recovery

The default `unmanaged` profile supports a directory with no Git and an existing repository without claiming ownership of its history, hooks, remotes, or branch layout. Managed profiles are `single-main` and `main-test`. Both require a complete, remote-free source repository, an exact reviewed `main` checkout, and explicit activation. Private backup and public publication use distinct external workspaces and credentials; neither adds a source remote.

## Initial commit and activation

After installing, an empty or unborn repository may receive a harness-only initial commit:

```powershell
python tools/oasis.py git initialize --root 'C:\Projects\Example'
```

Initialization uses the user's actual Git author and refuses existing history or foreign staged data. It stages only manifest-owned files and their baseline blobs. Other user files stay untracked. If the commit is interrupted, inspect `.oasis/local/initialize.json` and the index; no automatic index reset is performed. Complete the recorded owned commit only after resolving the failure. A project with existing commits skips initialization entirely.

Edit `.oasis/project.json` to set `git.profile` to `single-main` or `main-test`, review and commit that policy using the existing workflow, and ensure the working tree is clean. `git status` reports both desired policy and actual local activation. Obtain the exact HEAD with Git, then activate:

```powershell
python tools/oasis.py git activate --root 'C:\Projects\Example' --profile main-test --expected-head FULL_SHA
python tools/oasis.py git status --root 'C:\Projects\Example'
```

Activation refuses existing remote/upstream settings, shallow/replaced history, unknown hooks, dirty ownership, a different expected HEAD, or a divergent existing `test`. It never merges arbitrary histories or deletes retained branches. First activation can create `test` only at exact `main`. Other existing heads remain immutable recovery references.

The active Python engine and hooks live in the Git common directory under `oasis/engines/<content-id>`, with a recorded hash inventory. The absolute hook binding is independent of branch contents. Old linked worktrees use that engine but cannot mutate the managed source. Engine tampering, moving/copying the project, or changed common-directory identity makes the binding inactive. Hooks require primary-checkout identity, reject source pushes and non-fast-forward lane rewrites, and preserve existing tags. This protects normal Git operations; it is not a security boundary against an operator deliberately editing local Git policy files.

## Bounded profile changes and recovery

Commit the desired target profile first. With clean primary `main`, transition from single-main to main-test only when `test` is absent or equal to exact `main`; transition back only when both tips are equal. A retained `test` is never deleted. Select the branch with ordinary Git under the owner-approved shared source window.

```powershell
python tools/oasis.py git transition --root 'C:\Projects\Example' --profile main-test --expected-main FULL_SHA
python tools/oasis.py git transition --root 'C:\Projects\Example' --profile single-main --expected-main FULL_SHA --expected-test FULL_SHA
python tools/oasis.py git recover --root 'C:\Projects\Example' --expected-head FULL_SHA
```

If `test` already exists, provide its expected SHA even when equal. Pending activation/transition journals permit only the exact recorded continuation. Divergent history needs an explicit owner-reviewed mapping outside these bounded operations; there is no automatic reset, merge, removal of remotes, or managed-to-unmanaged deactivation.

Use `git rebind` with the same profile and exact main SHA to deliberately bind a copied, moved, restored, or upgraded project. It retains history and validates the new engine; it does not transfer private-backup authority. Restore creates an inactive repository which requires this review before source operations resume.

## Optional GitHub private backup

Configure only after the owner approves the concrete private repository and account. Commands validate immutable GitHub repository/account IDs, exact canonical name, private/non-fork/non-archived state, and stored GitHub CLI OAuth. Environment token overrides are removed. An existing relay with unknown ownership or transport configuration is rejected.

The default backup source policy is `managed`: configuration requires the actual
active managed Git binding described above. Existing bindings without a
`source_policy` field retain that contract. Repository or manifest absence never
selects another policy.

```powershell
python tools/oasis.py backup configure --root 'C:\Projects\Example' --repository OWNER/PRIVATE_REPO --repository-id ID --account-id ID --relay 'C:\Recovery\Example\relay.git'
python tools/oasis.py backup run --root 'C:\Projects\Example'
python tools/oasis.py backup status --root 'C:\Projects\Example'
python tools/oasis.py backup export-binding --root 'C:\Projects\Example' --output 'C:\Recovery\example-binding.json'
```

Retain the exported binding separately. It contains identity and local path metadata, never credentials. The relay is external and bare. Transfers use explicit atomic refspecs without force, mirror, pruning, or deletion. A unique external transport configuration carries large ref sets without exceeding Windows command-line limits; it contains the verified destination and exact refspecs and never changes source or relay local configuration. Successful readback removes only that token-owned transport file. Uncertain attempts retain it with their operation receipt.

On Windows, choose short physical relay and restore paths and inspect their
resolved locations. Packaged desktop apps may redirect AppData into a longer
per-app directory. If an empty setup fails on a ref-lock path, preserve the
unfinished binding and use an explicitly reviewed shorter external path.
Existing completed bindings need a reviewed migration. This is path-specific
recovery; validate the actual destination instead of assuming long-path support.

Catalog commits append exact source refs, main tree identity, reflog commit coverage, and the actual triggering commit when automatic backup runs. Remote identity and refs are reread before and after transfer. A lock contender cannot release another operation's lock. An uncertain push retains its intent receipt; inspect status and rerun only after reconciling the observed remote state. A push whose acknowledgement was lost is not repeated when the remote already contains the complete expected snapshot.

Backup covers committed Git objects and supported source refs. It does not preserve working, staged, untracked, ignored, or external files; take a separate owner-reviewed filesystem snapshot when those bytes matter. Unclassified ref namespaces, Git LFS and submodules fail closed because this version has no storage/independent-repository adapter for them.

For the managed policy, the exact Codex capture/checkpoint ref shapes documented
below are classified as local-only Desktop comparison state. Their targets must
still be regular trees without links/submodules. They remain untouched in the
source and are excluded from the catalog and transfer: their trees can contain
uncommitted tracked bytes. `source_refs_match` checks the selected backup refs and
reflog commits, not these local-only refs. Status reports
`codex_auxiliary_ref_policy: local-only` and their current
`local_only_auxiliary_ref_count`; `source_auxiliary_refs_match` remains null.
Unknown Codex shapes and other unclassified namespaces still fail closed.

Upgrading installed runtime files does not replace the active immutable hook
engine. Commit the reviewed upgrade, keep the existing managed profile and use
`git rebind --profile <same-profile> --expected-head <full-main-sha>` from clean
primary `main`. Then verify the next commit's automatic backup and catalog
`triggering_commit`; manual CLI backup alone does not verify the fixed hook.

## Explicit isolated source with existing development hooks

An owner may separately select `isolated-unmanaged` for a primary source checkout
that keeps its ordinary development hooks. This is manual private backup, not
managed-profile activation or an installation into the source itself. It requires
an actual committed `main` checkout, complete history, no source remotes,
remote-tracking/upstream settings or managed binding, and the actual desired
profile `unmanaged`. A source without `.oasis/project.json` or an install manifest
may use this explicit policy. It does not create either file or assign roles.

```powershell
python -B -X utf8 oasis.py backup configure --root <source> --repository OWNER/PRIVATE_REPO --repository-id ID --account-id ID --relay <external-relay> --source-policy isolated-unmanaged
python -B -X utf8 oasis.py backup run --root <source>
python -B -X utf8 oasis.py backup status --root <source>
python -B -X utf8 oasis.py backup export-binding --root <source> --output <new-external-binding>
```

Installed operators use `tools/oasis.py`; source operators use `oasis.py`.
Configuration retains the exact primary/common-directory identity, local and
effective `core.hooksPath` values, resolved hook directory and its file hash
inventory. It preserves the settings and files rather than replacing, executing
or chaining hooks. Hook path, inventory, source isolation or project-policy drift
blocks backup and leaves owner bytes intact for explicit reconciliation. Existing
managed bindings cannot be downgraded through this flag. A changed binding needs
a concrete migration; retrying configure does not silently adopt changed hooks.
Finish each authorized source commit with an explicit `backup run` and verified
`backup status` under the adopting project's selected completion instruction.
The source commit remains intact after backup failure. No automatic post-commit
operation follows from this policy; `enable-auto` requires the managed engine and
refuses `isolated-unmanaged`.

This policy additionally preserves only the identified Codex auxiliary ref
shapes `refs/codex/turn-diffs/captures/<timestamp>/<uuid>/base` and
`refs/codex/turn-diffs/checkpoints/<hex32>/<hex32>/<timestamp>/<uuid>` when they
identify regular trees without links/submodules. It neither moves nor deletes
the application-owned source refs. The catalog retains their exact names/OIDs;
private remote anchors use immutable
`refs/tags/source-local-captures/<ref-digest>/<tree-oid>`. These captured trees may
contain local snapshot bytes and belong only in the approved private backup,
never public source exports. Their presence does not establish complete backup
of all current working/index/ignored state. Other Codex/unknown namespaces stay
blocked. The managed policy does not upload these trees; it uses the explicit
local-only classification above instead of the isolated-unmanaged retention.

For isolated-unmanaged, `backup status` keeps `source_refs_match` as the full
selected refs/reflog check, including supported auxiliary refs.
The separate `source_main_match` verifies the current `main` commit/tree and
every current source head/tag against the catalog and exact remote refs. It
does not claim auxiliary or working-state coverage. Codex may create another
capture after a completed backup without changing committed source;
`source_auxiliary_refs_match` reports that pending auxiliary difference separately.
A source-delivery gate may use the explicit committed-source result for its
exact `main` candidate while recording the auxiliary limit, rather than calling
the whole source snapshot current. A new source commit always makes that result
false until backed up and read back.

Remote-only restore recovers these original auxiliary refs alongside the exact
source `main` commit/tree using only the retained private binding and remote.
The restored checkout still has no remotes, active hooks or backup binding.
For this source policy inspect restored files/settings and make a new explicit
manual binding; a managed `git rebind` is a separate selected-profile decision.

## Independent restore and automatic operation

Restore reads the remote into a new independent intake and verifies the catalog, refs, complete objects, main tree, and clean checkout. It never trusts relay objects. The target must be new or empty and separate from source/relay. An exclusive destination lock, repeated ownership checks and a non-overwriting checkout preserve a competing writer's files. The verified intake is retained for diagnosis. Interrupted targets retain `.git/oasis/restore-pending.json`; preserve them and choose a new empty destination after inspection instead of automatically clearing them.

```powershell
python oasis.py backup restore --binding 'C:\Recovery\example-binding.json' --destination 'C:\Restore\Example'
python tools/oasis.py backup enable-auto --root 'C:\Projects\Example' --destination 'C:\RestoreProof\Example'
```

Every relay, intake and restore Git operation isolates global/system transport configuration and hooks. Restored repositories persist an inactive effective hook path, including when the host has a global hook configured. Explicit `git rebind` recognizes the matching restore receipt and installs the reviewed engine.

`enable-auto` first syncs and performs a real independent restore. Only success records automatic activation. The synchronous post-commit hook then backs up the actual committed SHA. Backup failure leaves the source commit intact and reports manual recovery; it never claims remote success or undoes that commit.

Local behavioral fixtures use disposable real Git repositories and an injected provider. They do not provision a real repository, change live source policy, or establish production OAuth/network availability. Approved live identity, push/readback, independent restore, and automatic post-commit verification remain required before enabling a real destination.
