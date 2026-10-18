# Decisions

Implementation decisions the spec leaves open (spec §20). The design decision
log of `docs/design.md` §20 (D1–D19) is mirrored below so this file is the
one place to read "why is it like this?". Open spec questions live in
`docs/backlog.md`; when a question is settled here, the question entry stays
in the backlog for the spec revision and the answer is recorded here.

## Design decision log (mirrored from spec §20)

| # | Decision | Section |
|---|---|---|
| D1 | Multiple roots allowed; root = no outbound `refines`/`derives-from`. | 6.3 |
| D2 | Versioning Model 4 (mutable + integer versions + version-tracked links), hash-based detection in both modes, block scoped to newly outdated links, configurable. | 7.1 |
| D3 | Template migration: in-place for non-breaking, superseding for breaking; documents pin template versions; `init` copies built-ins into the repo. | 7.7 |
| D4 | Status derived from Git except the `deprecated` flag; acceptance = merge to baseline branch. | 8 |
| D5 | CRs are a first-class entity outside the graph (revised in r0.2); `affects` edges and kind `change` removed. | 9.1 |
| D6 | Glossary is first-class and outside the graph; slug identity; mention-based usage. | 10 |
| D7 | Conflicts recorded as symmetric edges, warned not blocked by default; four resolution patterns supported via existing commands. | 11 |
| D8 | Baselines are annotated tags with a manifest in the message; no committed file. | 12.4 |
| D9 | Assets are versioned through their owning document; users may place files in `assets/<ID>/` directly. | 5.7 |
| D10 | Document `type` immutable in v0.1; change via supersession. | 5.3 |
| D11 | Dependencies limited to pydantic, jinja2, markdown-it-py; argparse; shell-out Git; no networkx. | 16.3 |
| D12 | Extra level-2 sections are warnings, not errors. | 5.2 |
| D13 | Edge `refines` vs `derives-from` mutually exclusive on the same pair. | 6.4 |
| D14 | A CR's content is body plus scope; status, decisions and `introduces` are excluded, so deciding and implementing never invalidate a decision, while changing scope does. | 9.2, 9.3 |
| D15 | Scope `base_version` is the baseline-branch version at add time and changes only through `cr reanalyze`. | 9.4 |
| D16 | Drift = baseline version above base version, or target superseded/deprecated on the baseline; evaluated only while effective status is `open`/`accepted`. Implementation check runs against the working tree. | 9.6 |
| D17 | Decision authority = merge into the baseline branch; proposed vs. effective status is shown, not warned; `cr.deciders` is advisory. | 9.3 |
| D18 | Origin tracking as metadata (`origin_cr` / `introduces`), not edges. | 9.5 |
| D19 | Both CR workflows (proposal-first, single-PR) supported, none enforced; CRs optional via `cr.enabled`. | 9.9 |
| D20 | Typed IDs: `<PREFIX>-<ABBREVIATION>-<body>`, one required unique abbreviation per type, fixed reserved `CHG` for CRs; config schema 2 with a hard cutover and no aliases; standalone migration script; abbreviations immutable once used. (D-TYPED-IDS) | 4, 5.3, 7.2, 14 |

Known open items for v0.2 are listed in `docs/backlog.md` (mirrored from the
spec §20 closing note).

## Implementation decisions

### D-TOML-EMITTER

`config.toml` is written by a minimal internal TOML emitter in
`gregraph/core/config.py`, not by `tomli-w` (spec §16.3 offers either). The
config schema is fixed and shallow (scalar tables plus one table-of-tables
`types`); the emitter covers exactly that shape — basic strings with escaping,
integers, booleans, arrays of strings, bare/quoted keys — in ~80 lines. Rationale:
§16.3/D11 keep the runtime dependency set closed, and `tomli-w` would serve only
this one file. Reading stays on stdlib `tomllib` as specified. Emitter policy:
sections emitted in model field order (appendix B.1 order), `types` tables in
insertion order, `folder` omitted when it equals the type name (appendix B.1
writes no `folder` keys; the default is re-injected on read), comments are never
preserved (only `init` writes the file in v0.1, so nothing round-trips through
the writer). A present `types` key replaces the shipped default set entirely;
an absent `types` key yields the appendix B.1 defaults.

