# Installation and upgrade

Oasis Harness targets Windows/Codex with Python 3.11+. Install into an existing
project distinct from the inspected source. New installs provide all 24 skills
in active discovery, guidance, manuals and runtime.
The file installer does not initialize Git or native chats; project mode
initialization uses the [workflow adapter](workflows.md).

## Project bootstrap from a repository URL

A request to apply a harness URL selects its main ref unless another is supplied
and includes local installation plus selected-mode initialization. Pin the actual
repository identity, full commit/tree and complete regular source bytes before
running acquired code. Public reads need no token. Inspect executable installer
inputs as candidate data; version labels and matching filenames are not trust.

Acquire source outside the target without running checkout filters, hooks,
submodules or candidate code. Preserve global Git/Codex settings and credentials.
Reject unsafe/case-colliding paths, links, submodules and private-state payloads.
An isolated bare fetch and direct materialization of verified regular blobs
provide a reproducible intake; retain source hashes privately.

Use the target's actual instructions, files and Git state. Preserve project
settings, user skills and other writers. Existing valid manifests route to
[Doctor](doctor.md); incomplete ownership needs recovery instead of reinstallation.

## Plan and apply

From the trusted source, create an external plan:

```powershell
python -B -X utf8 oasis.py install plan --target 'C:\Projects\Example' --output 'C:\Review\install.json'
python -B -X utf8 oasis.py install diff --plan 'C:\Review\install.json'
python -B -X utf8 oasis.py install apply --plan 'C:\Review\install.json'
```

Review conflicts and decoded before/after operations. Apply checks recorded
current bytes under an operation lock immediately before each change and
journals both sides. It does not replace a file merely because its name matches.
The target/package must not traverse links or Windows reparse points.
Spaces, apostrophes, Korean, CJK and emoji paths use native argument arrays.

For initial collisions, prepare exact compatible merged bytes outside the target.
`--resolutions <file>` accepts schema 1 with a `files` array, each row containing
`path`, `before_sha256` and `after_base64`. The current hash binds the reviewed
inputs; the manifest retains original donor bases. Preserve existing guidance,
ignore rules and licenses. Unused paths, duplicate rows, changed current bytes
and unrelated paths refuse. Actual conflicting content needs the owner's
decision; a generic approval prompt is unnecessary for compatible requested work.

Fresh empty projects default to Pioneer; existing programs default to Oasis.
An explicit fresh `--mode pioneer|oasis` overrides that selection. Valid
installs without a mode retain Oasis. Upgrades preserve mode; use the separate
requested workflow switch to change it.

## Complete project bootstrap

Set a fresh project name from known project facts and record the selected source
under `adapters.harness_upstream` with repository URL and ref. Preserve existing
adapter/extension fields. Add only demonstrated local commands/knowledge.
Keep the project's Git choice and local skill modifications. If a canonical
knowledge policy already exists, link its actual file and heading from project
guidance and add only compatible closing guidance. Preserve its location and
shared implementation references; use the installed knowledge manual when no
project owner has been established.

Verify the installed payload and native catalog:

```powershell
python -B -X utf8 tools/oasis.py install verify --target .
python -B -X utf8 tools/oasis.py skills validate --project .
python -B -X utf8 tools/oasis.py session discovery --target .
```

The 24 target-local bundled skills and user skills may coexist with
shared host skills. File inventory and discovery do not prove instruction adoption.
Use `skills list --project . --summary` for the bundled files' current descriptions
and missing/invalid status. Existing metadata validation remains limited to the
supported frontmatter shape; it is not a general YAML validator.

Initialize one visible Pioneer, or Oasis plus Cameleer, using the selected mode's
[workflow](workflows.md). An install-only request leaves them ready for later
work; a concrete task in the same request can start immediately. Use existing
IDs after uncertainty rather than creating duplicates. Report the actual source,
specializations, checks, role links or pending initialization and resume action.

Installation preserves project Git history/remotes/index, existing hooks,
settings and unrelated files. Backup/publication use the project's selected
targets when included in requested work; source bindings are never copied.

## Owned files, manuals and recovery

`.oasis/install-manifest.json` records managed paths, hashes, original bases
and active capabilities. Immutable bases live under `.oasis/base/<sha256>`.
Manuals are installed under `.oasis/manual/`; runtime is under
`.oasis/runtime/` with entry point `tools/oasis.py`. Source development
guidance, tooling, hooks and account/repository bindings are excluded.
LICENSE/NOTICE are retained as harness notices without replacing the project's
root license.

An external journal under the local OasisHarness installations directory is
created before writes. Keep its reported exact path and plan through recovery:

```powershell
python -B -X utf8 oasis.py install recover --journal <journal.json> --action resume
python -B -X utf8 oasis.py install recover --journal <journal.json> --action rollback
```

Recovery accepts only recorded before/after bytes; later user edits remain
untouched for reconciliation. Completed journals are not general rollback tools.
An abandoned operation lock needs inspection of the actual process before its
exact lock can be removed.

## Upgrade without losing project knowledge

Run from the incoming inspected package:

```powershell
python -B -X utf8 oasis.py install upgrade --target <project> --output <new-plan>
python -B -X utf8 oasis.py install apply --plan <reviewed-plan>
```

The plan compares upstream base, local and incoming bytes. Independent JSON-key
and non-overlapping text changes combine; actual conflicting edits stop apply.
Locally specialized files absent from the incoming package remain preserved
for resolution. Root knowledge scaffold ownership is released without deleting
project copies; their content can remain the project's canonical knowledge. All bundled
skills refresh through three-way comparison without discarding local changes.
Owned files absent from the incoming payload are removed when unmodified;
customized copies remain project-owned after ownership is released.
User skills and knowledge outside
package ownership remain untouched.

Updates preserve mode, Git settings, adapters, local skill edits and chat
history. They do not initialize chats or bulk archive them. Runtime file updates
do not silently rebind an active Git engine.


Version-specific transition procedures are recorded in [CHANGELOG](CHANGELOG.md).
