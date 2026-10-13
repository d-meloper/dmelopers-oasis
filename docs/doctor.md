# Harness Doctor

Harness Doctor checks the selected upstream and applies compatible owned
updates while preserving project modifications. All 24 skills are active after
installation. Consult the owning skill's `references/workflow.md` when the
current operation needs it.

## Version deltas and selective application

`docs/upgrade-index.json`, installed at `.oasis/manual/upgrade-index.json`,
describes predecessor deltas and paths/checks. Doctor intersects advisory notes
with actual incoming differences and local specializations. Skipped versions,
missing/discontinuous history and repeated labels need actual byte review;
notes and labels do not establish provenance or behavioral policy.

Pin the complete project-selected source/ref/commit/tree, compare ownership,
saved bases and incoming bytes, then use the three-way installer. Resolve actual
conflicts, uncertain deletions, missing bases, bindings and material structural
decisions. Preserve mode, settings, user skill edits, knowledge and
task history.

## Local audit and update

```powershell
python -B -X utf8 tools/oasis.py doctor audit --target <adopter> --package <staged-source> --output <new-report>
python -B -X utf8 tools/oasis.py doctor plan --target <adopter> --package <staged-source> --output <new-plan>
python -B -X utf8 tools/oasis.py install apply --plan <reviewed-plan>
```

Source operators use `oasis.py`. These helpers inspect a complete donor distinct
from the target; they do not fetch upstream or initialize chats. `current` means
saved bases match the donor, with specializations shown separately. It does not
claim remote freshness or model adoption.

Doctor and ordinary upgrades refresh all bundled skills through saved bases,
preserving local changes. File collisions, missing files and corrupt bases are
recoverable conflicts. Runtime updates do not rebind an installed Git engine.

## Core 2 migration

Core 2.0.0 removes Calf and moves implementation/checks to Camel. No hash seal
or protected-key policy blocks this versioned migration. Actual file comparison,
local-content resolution and transaction safeguards remain. Finish existing
Camel/Calf work before transition, retain its historical links and migrate
useful local Calf knowledge before retirement. See
[migration](installation.md#core-2-migration).

For a Core 1 installation, run audit, plan and apply from the inspected incoming
source's `oasis.py`, not its old installed helper. The old helper still has the
Core 1 seal and cannot provide the new unfinished-work wait or migration:

```powershell
python -B -X utf8 <incoming-source>/oasis.py doctor audit --target <adopter> --package <incoming-source> --output <new-report>
python -B -X utf8 <incoming-source>/oasis.py doctor plan --target <adopter> --package <incoming-source> --output <new-plan>
python -B -X utf8 <incoming-source>/oasis.py install apply --plan <reviewed-plan>
```

An update preserves mode and chats; it does not bulk archive or initialize
replacements. Later assignments use direct completion and actual chat IDs.
A source checkout uses source Git review, without self-installation or resetting
local commits to public squash history.