### D-OPREFUSED-HOME

`OperationRefused` lives in `gregraph/core/models.py`, next to `Finding`
(resolves the backlog SPEC-QUESTION "Where does `OperationRefused(finding)`
live?"). Spec §16.2 reserves exceptions for refusals (`OperationRefused`
carrying a `Finding`) and internal errors, but the §16.1 layout has no errors
module and the S1 model list omits the class. It is pure data handling around
a `Finding`, so it is defined where `Finding` is defined and every module that
raises refusals (`operations`, later `cli` which maps it to exit code 4)
depends only on `models`. Plain `Exception` subclass with a `finding`
attribute; `str()` renders `code: message`.

### D-S12-OPERATIONS

S12 semantics for the ambiguous corners of §7.6/§13.2–13.6,
§13.14–13.15. (1) Refusals are atomic: a refused `create_document` (bad initial
link, deprecated template) or `link_refresh` (deprecated target, fork under
`--follow`, missing target) writes nothing and raises `OperationRefused` with
the first refusal in sorted `(source, type, target)` order. (2) Explicitly
requested edges (`new --link`, `link`) abort on the first failed check; edges
inherited by `supersede --copy-links` are filtered instead — each candidate is
checked and failing ones are skipped and listed as findings in the result
(§11.2 "duplicates collapsed and shown for review"; a compromise must succeed
even when the two superseded documents hold incompatible links). (3)
`link refresh` on a stale link without `--follow` leaves the link untouched and
reports it with its supersession chain (the "interactive otherwise" branch of
§13.5 — core never prompts); `--follow` re-points to the chain end and refuses
with `E-SUPERSEDE-FORK` on a fork. `supersedes` links (S11 precedent) and
`conflicts-with` links (§11.2 "it remains … as history") are never re-pointed.
(4) `supersede --copy-body` defaults on when every target pins exactly the new
document's resolved template (name and version); multi-target body copies use
the first target's body; the default type is the targets' common type, else the
first target's type (noted in `notices`). (5) `--cr` on `new`/`supersede`
refuses `E-CR-DISABLED` when `cr.enabled = false` (§14 row) and otherwise calls
`record_introduction` (S13) before any file is written; the caller writes
`origin_cr`. (6) Unknown ID arguments refuse `E-ID-UNKNOWN`, unsupported `set`
keys `E-SET-KEY`, malformed assignments `E-SET-VALUE`, invalid tags
`E-TAG-INVALID` (refusal codes outside the §14 catalogue — see docs/backlog.md).
(7) `new` warns `W-NO-GIT-IDENTITY` whenever `created_by` is null (§5.4 "new
warns"), unlike `validate`'s narrower Git-repo-only reading.

### D-S13-CHANGES

S13 semantics for the ambiguous corners of §9/§13.18. (1)
Content contract (§9.2, D14): `content_hashes(cr, body) = (body_hash(body),
versioning.scope_hash(scope))` — exactly the two inputs `reconcile` compares;
`status`, `decisions`, `introduces`, `branch`, `external_ref`, `tags`, `extra`
are never hashed. Scope mutations (`cr scope add/remove`, `cr reanalyze`)
record one `version` bump and refresh the stored hashes; `cr reanalyze`
bumps explicitly because the id-list `scope_hash` cannot see `base_version`
changes (docs/backlog.md). Decisions, `introduces` and metadata never bump.
(2) Scope add-time rules (§9.4): liveness is checked only at add time
(deprecated/superseded/CR/term/unknown/duplicate all refuse
`E-CR-SCOPE-TARGET`); `base_version` is the baseline-branch version via a
lazy `files_at` snapshot, and a target absent from the baseline is refused
with a pointer at `new … --cr` (new work belongs in `introduces`). Degraded
mode (and a missing baseline branch) uses the effective working-tree version.
(3) Decision state machine (§9.3): same-status appends are `reaffirm`
confirmations (valid in the history); `cr set status=<current>` refuses
`E-CR-STATUS` pointing at `cr reaffirm`; empty history is `E-CR-STATUS`.
(4) `W-CR-MODIFIED-AFTER-DECISION` compares the **last** decision (§9.3
text), not the last non-open one. (5) Drift (§9.6) is baseline-only and only
while the **effective** status is `open`/`accepted`; the finding message
names the merged-implementation false positive and suggests
`cr set status=implemented`; the fix is `cr reanalyze`. (6) Validation codes
live in `validation.CR_CHECKS` (`check_change_requests`) composing
`changes.cr_findings`, which also applies §5.5/§5.6 to CR bodies (§9.2) and
the §9.7 mention rules (`E-MENTION-UNKNOWN`, `W-CR-MENTION-UNSCOPED`);
`E-CR-DISABLED`/`E-CR-CLOSED` are refusal-only. Findings are attributed to
the CR id, except `E-CR-ORIGIN-MISSING` (the document with the bad
`origin_cr`). (7) `record_introduction` writes the CR's `introduces` before
the caller writes the new document (S12 ordering) and refuses `E-CR-CLOSED`
for `rejected`/`implemented` CRs. (8) `cr show`'s impact set is 1-up +
unlimited-down per scope target, de-duplicated, excluding the scope targets
themselves (spec gap noted in docs/backlog.md).

### D-S14-GLOSSARY

S14 semantics for the ambiguous corners of §10/§13.20. (1)
Slug derivation (`derive_term_slug`): NFC-normalise, lowercase, maximal runs
of non-alphanumerics → `-`, trim (docs/backlog.md on non-ASCII). The slug is
the filename stem; `validate` checks `E-TERM-SLUG` for sidecar-slug/stem
mismatch, H1 ≠ `term` (missing H1 included), and case-insensitively colliding
stems (slug uniqueness — `kb.md`/`KB.md` is one identity on Windows/macOS).
(2) Alias uniqueness (`E-TERM-ALIAS-CLASH`) is case-insensitive and
symmetric: an alias collides with any term name (including its own) or with
any other alias instance; one finding per offending alias, name-vs-name is not
validated (no catalogue code). `term add`/`term rename` refuse the same matrix
before writing anything. (3) Usage (`term usage`, and the mention list of
`term rename`) scans **document bodies only** ("documents whose bodies
mention", §10.2 — CRs and other terms are out), matching the name and aliases
case-insensitively with `(?<!\w)…(?!\w)` boundaries (names like "C++" have
non-word edges, so `\b` would misbehave). Informational, no edges. (4) `term
rename` rewrites the H1 and the sidecar (`term`, `slug`) and moves
`glossary/<old>.*` → `glossary/<new>.*` (two-step for case-only renames on
case-insensitive filesystems); it lists body mentions of the old name/aliases
and never rewrites prose (human-owned). The stored `body_hash`/`version` are
left stale on purpose: the H1 change is an effective content change (§7.3)
and the bump belongs to the reconcile pass (§7.5), exactly like editing a
document title by hand. A rename to the identical name is a no-op notice; the
old name is not kept as an alias. (5) `term add` renders the repository's
`term` template (pinned in the sidecar "for uniformity", B.3) and allows a
deprecated template version — unlike documents there is no `migrate` path out
of a deprecated term template. Blank names/aliases are `ValueError`; refusals
use `E-TERM-SLUG`/`E-TERM-ALIAS-CLASH`/`E-TEMPLATE-UNKNOWN` plus the
refusal-only `E-TERM-UNKNOWN` (docs/backlog.md).

### D-S16-MERMAID

Rendering and scope choices for the §15 Mermaid export.
(1) Conflict edges are red as `linkStyle <indices> stroke:#ff0000`, one
statement with all conflict-edge indices in emission order (edges sorted by
`(source, type, target)`, nodes sorted by ID — deterministic output for golden
tests). (2) The dashed `classDef` of §15 is one class named `stale`
(`stroke-dasharray: 5 5`) shared by deprecated and superseded nodes, assigned
via `class <ids> stale`. (3) Label escaping escapes `#` → `#35;` before
`"` → `#quot;` (Mermaid entity codes): escaping `#` is required for the
quote-escape scheme to be sound (`#quot;` in a title must not become a quote),
and nothing else is touched. (4) Title truncation is plain `title[:40]` (no
ellipsis). (5) Node kind `None` (unknown type) falls back to the rectangle
shape. (6) The diagram is the complete fenced block with trailing newline;
statements are not indented. (7) The §13.13 default edge scope (all directed
types plus `conflicts-with`, so `relates-to` is drawn only when requested via
`edge_types`) lives in `mermaid.py` so `export_mermaid` is self-contained;
`--types` filtering is the caller's job (the `Graph` carries kinds, not type
names). (8) The >300-node warning is `Finding(W-GRAPH-LARGE)` with subject
`Path("graph")` and a `--root` fix suggestion (backlog SPEC-QUESTION).
(9) Unknown `roots` raise `ValueError` (caller resolves user IDs first,
matching `Graph.check_link`'s caller-bug precedent).

### D-S17-CLI

CLI-layer semantics the spec leaves open. (1) `--repo PATH` is
strictly the repository root ("override root discovery", §13): PATH must
contain `.gregraph/config.toml`, otherwise exit 3 — without `--repo` the root
is discovered upward from the current directory as usual. (2) `init` runs
`git init -b <baseline-branch>` so the new repository's branch matches the
`--baseline-branch` written to config (falls back to plain `git init` and
reports a notice if `-b` is rejected). (3) `edit`/`new --edit` read
`$VISUAL` then `$EDITOR` (shlex-split, so flags are allowed); a missing or
non-zero-exiting editor is an environment error (exit 3), and `edit` prints
nothing on success. (4) Interactive prompts appear only when stdin is a TTY
and `--no-input` is absent; cancelled pickers (`q`) and missing required
inputs in non-interactive mode are usage errors (exit 2). (5) `main()`
returns exit codes for command outcomes, while argparse's `--help`/`--version`
raise `SystemExit(0)` (S0 contract in tests/test_scaffold.py); argparse usage
errors are converted to exit-2 returns via a custom `ArgumentParser.error`.
(6) JSON output uses the canonical sidecar shape (indent 2, sort keys,
trailing newline); `list --json` emits a bare array of sidecars plus derived
`status`/`kind`, `show --json` one object (sidecar + `status`/`kind` +
`outbound`/`inbound`/`upstream`/`downstream` + `template_info`). (7)
`OperationRefused` findings print to stderr as `E-CODE subject: message
(fix: …)` and map to exit 4; ValueError maps to exit 2, OSError and missing
repositories to exit 3, NotImplementedError (not-yet-written S18/S19 command
modules) to exit 5.

### D-PACKAGE-SPLIT

Supersedes the single-distribution packaging of spec §16.4 by explicit user
instruction (lockstep versions, currently 0.2.0). (1) Two distributions under
`packages/`: `gregraph-core` (library, runtime deps unchanged) and `gregraph-cli`
(console script, `python -m gregraph`, depends on `gregraph-core==<same version>`).
The import names `gregraph.core`, `gregraph.cli`, `from gregraph import __version__`
and the `gregraph` command are preserved. (2) The shared `gregraph` namespace is a
regular package: `packages/core/src/gregraph/__init__.py` owns `__version__` and
calls `pkgutil.extend_path`; `gregraph-cli` ships no `__init__.py` at that level,
so the wheels install no overlapping files. PEP 420 implicit namespace packages
were rejected because they cannot provide `__version__` from `gregraph/__init__.py`
without a second owner of that file. (3) The root `pyproject.toml` is tooling-only
(no `[project]`): dev tools live in the `dev` dependency group, installed with
`python -m pip install --group dev -e packages/core -e packages/cli`, which needs
pip 25.1 or later. The quality gate uses `mypy --strict -p gregraph`, with both
source roots on `mypy_path`. (4) No root umbrella install is supported. Spike
verified: core-only imports and resources work; core-only CLI is unavailable
as intended. Published `pipx install gregraph-cli` is intended usage and was not
verified against an index. (5) Dev tooling: the root `dev` group carries
`hatchling`, the existing build backend, so local `--no-build-isolation` wheel builds
work; it is a development dependency only, not a new runtime dependency.

### D-WEBUI

Optional local web UI, specified by spec §21 (Amendment A1, revision 0.3,
authorised 2026-10-14). It is an extension to the v0.1 scope, not a milestone,
and carries no tag. (1) **Third distribution.** `gregraph-webui` lives in
`packages/webui` and is versioned in lockstep (0.2.0). It is separate so that
the two baseline distributions keep their runtime dependency set closed
(D11, BOOT-201): `pydantic`, `jinja2`, `markdown-it-py` and `mdit-py-plugins` for
core, nothing new for the CLI. Only `gregraph-webui` adds `fastapi` and
`uvicorn`. Users who never run `serve` never install them. (2) **Discovery by
entry point.** The CLI learns whether `serve` exists from the `gregraph.serve`
entry-point names, read with `importlib.metadata`, and imports the launcher
only after `serve` is selected. `--host` and `--port` are validated by the
argument parser, so `--help` and bad arguments never load the web UI. (3)
**Compiled bundle checked in.** The React, TypeScript and Tailwind (Vite) build
output is committed under `packages/webui/src/gregraph/webui/static/`, so pip
installs need no Node.js. CI enforces the bundle: a frontend job on Node 22 and
24 runs tests and typecheck, and on Node 22 it builds and fails on any drift of
the static directory (`docs/webui.md`). Node.js 22.12 or later (Node 22 LTS or Node 24 recommended) is needed only for
frontend development. (4) **Loopback-only, foreground.** `serve` accepts only
`127.0.0.1`, `localhost` and `::1`, defaults to port 8765, prints a plain
banner with the local URL (the user opens it; no browser launch), and stops on
Ctrl-C with exit 0. It is not a daemon, so the spec's "no daemon" stance (§1.2)
still holds in spirit. (4a) **Guards.** Every HTTP request, including the static
page and assets, passes three checks before routing. Host: exactly one header,
naming exactly `127.0.0.1`, `localhost` (case-insensitive) or `::1`. A header without a port means the HTTP default, 80.
When `serve` starts the app, the header's effective port (explicit, or 80 when
absent) must equal the bound port, so a server on port 80 accepts the bare names
browsers send and a server on 8765 accepts only `:8765`. An app created without
a port (tests, programmatic use) accepts any valid port. Origin: if present, exactly `http://` plus the request's
own `Host` value. Fetch-Site: if present, `same-origin` or `none`. A refusal is
403 `E-REQUEST-REFUSED`. (4b) **Token.** `create_app` owns a per-instance token,
held in memory and never logged, printed or put in a URL. `serve` neither
generates nor imports it. `GET /api/session` needs no token and returns the
token as `csrf_token`. Mutating requests need exactly one matching
`X-GREGraph-Token`, checked in constant time, else 403 `E-TOKEN-INVALID`. The
guards and token defend against browser pages from other origins (cross-site
request forgery, DNS rebinding). They do not defend against local OS users or
processes running as the same user, which can already access the repository
directly. This is a browser-origin guard, not authentication; the user asked for
no auth scheme beyond it. (5) **Body writes.** `update_body` is a core
operation, not a webui-only path, so the CLI and the web UI share one write
rule. It requires the normalised hash of the file on disk (`base_hash`) and
refuses with `E-BODY-STALE` on mismatch. It refuses `E-BODY-MISSING` without
recreating the file. Structural problems (missing level-1 heading, front
matter) are reported as findings, and the text is still saved. Text is stored as
sent, changing only CRLF/CR to LF. The body is replaced through a same-directory
`<filename>.<hex>.tmp` file, flushed and synced, with mode bits copied and then
`os.replace`; ACLs and extended attributes are not preserved. The sidecar title
update is a separate, non-atomic write. `update_body` does not bump `version` or
`body_hash`, so the hook and `sync --bump` keep their meaning. `E-PATH-UNSAFE`
is raised before any read or write when a path component below the root is a
symbolic link or junction, or when a path would leave the root. (6)
**Concurrency is honest about its limit.** Requests are serialised in-process.
External writers are not locked (§1.2 "no locking" is kept outside the process).
The stale check and the writes are not one atomic compare-and-swap against
other processes, so external races, including between the body and sidecar
writes, remain possible. `base_hash` is a best-effort guard only. This is an accepted residual risk, not
a resolved one. (7) **Scope
of the first version.** Filters are `type`, `status` and `q` (title or ID text).
Links are chosen by the user and validated by core on submission; no
allowed-targets API exists. The graph returns the first 300 nodes in ascending
ID order with a truncation flag, and has no root or type filter. Git commit UI,
asset upload, CR and glossary editing, arbitrary file access and Markdown
rendering are excluded. Remote or multi-user use is unsupported.
(8) **Verification.** The required gate `mypy --strict -p gregraph` is kept as
written. CI also runs `mypy --strict -p gregraph -p gregraph.cli -p gregraph.webui`,
because the shared namespace is not reached through `-p gregraph` alone for the
optional packages. Packaging is checked by `tests/packaging_check.py`.

**D-AGENT-1 … D-AGENT-9 (agent readiness).** Recorded from
`AGENT_READINESS.md` (Amendment A2 to `docs/design.md`,
revision 0.4, confirmed by the project owner 2026-10-15). The amendment
makes the tool agent-*ready* rather than agent-*tolerated*: a coding agent
must be able to create, link, validate and read requirements through the CLI
without reading tool documentation, configuration files or source code, and
every interaction must be observable in exactly one parseable stream. The
nine decisions below are the resolved choices; each is restated here with
its reasoning in the style of the other entries. No new runtime dependency,
no server, no daemon: the whole change lives inside the existing dependency
footprint (D11) and leaves the optional web UI untouched.

### D-AGENT-1 (integration model)

An agent integrates with GREGraph through the local CLI and the core library
only — no MCP server, no LSP, no daemon, no watch mode, no network service
(§1.2, §21.3 stay authoritative). Agent readiness is delivered by six
capabilities instead: (a) a complete `--json` contract (D-AGENT-2), (b)
template-aware authoring plus the uncommitted-`v1` grace period
(D-AGENT-3/D-AGENT-4), (c) schema and rule introspection (D-AGENT-5), (d)
explicit prose mention syntax plus the freshness fix (D-AGENT-6/D-AGENT-7),
(e) single-call context packing (D-AGENT-8), and (f) automatic
`AGENTS.md`/`.agents/skills/gregraph/SKILL.md` scaffolding (D-AGENT-9).
Consequence: `--help`/`--version` remain plain-text argparse output; agents
discover the command surface via `gregraph schema --json` instead.

### D-AGENT-2 (universal `--json` contract)

Every command and subcommand accepts `--json` (the lifecycle exception
`serve` accepts and ignores it, §21.3). With `--json`, stdout carries
exactly one canonical JSON document and stderr is empty for exit codes
0–4 (exit 5 suppresses its traceback unless `GREGRAPH_DEBUG=1` is set — a
debugging escape hatch, not part of the contract). Exit 1 documents are
result-shaped (`validate` findings array, `check`/`hook pre-commit`
payloads); exits 2/3/4/5 produce one error envelope
`{"error": {code, exit_code, message, finding, details}}` on stdout, whose
`code` is the protocol code `E-USAGE`/`E-NO-REPOSITORY`/`E-ENV`/the refusal
code/`E-INTERNAL`. These protocol codes live only in the envelope — they are
not added to the §14 catalogue and never appear as findings. Warnings and
degraded-mode notes travel inside the payload as `notices`/`findings` arrays
instead of stderr lines; `--json` takes precedence over `--quiet`;
`--edit` and `--json` are mutually exclusive (exit 2). Consequence: an agent
parses one stream and never interleaves; human mode is unchanged.

### D-AGENT-3 (rich `new --json`, uncommitted-`v1` grace)

`new --json` returns a rich authoring payload — `md_path`, the body exactly
as written on disk, the template `sections` spec (heading, required,
placeholder, renamed_from) and the parsed sidecar — so the file-first
workflow (agent creates with `new --json`, then edits `md_path` with its
native Edit tool) needs no template lookup. On top of that, an item at
`version == 1` that is absent from Git `HEAD` is in the *initial-grace
state*: reconcile populates it in place (`version` stays `1`; hashes, title
and assets are refreshed), and its `effective_version` is `1`, so links
recorded against the uncommitted draft stay fresh across the initial
commit. This kills the "skeleton `v1` → real content lands as fake `v2`"
trap of the first hook commit. Degraded mode has no grace period (`sync` is
the versioning act there and bumps as before).

### D-AGENT-4 (template-guided authoring flags)

`new`, `supersede`, `cr new`, `term add` and `edit` accept
`--section "<Heading>=<Content>"`/`--section-file "<Heading>=<PATH|->"`
(per-section assembly; `new`/`supersede`/`edit` additionally accept the
whole-body pair `--body`/`--body-file`), plus `--strict` to refuse
empty-or-placeholder required sections at write time. Precedence: whole
body > sections > skeleton; headings are matched against the pinned
template exactly, trimmed and case-sensitive (`heading` first, then
`renamed_from`); sections assemble in canonical template order. Refusals
are self-describing: `E-SECTION-UNKNOWN` carries the full
`details.template_sections` (plus `given_heading`), the write-time
`E-SECTION-REQUIRED-EMPTY` carries `template_sections` and
`missing_required` — the next call can succeed without a template lookup.
Nothing is written on refusal. On `edit` (which has no `--title` flag) the
body's H1 is the title authority: a supplied whole body whose first
non-blank line is a level-1 heading is stored as sent and the sidecar
`title` is synchronised to it (`update_body` step 5, AGENT_READINESS §3.4
rule 8), while a whole body without an H1 gets the existing document title
prepended as `# <title>`. The `--section` required-section check runs on
the assembled body, so unmentioned required sections already filled on disk
are preserved verbatim (AGENT-016) and only empty-or-placeholder required
sections in the assembled body refuse `E-SECTION-REQUIRED-EMPTY`.
Consequence: CLI-first and file-first
authoring are equally first-class and equally versioned.

### D-AGENT-5 (self-discovery)

`gregraph schema [--type TYPE] [--json]` exposes the whole rulebook in one
call (config policies, types with kinds and templates, the five kinds, the
nine edge rules with their §6.1 guidance, active templates with sections,
the CR lifecycle); `template show --json` adds the resolved `sections` and
the template file's `path`; `link --candidates SOURCE [--type T]` exposes
the interactive picker's filtering (kind rule, target liveness, cycle
pre-exclusion) as data. Consequence: an agent never reads `config.toml`,
template JSON files or tool source to learn the rules, and never discovers
them by trial-and-error refusals.

