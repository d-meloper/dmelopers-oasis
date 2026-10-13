---
name: oasis-git-operations
description: Operate the selected Git profile, coordinated refs and recovery, with optional bound private backup; exclude public publication.
---

# Git Operations

Inspect actual root, branch/full HEAD, index, refs, worktrees and owners. Default unmanaged means observe and use project conventions; installation creates no Git policy. Managed profiles single-main and main-test have explicit readiness and transition contracts. A profile change preserves history and user bytes and needs a reviewed expected-old transaction, not a config edit alone.

Obtain acknowledged ownership and serialize stage/hooks/commit. Preserve foreign staged/dirty/untracked/ignored data; Git objects do not protect working bytes. Keep commit, tree and patch equivalence distinct. Never force equality of lanes over unfinished work or clean old worktrees to make a transition pass.

Optional private backup uses the actual configured destination and immutable identity, source policy and isolated relay. Restores/copies start inactive. Automatic post-commit coverage needs the exact triggering SHA and independent verification; commit success is not backup success. Final commit-free ref changes need the configured manual completion boundary. On uncertain push inspect before retry, preserve the commit and report recovery.

No role permission derives from branch names, receipts or config labels. Public source/release writes belong to the publication workflow.

Use [protected identity](../../../.oasis/docs/identity.md), [internal handoffs](../../../.oasis/docs/communication.md) and the [knowledge lifecycle](../../../BestPractice/KnowledgeLifecycle.md) only as relevant.
