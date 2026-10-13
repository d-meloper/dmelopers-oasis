# Oasis Harness development

This is the independent source of record for Windows/Codex and Python 3.11+.
Use `python -B -X utf8 oasis.py` from this root. `seed/` and `library/` are
inactive distribution templates; source maintenance never needs self-installation.
The package literal owns its version; the current role contract is Core 2.0.0.

Oasis maintains the harness; Cameleer assigns and integrates work; Camel
investigates, implements and checks its assignment, then reports directly.
Pioneer remains the single-chat mode. Calf is retired. Use actual chat IDs for
assignment, completion and reuse; titles are a naming convention.

Read the guide needed by the current operation. Keep guidance thin and
product-neutral. Useful experience belongs in the owning skill's best-practices
reference with applicability and evidence. Preserve project knowledge, settings,
optional/user skills and historical task links. Finish existing Camel/Calf work
before the Core 2 transition.

`빠른 작업으로 진행해` immediately applies [fast work](seed/ProjectGuide.md#fast-work).
`계획작업으로 진행해` uses [planning](seed/ProjectGuide.md#planning-work):
supported native Plan mode and immediate requested planning, or one manual
mode/start instruction. Implementation follows the user's instruction.
For dependencies, name the blocked part, finish independent work and end the
turn; resume from one terminal notice without polling or ACKs.

Finish requested source changes with relevant validation, a scoped hook commit,
verified private backup and the exact reviewed public candidate under
[development guidance](docs/development.md#commit-and-synchronize).
Public source is `d-meloper/dmelopers-oasis` on `main`; private recovery is
`d-meloper/dmelopers-oasis-harness-backup`. Verify actual account, immutable
repository IDs and visibility for each operation. The owner authorizes routine
source-only delivery of requested edits without repeated candidate approval.
Unresolved material decisions still need the owner.

Use `.githooks/pre-commit` with the intended staged scope and plain `git commit`.
Ordinary commits increment only package patch Z from HEAD and append a
predecessor delta in [the version index](docs/upgrade-index.json).
Explicit exact versions use command-local `oasis.versionTarget`; X/Y and core
changes follow explicit owner requests. Never bypass the hook.

Preserve other writers, private/ignored state and Git/Codex settings.
Operational evidence stays in `.oasis/local/`. Keep PR/squash, required
`oasis-source-checks` and full anonymous readback. Never push the producer
directly, reconnect its public remote, reset to the public squash, force history
or disable protections. Report actual checks and limits using
[validation boundaries](docs/validation.md).
