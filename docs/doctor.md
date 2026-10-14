# Harness Doctor

Harness Doctor compares the selected upstream and applies compatible owned
updates while preserving project modifications. All 24 skills are active.
Use its skill's `references/workflow.md` for acquisition and recovery.

## Version deltas and selective application

The installed `.oasis/manual/upgrade-index.json` records predecessor deltas and
paths/checks. Doctor intersects advisory notes with actual incoming differences.
Missing/discontinuous history, repeated labels and unmapped paths receive complete
byte review. Pin the selected repository/ref/commit/tree, compare ownership and
saved bases, then use the three-way installer.

## Local audit and update

```powershell
python -B -X utf8 tools/oasis.py doctor audit --target <adopter> --package <staged-source> --output <new-report>
python -B -X utf8 tools/oasis.py doctor plan --target <adopter> --package <staged-source> --output <new-plan>
python -B -X utf8 tools/oasis.py install apply --plan <reviewed-plan>
```

Source operators use `oasis.py`. These helpers inspect a complete donor distinct
from the target; they do not fetch upstream or initialize chats. `current`
means saved bases match the donor, with specializations shown separately.
It does not establish remote freshness or model adoption.
One request reuses its donor and knowledge-case inventory. Apply and recovery
reread expected current bytes instead of trusting that earlier inventory.

Preserve mode, settings, user skills, project knowledge and task links. File
collisions, missing/corrupt bases and material binding changes need concrete
resolution. Compatible edits merge through baseline/current/incoming comparison.
Updates preserve independent knowledge owners and release discontinued template
ownership without deleting project copies. Runtime updates require a scoped Git
engine rebind when applicable; file replacement alone does not rebind it.

Finish a health/update task with its requested audit or verified application.
Before the final report, consolidate useful experience once under
[knowledge](knowledge.md). Version-specific migration procedures are retained in
[CHANGELOG](CHANGELOG.md).