### D-AGENT-6 (explicit mention syntax only)

Prose mentions are recognised **only** in explicit reference syntax:
`[[ID]]`, `[[ID|label]]`, or a Markdown link whose target matches the ID
pattern, resolves to a managed `.md` path whose stem matches it, or whose
link text matches it — case-sensitive canonical uppercase; bare ID-shaped
tokens in prose are never mentions, and code spans, fenced code and HTML
are excluded. This resolves the dogfooding false positives where
hyphenated prose ("multi-target", "baseline-branch") fired
`E-MENTION-UNKNOWN` and blocked commits. Consequence: validation is
trustworthy because it never fires on ordinary prose; repositories seeded
with bare-ID mentions lose those mentions (coverage shrinks to explicit
references) and must be re-checked on upgrade. `term usage` is unaffected
(name/alias matching, not ID matching).

### D-AGENT-7 (freshness against the effective version)

`E-LINK-VERSION-AHEAD` is measured against the target's **effective**
version, not the stored one: `target_version == effective_version` on a
target with unbumped modifications is the existing warning
`W-LINK-PENDING` (fix `gregraph sync --bump`), and only
`target_version > effective_version` is the error. This resolves the
long-standing contradiction where `link`/`link refresh` legitimately
recorded `version + 1` against an unbumped target and `validate` then
flagged the very state the tool had just created. With D-AGENT-3 the
effective version of an uncommitted `v1` draft is `1`, so the seeding-time
variant disappears as well; `W-LINK-PENDING` is suppressed for
initial-grace targets. Consequence: `validate` and `check`/`hook
pre-commit` agree on the same tree, and the hook's ad-hoc suppression of
these false positives becomes redundant.

