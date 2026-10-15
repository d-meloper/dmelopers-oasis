# Build and GitHub publication

Publication is an explicitly selected project operation. Installation leaves
publication unconfigured; choose the adopting project's own account, repository,
checks and approval policy. Package source-development tools and bindings are
not part of the installed runtime or manuals.

All selected exports are scanned by original source and destination path. The
complete surviving public projection is scanned, including inherited base blobs,
before preparation and before any execution/resumption writes. Committed regular
file modes are preserved. Source-only operations enforce null tag and false
make_latest and verify every projected anonymous blob after squash. Do not turn
off the gates to complete delivery.

Changing an existing private repository to public is outside `publish setup`.
The owner's separate exact visibility request needs a review of all reachable
history, author metadata, refs, Actions logs/artifacts, releases, comments, wiki,
Pages and existing protections. Record the immutable identity and observed limits
privately; recheck before changing visibility, then read it back anonymously and
apply the approved protection/security setup. Public forks/copies cannot be
recalled by making the repository private again. See [GitHub visibility rules](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility).

Local producer source has no publication remote. A separate public repository
contains selected source plus artifacts, or artifacts only. Producer commit/tree
evidence remains local in artifacts-only mode; a public metadata commit anchors
the release. Existing public files remain in the reviewed base unless exact
removals are named. There is no automatic whole-project export.

## Build adapter

`build --root <producer> --revision <full-commit> --adapter <json> --destination
<producer>/.oasis/local/builds/<new-run> --version <version>` materializes regular files from one
Git commit. It rejects links, submodules and Windows path collisions. Working
changes remain untouched. Internal evidence must be ignored and untracked;
explicit external destinations remain supported. Retain receipts, logs and exact
source/output bytes together. The adapter JSON contains exactly:

```json
{"schema_version":1,"build":[["python","build.py","--output","{output}"]],"checks":[["python","check.py","{output}"]],"artifacts":["application.zip"]}
```

Commands are argument arrays run in the retained source folder. Placeholders
are `{source}`, `{output}`, `{version}`. Inspect these executable project commands
before use: this runner is not an OS sandbox. Supply the project's real builder
and product checks; absence is not a pass. Failed runs/logs remain local. A
verified receipt binds command exits, logs, source hashes and exact output bytes.
Publication rechecks retained evidence and copies candidate bytes; release logs,
receipts and source identity are never implicitly uploaded.

For source-only verification set adapter `purpose: "source"`; `build` and
`artifacts` may then be empty, while real `checks` remain mandatory. A release
cannot consume an empty-artifact result.

## Setup and connection

`publish setup <plan.json>` reads the actual account/repository and presents the
plan hash. It performs no external write without `--apply --authority <reference>`.
Schema-1 fields: `repository`, `account_id`, `create`, `repository_id` (null only
when creating), `base_branch`, `bootstrap_readme`, `protection`. Protection is the
exact supported GitHub branch protection request; configure required reviews and
status contexts for the project. Review whether the acting account can merge
under those protections; never weaken them during publication to pass a gate.

Setup creates only the named public repository when approved, bootstraps the
approved minimal README if empty, applies the specified branch protection and
enables immutable releases. Existing private repositories are never converted.
Settings and ID are read back. Organization membership, unsupported settings or
insufficient permissions produce a retained failure, not a fallback. A creation
with no response must be reconciled against actual repository identity before
any retry. Setup and release approvals are distinct.

## Candidate

`publish prepare --config <json> --build-receipt <build.json> --notes <utf8-file>
--destination <producer>/.oasis/local/deliveries/<new-run>/candidate` only reads
GitHub and writes local evidence. Candidate paths follow the same private
workspace boundary as builds.
Configuration includes `schema_version:1`, exact `repository`, `repository_id`,
`base_branch`, `channel` (`stable` or `preview`), `mode` (`source-and-artifacts`
or `artifacts-only`), `version`, `tag`, `title`, boolean `make_latest`, an `exports`
mapping of exact committed source path to public path, and `required_checks`
(GitHub commit status context names). Optional `remove_public_files` lists exact
reviewed deletions. Preview additionally needs a distinct verified
`production_repository_id` and cannot become latest. An inspected programmatic caller may supply a custom source policy via the
`policy` argument and bind its exact name in `source_policy`. Configuration
data never loads that code. A custom candidate refuses without the matching
explicit policy; the installed CLI uses the generic strict scanner.
Check-run-only projects
must bridge their required check into a named commit status or supply a reviewed
adapter; unknown check mechanisms do not pass.

For a public-source-only change set `operation: "source"` in selected-source
mode. Keep `tag: null` and `make_latest: false`; version/channel identify the
reviewed projection. The candidate verifies and squash-merges the source PR,
then stops with `source_verified`; no tag, draft or release assets are created.
Omitting operation selects the release workflow.

Review all bytes, inherited public base, removals, titles, notes, binary artifact
contents, licenses, target identity and scan limits. Path/token scanning cannot
prove arbitrary archive/binary content safe. Security/asset skills add the
project's archive and binary validators before approval. Record actual human
approval for the displayed candidate SHA256 and operations. A receipt string,
successful scan, old approval or `configured:true` is never that approval.

## Execute and resume

`publish execute <candidate-folder> --sha256 <approved-sha256> --authority
<actual-request-reference>` operates only within the real human-approved scope.
It creates a candidate branch and PR, checks exact tree/parent/head and required
statuses, requests an exact-head squash merge, prepares a draft, uploads missing
assets, verifies the complete asset set and then publishes. Immediately attach
every created PR to the active Codex task using its returned `pr_url`; a CLI
cannot attach to the desktop task itself. On interruption read `state.json` and
attach any already created PR before continuing.

All stages write intent before the remote mutation. Resume queries actual PR,
draft and asset identities. Conflicting, partial, duplicate or unexpected files
remain for inspection; no `--clobber`, tag movement or published-file replacement
exists. Missing objects after an uncertain non-idempotent creation stop further
retries. Candidate/target/base drift needs a new review and approval. Serialize
publication with other repository writers; GitHub's merge endpoint checks head
but does not offer a base compare-and-swap. A racing base change is detected by
post-merge parent/tree verification and blocks later publication; preserve the
unexpected merge and reconcile it explicitly rather than undoing history.

Merged-PR resume uses the retained exact merge commit when available and rejects
a conflicting REST `merge_commit_sha`. Without retained identity, use
that REST field or read this exact repository/PR's GraphQL `mergeCommit.oid`.
Verify repository ID, PR number and merged state, then the complete public tree
and approved parent for the resolved commit. An unavailable/null/error identity
or wrong commit stops without replaying the merge; the current main tip is never
a substitute. GitHub documents supported merged identity fields in its
[REST breaking changes](https://docs.github.com/en/rest/about-the-rest-api/breaking-changes)
and [GraphQL PullRequest reference](https://docs.github.com/en/graphql/reference/pulls#pullrequest).
Injected tests cover retained-state and response-loss recovery and conflicting
or incomplete identities. The adapter still supports only SHA-1 GitHub objects;
these checks do not grant approval or establish other providers' behavior.

After publishing, verify immutable status, tag commit, title/body/channel/latest,
exact asset names/sizes and anonymous downloaded SHA256. Metadata remains
separately checked because immutability does not freeze every release field.
Follow [immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases),
[repository API](https://docs.github.com/en/rest/repos/repos) and
[release API](https://docs.github.com/en/rest/releases/releases).
External scanner uploads, document edits, store submissions and mail are not
included; each requires its own explicit scope and supported adapter.
