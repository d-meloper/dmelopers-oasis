# Git and backup experience

## Working bytes and object identity

Committed-object backup covers neither dirty/staged/untracked/ignored files nor
worktree administration. Preserve those separately when the requested transition
needs them. Verify commit/tree types, exact refs and required history; equal
trees do not establish equal lineage.

Use explicit native paths and byte input where protocol identity matters.
Isolate inherited Git environment for owned disposable children. Preserve
ordinary text policy while marking content-addressed baseline blobs as non-text.

## Backup and uncertain recovery

Check the exact triggering commit and backup outcome independently.
Bind destination identity, catalog ancestry and restored snapshot scope.
An upgraded CLI does not establish which immutable engine Git hooks execute.
After a managed runtime upgrade, commit the reviewed files and rebind the same
profile from clean primary main; verify the next actual post-commit catalog's
triggering commit, preserving the earlier engine. See the manual below.
Inspect existing relay ownership before setup. Verify retained object closure
for external LFS/submodule dependencies and reserve the restore target throughout
intake. Preserve inactive restores until an explicit rebind.

Keep effective Git configuration isolated across the complete operation.
Reconcile uncertain pushes with observed remote objects before retrying.
Large ref sets use the owning transport adapter rather than exceeding native
command-line limits. Preserve recoverable committed work.

The [manual](../../../../.oasis/manual/git-backup.md) contains current commands;
[version history](../../../../.oasis/manual/CHANGELOG.md) retains source evidence.