### D-AGENT-8 (context packing)

`gregraph context <ID…> [--depth N] [--direction …]
[--include-terms|--no-include-terms]` packs one call with everything
needed to implement against the requested documents and CRs: full target
payloads with bodies and parsed sections, BFS neighbours with the
connecting edge, direction, depth and freshness state, glossary terms
occurring in the bundle bodies, and the findings affecting the bundle.
Supporting conveniences: `show` accepts multiple IDs (JSON array under
`--json`, `---`-separated in human mode; single-ID output unchanged) and
`list --body` adds full Markdown bodies to the `list --json` items.
Consequence: a ten-document context costs one tool call with freshness
attached, not ten `show` calls plus manual link chasing and glossary
lookup.

### D-AGENT-9 (agent scaffolding)

`gregraph init` writes `AGENTS.md` (a delimited managed block, following
the pre-commit hook's managed-block pattern: existing content preserved,
block appended or replaced in place, idempotent) and
`.agents/skills/gregraph/SKILL.md` (wholly tool-owned, rewritten only when
its content differs, the one file allowed YAML front matter). `repair
agents` rewrites both on demand and `sync` refreshes them as its last
step, so the instructions heal after a tool upgrade or config change.
Both files are static text generated in `core/agents.py` — never imported
or parsed by the tool. Consequence: every new agent session reads the
golden rules from the repository instead of re-deriving (or violating)
them; `hooks install` deliberately does not touch agent files (single
responsibility).

