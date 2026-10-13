# Harness Doctor

`oasis-harness-doctor` is a default maintenance skill beside the eight protected
core skills, with fifteen optional families still selectable. It assigns no new
role and does not activate a service or upstream binding on installation.
The skill's `references/workflow.md` owns the complete workflow and decision list.
This package includes Doctor; protected core remains v1.0.0. Existing installations
that lack this default skill gain it through an owner-approved upgrade rather than silent
activation. Each adopter selects its own upstream repository/ref and pins its full
commit/tree. Source checkouts follow their own authorized Git workflow; compare
actual source bytes and modes, including separately generated public metadata.
Never reset or self-install to force SHA equality.

On a normal Doctor maintenance request, obtain the complete project-selected
upstream, pin its verified repository/ref/commit/tree, compare actual ownership
and apply compatible owned updates. An audit-only request stops at inspection.
Ask about all unresolved material conflicts, intentional deletions, baseline
repairs, binding changes, new/removed skills, structural/authority changes and
core migrations before application. Keep user settings and project knowledge.

The CLI is deliberately local and uses the existing installer, not a downloader:

```powershell
python -B -X utf8 tools/oasis.py doctor audit --target <adopter> --package <staged-source> --output <new-report>
python -B -X utf8 tools/oasis.py doctor plan --target <adopter> --package <staged-source> --output <new-plan>
python -B -X utf8 tools/oasis.py install apply --plan <reviewed-plan>
```

Source operators invoke `oasis.py` from the trusted source; installed adopters use
`tools/oasis.py`. Inspect `--help` first. The donor must be a complete, inspected
source distribution, distinct from the target. These commands neither verify
remote provenance nor grant semantic approval. Plan application needs the
candidate identity and material decisions established by the skill's workflow.

Audit compares incoming/installed versions and exact resource hashes, detects
missing or specialized files, checks saved bases, core pin, selected capability
consistency and all plan conflicts. `current` means the saved upstream bases
match this donor; local specializations remain separately visible. It is not a
claim of remote freshness, model adoption, identical local bytes or defect-free
behavior. Same-version donor bytes can still be outdated locally.

Doctor plans update the entire owned distribution and selected active skills,
including their resources and immutable bases, while merging independent local
edits. Missing managed files and corrupt bases need explicit reconciliation;
the plan never guesses whether deletion was intentional. Incoming core drift
requires a supported, explicitly approved versioned migration. Keep existing
external journals for interrupted apply/recovery. Ordinary installer upgrades
retain their active-skill preservation behavior.
After runtime updates, inspect an existing managed Git engine's actual binding.
If it needs refresh, retain that as a pending decision and follow the separate
reviewed commit/rebind procedure; file updates do not prove the old engine adopted
them.

A primary source checkout uses its selected source Git workflow. A missing
manifest does not authorize installation, and source divergence does not justify
resetting local commits. Native discovery and old-chat adoption need their own
evidence. No real remote fetch/update or model adoption is established by the
local helper tests.
