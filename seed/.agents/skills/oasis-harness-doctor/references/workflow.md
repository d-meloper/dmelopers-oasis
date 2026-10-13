# Doctor workflow

## Select target and upstream

Distinguish an installed adopter with `.oasis/install-manifest.json` from the
source checkout or an uninstalled folder. Use the project's selected upstream;
resolve an unbound repository/ref/account with the owner. Keep upstream selection
in `adapters.harness_upstream`, separate from backup/publication bindings.

Read the actual repository identity, visibility and exact commit/tree, and acquire
the complete source into an isolated staging folder. Preserve shared account and
Git/Codex settings. Inspect paths, regular file modes and bytes before executing
staged code; linked paths, private-state payloads and unsupported extraction need
resolution. Record exact candidate provenance in local evidence.

## Review the update

Use version-delta notes to find affected areas, then compare actual bytes.
Same-version drift, missing delta chains and unmapped changes still need their
actual diff. For an installed project, use the trusted entry point:

```powershell
python -B -X utf8 tools/oasis.py doctor audit --target <project> --package <staged-source> --output <new-audit-file>
python -B -X utf8 tools/oasis.py doctor plan --target <project> --package <staged-source> --output <new-plan-file>
```

The helpers audit and plan local files; they do not fetch or apply. Compare the
candidate digest with the staged bytes. The proposed update covers owned runtime,
manuals and all 24 active skills, preserving independent local edits through
existing baseline/current/incoming comparison. Existing user-created skills stay
in place. All domain skills are available immediately after install or upgrade;
there is no skill-selection or activation operation.

Legitimate local specialization is not automatically a defect. Resolve overlapping
edits, corrupt/missing bases, intentional deletions or material changes to project
bindings/settings with concrete affected bytes and choices. Do not repeat decisions
already covered by the current request. Audit-only work stops at the audit.

For source work, compare the pinned remote source with HEAD/index/worktree and
use that source's Git workflow. Preserve local ahead/diverged work; source review
does not require installing the package into itself.

## Legacy Calf transition

For Core 1 projects, use the inspected incoming source's `oasis.py` for audit,
plan and apply. The old installed helper still enforces the old core seal and
cannot apply the unfinished-work wait, all-skill mapping or Calf migration:

```powershell
python -B -X utf8 <incoming-source>/oasis.py doctor audit --target <project> --package <incoming-source> --output <new-audit-file>
python -B -X utf8 <incoming-source>/oasis.py doctor plan --target <project> --package <incoming-source> --output <new-plan-file>
python -B -X utf8 <incoming-source>/oasis.py install apply --plan <reviewed-plan-file>
```

Before transitioning an existing Camel/Calf project to Core 2.0.0, let active work
finish. Preserve chat/task links and the project's mode, Git choices, installed
and user-created skills, settings and knowledge. Transfer useful locally modified
Calf implementation material into Camel references, then retire the owned Calf
skill. Keep historical originals for recovery; reporting, manager creation,
approval and ownership ACK text is retired context, not new Camel guidance.
Local conflicts use the same installer comparison and resolution path.

## Apply and recover

Regenerate the plan against current bytes after resolving conflicts. If the
selected donor changed, review that delta before replacing the prepared candidate.
Use the conflict-free plan:

```powershell
python -B -X utf8 tools/oasis.py install apply --plan <reviewed-plan-file>
python -B -X utf8 tools/oasis.py install verify --target <project>
python -B -X utf8 tools/oasis.py skills validate --project <project>
```

The transaction retains expected-old bytes and recoverable originals. An
interrupted response resumes from the existing journal; later user edits remain
conflicts rather than being overwritten. Refresh checks affected by the update.
Report applied paths, preserved local specializations, conflicts, failed/deferred
checks and precise resume steps.

An existing managed Git engine may need a scoped rebind after runtime changes;
file replacement alone does not refresh that engine. Native catalog discovery
and actual chat adoption also differ from installed byte verification. Perform
the boundary relevant to the requested update and describe what remains unknown.
Use [Doctor experience](best-practices.md) for retained mechanisms and limits.