### D-TYPED-IDS (typed document identifiers, 0.2.0)

Implements spec r0.5 (design §4, §5.3, §7.2, §14; decision D20).
(1) **Typed canonical form.** Every ID is
`<PREFIX>-<ABBREVIATION>-<6-char Crockford body>` (e.g. `RE-FEAT-7F3K2Q`):
the configured repository prefix, the type's abbreviation and the
UUID-derived body. The body stays random; only the type segment is
semantic. (2) **Per-type abbreviation.** Every configured document type
declares a required `abbreviation` under `[types.<name>]`, matching
`[A-Z]{3,5}` and unique across types. Change requests always use the fixed,
reserved abbreviation `CHG` (`RE-CHG-3M9XA1`); `CHG` is not configurable and
no document type may use it. The shipped mapping is context CTX, goal GOAL,
epic EPIC, feature FEAT, user-story STORY, functional-requirement FUNC,
non-functional-requirement NFR, constraint CON, design DSGN, decision DEC,
test-case TEST, stakeholder STKH, assumption ASM; CR CHG. (3) **Immutability.**
An abbreviation is fixed once any document of that type exists; changing it
is `E-TYPE-ABBREVIATION-CHANGED`. The cache records the abbreviation (beside
the kind) so the change is detectable, and an unchanged abbreviation is
re-checked through `E-ID-DERIVATION` (prefix + abbreviation). A type with no
documents may still be re-abbreviated. (4) **Schema 2 hard cutover.** Config
schema becomes `2` (`config_schema = 2`); a schema-1 config is refused as an
environment error (exit 3) telling the user to run
`scripts/migrate_type_ids.py`. There is no dual-format period and no legacy
alias: two-segment IDs are rejected everywhere, and a schema-2 repository
that still contains one reports `E-ID-LEGACY`. (5) **Standalone migration
only.** Migration ships as `scripts/migrate_type_ids.py`, dry-run by
default, writing only with `--apply`, accepting custom-type
`--abbreviation TYPE=ABBR` and `--map-out PATH`, working on schema-1 configs
and deliberately **not importing gregraph** so it can run before the new
tool is installed. No `gregraph` command performs the rewrite. (6)
**Version-preservation rule.** The migration preserves every document/CR
`version`, every link `target_version` and every CR scope `base_version`; it
recomputes `body_hash`/`scope_hash` because identifier text changed. It is an
identifier rewrite, not a semantic content change — the one documented case
where a stored hash changes without a version bump. Old Git history and tags
are not rewritten. (7) **Rejected alternatives.** A purely random
type-agnostic ID (no type information), a configurable CR abbreviation, an
in-tool migration command, and legacy aliases for old IDs. Consequence:
humans and agents can tell a document's type from its ID, while the random
body still guarantees stability and collision behaviour; upgrading an
existing repository requires the documented one-time migration.
