<p align="center">
  <img src="assets/readme-hero.svg" width="220" alt="DMeloper's Oasis">
</p>

<h1 align="center">
  <img src="assets/readme-title.svg" width="360" height="52" alt="DMeloper's Oasis"><br>
  <sub><sup>Independent AI agent workflows for Codex on Windows</sup></sub>
</h1>

Oasis is a thin harness for assigning visible Codex chats and retaining useful
implementation experience on Windows with Python 3.11+. Read the package version
from [its literal](oasis_harness/__init__.py) or `oasis.py --version`.
Core 2.0.0 uses **Cameleer → Camel**: Cameleer assigns and integrates work;
Camel investigates, implements and checks it, then reports directly.

## Source or adoption

This repository is the primary development source. `seed/` and `library/` are
inactive source templates for **24 skills, all active after installation**.
Use [development](docs/development.md) for source maintenance and
[installation](docs/installation.md) to apply an inspected package to a separate
project. Never self-install for source parity.

Applying a repository URL includes local installation and selected-mode
initialization. Pin and inspect the source, review its three-way plan and resolve
actual conflicts. Preserve project settings, knowledge and user skill edits.
Installation retains the project's Git choice and does not select service targets.

## Working modes

| Mode | Work |
|---|---|
| Pioneer / 개척 모드 | One visible chat performs requested work directly. |
| Oasis / 오아시스 모드 | Cameleer coordinates visible Camels; Oasis maintains the harness. |

Fresh empty projects default to Pioneer; existing programs and installations
without a mode default to Oasis. The selection persists until the owner changes
it. See [workflows](docs/workflows.md).

Cameleer records chat IDs, goals, useful context and results in
`.oasis/state/tasks.md` at assignment, collection and resume. The suggested
title is `camel_A_task`; renaming a Camel does not change its connection.
Completion arrives directly; Cameleer reviews the relevant diff and performed
checks, integrates and archives the Camel. Follow-up work restores the same
chat. Dependencies use one notice when the named part ends.

Planning enters native Plan mode where supported and starts the requested
investigation immediately. Unsupported paths give the manual mode/start
instruction once. Implementation follows the user's instruction.
`빠른 작업으로 진행해` selects prompt implementation and brief checks;
`계획작업으로 진행해` selects the planning flow.
See [ProjectGuide](seed/ProjectGuide.md).

## Relevant guides

| Operation | Reference |
|---|---|
| Source development/delivery | [Development](docs/development.md) |
| Install or upgrade | [Installation](docs/installation.md) |
| Assign, communicate, collect or resume | [Identity](docs/identity.md), [sessions](docs/sessions.md) |
| Modes and transitions | [Workflows](docs/workflows.md) |
| Harness health/updates | [Doctor](docs/doctor.md) |
| Git and private recovery | [Git and backup](docs/git-backup.md) |
| Requested publication | [Publication](docs/publication.md) |
| Reusable experience | [Knowledge](docs/knowledge.md) |
| Checks and limits | [Validation](docs/validation.md) |
| Version history and transition procedures | [CHANGELOG](docs/CHANGELOG.md) |

Run source commands from this root; adopters use installed `tools/oasis.py`:

```powershell
python -B -X utf8 oasis.py --help
python -B -X utf8 oasis.py skills list
python -B -X utf8 -m unittest discover -s tests -t . -v
```

Read the applicable skill experience before choosing an approach. Once before
final completion, consolidate useful lessons in the existing owner, combining
duplicates and replacing advice disproved under its own conditions. With nothing
useful to change, finish without a reference edit or routine report. Existing
project knowledge stays in its actual file; see [knowledge policy](docs/knowledge.md).

The [upgrade index](docs/upgrade-index.json) describes predecessor deltas;
actual bytes and local conflicts determine application. Core metadata describes
roles and versions. [CHANGELOG](docs/CHANGELOG.md) retains historical procedures
and evidence.

Source delivery targets `d-meloper/dmelopers-oasis` on `main`, with private
recovery at `d-meloper/dmelopers-oasis-harness-backup`. These bindings and source
tooling are excluded from adopter installation. Requested source edits finish
with validation, the version hook, backup and reviewed PR/squash delivery under
[development guidance](docs/development.md#commit-and-synchronize).

The owner selected [Apache-2.0](LICENSE); preserve [NOTICE](NOTICE) and
[license guidance](docs/license.md) in distributed copies.
