# GREGraph CLI reference

Every command, flag, exit code and interactive behaviour of GREGraph v0.1.1,
plus the `serve` command of the optional `gregraph-webui` distribution.
The normative specification is `docs/design.md` §13; this document describes
the implemented surface. When the two disagree, the spec wins and this file
needs an update.

See `docs/concepts.md` for the underlying model (documents, links, versions,
change requests). Finding codes (`E-…`, `W-…`) are catalogued in
`docs/design.md` §14.

## General

### Invocation

```
gregraph [global options] <command> [subcommand] [args] [options]
```

Also available as `python -m gregraph`. Global options work before or after
the command. `gregraph` without a command prints help and exits 2;
`--help`/`--version` exit 0. The `serve` command exists only when the optional
`gregraph-webui` distribution is installed (see [`serve`](#serve)).

### Global options

| Option | Meaning |
|---|---|
| `--repo PATH` | Use PATH as the repository root instead of discovering it upward from the current directory. PATH must contain `.gregraph/config.toml`, otherwise exit 3. |
| `--no-input` | Never prompt. Missing required inputs become usage errors (exit 2). |
| `--json` | Machine-readable output. Every command and subcommand supports it; with it, stdout carries exactly one canonical JSON document (see [Output conventions](#output-conventions)). The `serve` command accepts and ignores it. |
| `-q`, `--quiet` | Suppress non-essential human output. `--json` takes precedence: `--json --quiet` still prints the JSON document. |
| `-v`, `--verbose` | Extra detail; an internal error prints its traceback. |
| `--version` | Print the tool version and exit. |
| `-h`, `--help` | Help for the command tree or the nearest subcommand. |

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Success. |
| `1` | Validation errors found, or the operation is blocked (`check`, `hook pre-commit`, `validate --strict` with warnings). |
| `2` | Usage error: bad flags, missing required input with `--no-input`, cancelled picker, `--edit` combined with `--json`. |
| `3` | No repository found or environment error (bad `--repo`, missing Git, editor failure, corrupt config). |
| `4` | Operation refused: cycle, edge-rule violation, refusal to overwrite, closed CR, and similar. The refusal finding is printed on stderr (human mode). |
| `5` | Internal error. |

`validate` exits 1 on errors, or on warnings when `--strict` is given.
`check` exits 1 when the pre-commit hook would block. `hook pre-commit`
exits non-zero to abort the commit. `status` always exits 0.

Under `--json` the exit codes map to documents, not stderr text: exit 1
prints the command's *result* document (findings array, check payload —
not an error), and exits 2/3/4/5 print one **error envelope**
`{"error": {code, exit_code, message, finding, details}}` on stdout with
empty stderr (see [Output conventions](#output-conventions)).

### Output conventions

- Findings are one per line on stdout (refusals on stderr), prefixed with the
  code and subject: `E-CYCLE RE-1 refines RE-2: … (fix: …)`. Warnings use
  `W-…`, errors `E-…`.
- Colours are used only when stdout is a TTY and `NO_COLOR` is unset.
- `note: not a git repository — <feature> unavailable` lines mark degraded
  mode (see below); at most one per feature per invocation.
- With `--json`, stdout is exactly one canonical JSON document
  (indent 2, sorted keys, trailing newline); human lines are suppressed.

The full `--json` contract:

- **One document, empty stderr.** With `--json` every command writes exactly
  one canonical JSON document to stdout and nothing else; stderr is empty for
  exit codes 0–4 (and for 5 unless `GREGRAPH_DEBUG=1` sends the traceback to
  stderr as a debugging escape hatch).
- **Success payloads** (exit 0) carry `findings` (non-fatal findings, `[]`
  when none) and `notices` (human-mode stderr warnings and degraded-mode
  notes, machine-readable here, `[]` when none) in addition to the command's
  own keys.
- **Exit 1 is a result, not an error.** `validate --json` emits the §14
  findings array; `check --json` and `hook pre-commit --json` emit their
  check payloads (with `blocked`, `block_reasons`, …). The document says
  *what was found*, so the process exit code carries the verdict.
- **Exits 2/3/4/5 produce an error envelope on stdout**:
  `{"error": {"code": …, "exit_code": …, "message": …, "finding": …,
  "details": …}}`. `code` is `E-USAGE` (exit 2; `details.usage` carries the
  argparse usage string when available), `E-NO-REPOSITORY` when root
  discovery fails or `E-ENV` otherwise (exit 3), the refusal's own finding
  code such as `E-CYCLE` (exit 4 — `finding` is the complete `Finding`,
  including its `details`, and `details` mirrors `finding.details`), or
  `E-INTERNAL` (exit 5). These four are *protocol* codes of the envelope
  only; they never appear as findings.
- Findings may carry an optional machine-readable `details` object
  (e.g. `template_sections` for authoring refusals, a cycle path for
  `E-CYCLE`); it is serialised whenever present.
- `--help`, `-h` and `--version` stay plain text (exit 0). `gregraph`
  without a command prints help and exits 2 — under `--json` this becomes an
  `E-USAGE` envelope with the help text in `details.usage`.

### Interactivity

Prompts appear only when stdin is a TTY and `--no-input` is absent. Every
prompt has a flag equivalent — passing the flag skips the prompt. Missing
required input in non-interactive mode is a usage error (exit 2).

Pickers show a numbered list (ID, type, title, status) and accept:

- a displayed number;
- an exact ID (case-insensitive, searched in the full row set);
- a filter string that refines the displayed list;
- `q` to cancel (a cancelled single pick is a usage error; see per-command
  notes for multi-pick and optional pickers).

Text prompts repeat while a required value is empty; an empty line accepts
the default when one is shown.

### Editors

`--edit` flags and `edit` open the Markdown in `$VISUAL`, else `$EDITOR`
(shlex-split, so editor flags are allowed). A missing editor or a non-zero
editor exit is an environment error (exit 3).

An interactive editor cannot be part of a machine-readable call: `--edit`
and `--json` are mutually exclusive (usage error, exit 2), and `edit --json`
without content flags is likewise a usage error.

### Degraded mode

Without Git (no `git` on `PATH`, or the root is not a repository) every
command works, but draft/active status is reported as `unknown`, version
bumps happen in `gregraph sync`, and Git-only features print a single
`note:` line. Configured policies come from `.gregraph/config.toml`
(appendix B.1 of the spec): `versioning.on_outdated_links`,
`versioning.on_cr_modified`, `graph.open_conflicts`, `cr.enabled`.

---

## Commands

### `init`

```
gregraph init [PATH] [--prefix RE] [--baseline-branch BRANCH]
              [--templates all|minimal] [--no-git]
```

Creates a requirements repository: the directory layout, built-in templates
under `.gregraph/templates/<name>/v1/`, `config.toml` with the default
document types, `.gitignore`, and a starter `README.md`. It also writes the
agent instruction files: `AGENTS.md` — existing content is preserved and the
managed gregraph block is appended, or replaced in place when a block already
exists — and `.agents/skills/gregraph/SKILL.md`, wholly tool-owned and
rewritten only when its content differs. Both paths are printed
(`agents files written: …`) and reported as `agents_files` under `--json`.

| Argument/flag | Meaning |
|---|---|
| `PATH` | Directory to initialise (default: current directory). |
| `--prefix RE` | Document ID prefix (default `RE`). |
| `--baseline-branch BRANCH` | Baseline branch name written to config (default `main`). |
| `--templates all\|minimal` | Built-in templates to copy (default `all`; `minimal` = those the default config references). |
| `--no-git` | Skip `git init` and hook installation. |

Runs `git init -b <baseline-branch>` when PATH is not a Git repository,
unless `--no-git`, and installs the pre-commit hook. Refuses (exit 4) if
`.gregraph/` already exists.

### `new`

```
gregraph new [TYPE] [--title T] [--template NAME] [--template-version N]
             [--allow-deprecated] [--tag TAG]… [--link TYPE:TARGET]…
             [--cr CR]
             [--section "HEADING=CONTENT"]… [--section-file "HEADING=PATH|-"]…
             [--body TEXT | --body-file PATH|-] [--strict] [--edit]
```

Creates a document: generates the ID, renders the template, writes the
Markdown body and JSON sidecar, creates the initial links (each checked),
prints the ID and path.

| Argument/flag | Meaning |
|---|---|
| `TYPE` | Document type from `config.toml` (prompted as a picker). |
| `--title T` | Document title, i.e. the H1 (prompted). |
| `--template NAME` | Template name override for this document. |
| `--template-version N` | Pin this template version (default: latest non-deprecated). |
| `--allow-deprecated` | Permit creation on a deprecated template version. |
| `--tag TAG` | Add a tag; repeatable. Tags are `[a-z0-9-]+`. |
| `--link TYPE:TARGET` | Initial edge `TYPE:TARGET`; repeatable. Each is checked; a failed check aborts the creation. |
| `--cr CR` | Record the new document as introduced by CR (sets `origin_cr`, appends to the CR's `introduces`). |
| `--section "H=C"` | Provide section `H`'s content (repeatable); see below. |
| `--section-file "H=PATH"` | Provide section `H`'s content from a file, `-` for stdin (repeatable). |
| `--body TEXT` / `--body-file PATH\|-` | Replace the whole body; `-` reads stdin. |
| `--strict` | Refuse when a required section is empty or placeholder-only after assembly. |
| `--edit` | Open the Markdown in `$VISUAL`/`$EDITOR` afterwards. |

Interactive: type picker over configured types, title prompt, then an
optional `link (TYPE:TARGET, empty to finish)` loop when no `--link` was
given. Warns `W-NO-GIT-IDENTITY` when no Git identity is available for
`created_by`. Refuses `E-CR-DISABLED` when `--cr` is used with
`cr.enabled = false`; `E-CR-CLOSED` when the CR is `rejected`/`implemented`;
`E-CR-SCOPE-TARGET` when the CR does not know the ID. Unknown types refuse
`E-TYPE-UNKNOWN`.

**Authoring flags.** Precedence: whole-body (`--body`/`--body-file`) >
per-section assembly (`--section`/`--section-file`) > template skeleton.
`HEADING` is matched against the pinned template's sections — exact, trimmed,
case-sensitive, `heading` first then any `renamed_from` alias. Sections are
assembled in canonical template order; unmentioned sections keep their
template placeholder text, so `v1` hashes the real content, and the
uncommitted-`v1` grace period keeps the first commit at `version 1` (see
[`sync`](#sync)). The tool owns the H1: a differing level-1 heading in
`--body` input is replaced by `# <title>` (notice), a missing one is
prepended. Conflicting combinations (`--body` with `--section`, `--body` with
`--body-file`, the same heading twice, two stdin consumers) are usage errors
(exit 2); nothing is written on refusal. Unknown headings refuse
`E-SECTION-UNKNOWN` and a missing/empty required section refuses
`E-SECTION-REQUIRED-EMPTY` — both carry the template's full section
specification in the finding's `details` so the next call can self-correct.
Without the content flags, behaviour is unchanged (placeholders allowed at
creation; `validate` reports emptiness later).

**`new --json`.** Returns one rich payload: `id`, `uuid`, `type`, `kind`,
`md_path`, `json_path`, `template{name, version}`, `version`, `body_hash`,
`sections` (`heading`, `required`, `placeholder`, `renamed_from`), `body`
(the text exactly as written on disk — an agent can edit `md_path` directly),
`sidecar` (the parsed on-disk sidecar), `links`, `findings`, `notices`.
`body_hash` doubles as the `base_hash` of a later `edit` call.

### `link`

```
gregraph link [SOURCE] [TYPE] [TARGET]
gregraph link --candidates SOURCE [--type EDGE_TYPE]
```

Adds a directed or symmetric edge from SOURCE to TARGET. Records
`target_version` = the target's effective version (its `version`, plus one
when the target has unbumped modifications; `1` for an uncommitted `v1`
target in the initial-grace period).

Refusals (exit 4): `E-CYCLE` (would close a directed cycle, with the path),
`E-EDGE-RULE` (kind rule violated), `E-EDGE-EXCLUSIVE` (`refines` and
`derives-from` on the same pair), `E-TARGET-SUPERSEDED`,
`E-TARGET-DEPRECATED` (target dead; `supersedes` is the exception).
A duplicate edge is a notice and exit 0. Unknown IDs refuse `E-ID-UNKNOWN`.

Interactive: pick source (all nodes), pick type (only types whose source-kind
rule the source satisfies), pick target (only nodes the kind rule allows,
which are not deprecated/superseded and would not create a cycle — computed
before the picker runs).

`gregraph link --help` prints the edge-type guidelines (spec §6.1).

**`--candidates`.** `link --candidates SOURCE [--type EDGE_TYPE]` answers
"what may I link from here" without linking: it applies the interactive
picker's filtering (kind rule, target liveness, cycle pre-exclusion) and
under `--json` returns `{source, source_kind, allowed_edge_types,
candidates: [{type, target, target_title, target_type, target_kind}]}`,
sorted by `(type, target)`. `allowed_edge_types` is `[]` when the source
kind permits no edge type; without `--type`, candidates for every admissible
type are listed. Mutually exclusive with the positional `TARGET`. Unknown
edge type is a usage error; unknown source refuses `E-ID-UNKNOWN`.

### `unlink`

```
gregraph unlink [SOURCE] [TYPE] [TARGET]
```

Removes the edge. Symmetric edges are found on either endpoint, so
`unlink A relates-to B` and `unlink B relates-to A` both work. Interactive
pickers for any missing argument.

### `link refresh`

```
gregraph link refresh [SOURCE TYPE TARGET | --from ID | --to ID | --all]
                      [--follow] [--dry-run]
```

Sets `target_version` to the target's effective version for the selected
links. Exactly one selection: the edge triple, `--from ID` (all outbound
links of ID), `--to ID` (all inbound links of ID — the common case after
editing ID), or `--all`.

| Flag | Meaning |
|---|---|
| `--follow` | Re-point stale links to the successor (end of the `supersedes` chain). |
| `--dry-run` | Report what would change; write nothing. |

Stale links (target superseded): with `--follow` they are re-pointed; if the
succession chain forks, the command refuses `E-SUPERSEDE-FORK` under
`--no-input` or offers the successors interactively. Without `--follow` the
link is left untouched and listed with its supersession chain (interactive
sessions get a successor picker). `supersedes` and `conflicts-with` links
are never re-pointed. For deprecated targets, refresh refuses
(`E-TARGET-DEPRECATED`) and suggests `unlink` or re-linking elsewhere.

Interactive with no selection: link picker over all links. Cancelled stale
picker: the link is left untouched.

### `set`

```
gregraph set [ID] [key=value…]
```

| Key | Syntax | Effect |
|---|---|---|
| `tags` | `tags=a,b` | Replace the tag list. |
| | `tags+=x` | Add a tag. |
| | `tags-=x` | Remove a tag. |
| `extra` | `extra.name=value` | Set an extra field. |
| | `extra.name=` | Remove an extra field. |

Everything else is refused `E-SET-KEY` with a pointer to the right command
(`title` → edit the H1; `type` → `supersede`; `status` → `cr set`). Malformed
assignments refuse `E-SET-VALUE`; bad tags `E-TAG-INVALID`; unknown IDs
`E-ID-UNKNOWN`. Interactive: document picker, then an assignment loop.

### `sync`

```
gregraph sync [--bump]
```

Reconciles everything (spec §7.5): normalises line endings, rewrites
non-canonical sidecars, rebuilds the cache. Versions are bumped in degraded
mode, or in Git mode only with `--bump` (the pre-commit hook normally does
the bumping). Reports bumped documents, **initialised** items (uncommitted
`v1` documents, CRs and terms populated in place during the initial-grace
period — the version stays `1`), newly/already outdated links, stale
and pending-outdated links, and validation findings. As its last step
`sync` refreshes `AGENTS.md` and `.agents/skills/gregraph/SKILL.md`,
writing only files whose content differs; `--json` lists them under
`agents_files_changed`.

### `check`

```
gregraph check [--json]
```

"What would the hook say": the pre-commit simulation over all working-tree
changes (staged or not), report-only. Exits 1 when the hook would block —
validation errors, or newly outdated links while
`versioning.on_outdated_links = "block"`. `--json` emits
`{blocked, block_reasons, would_bump, initialised, findings,
newly_outdated, previously_outdated, stale, pending, refresh_commands}` —
`initialised` lists the uncommitted `v1` items the commit in progress would
populate in place (version stays `1`).

### `validate`

```
gregraph validate [--strict] [--only-errors] [--json]
```

Full validation (the spec §14 catalogue). Intended for CI.

| Flag | Meaning |
|---|---|
| `--strict` | Treat warnings as errors for the exit code. |
| `--only-errors` | Display errors only; the exit code still sees the full report. |
| `--json` | Emit `[{code, severity, id\|path, message, fix?, details?}]` (`fix` is a suggested command where one exists; `details` is the optional machine-readable context, e.g. `template_sections` or a cycle path). |

Exits 1 on errors (or warnings with `--strict`), else 0. Freshness is
measured against the target's **effective** version: a link confirmed
against an unbumped target is `W-LINK-PENDING` (fix: `gregraph sync --bump`),
not `E-LINK-VERSION-AHEAD`; only `target_version` beyond the effective
version is the error. Explicit mentions (`[[ID]]`, `[[ID|label]]`, Markdown
links to an ID or a managed `.md` path) are the only mentions checked — bare
ID-shaped words in prose are never mentions.

### `list`

```
gregraph list [--type T]… [--kind K]… [--status S]… [--tag t]…
              [--roots] [--orphans] [--outdated] [--stale]
              [--deprecated-templates] [--sort id|title|created|version]
              [--body] [--json]
```

Tabular output: ID, type, status, version, title. Filters are repeatable and
combine as OR within a category, AND across categories.

| Flag | Meaning |
|---|---|
| `--type T` / `--kind K` / `--status S` / `--tag t` | Filter by type, kind, derived status, or tag. |
| `--roots` | Only root documents (no outbound `refines`/`derives-from`). |
| `--orphans` | Only orphans (no edges at all). |
| `--outdated` | Documents with at least one outdated outbound link. |
| `--stale` | Documents with at least one stale outbound link. |
| `--deprecated-templates` | Documents pinned to a deprecated template version. |
| `--sort id\|title\|created\|version` | Sort key (default `id`). |
| `--body` | Include each item's full Markdown body in the `--json` payload (additive `body` key). Ignored in human mode — the table is unchanged. |
| `--json` | Array of sidecars plus derived `status` and `kind` fields. |

### `show`

```
gregraph show [ID…] [--body] [--depth N] [--json]
```

Prints one document: sidecar fields, derived status, outbound and inbound
edges with freshness (`target_version / effective`, state), one level of
upstream (hierarchical edges to this document), the downstream tree
(documents that transitively link here over directed edges), assets, and
template info. If ID is a CR, delegates to `cr show`.

**Multiple IDs.** `show` accepts several IDs. One ID keeps today's output
exactly. Multiple IDs: human mode prints the documents sequentially,
separated by a blank line and `---`; `--json` emits a JSON array of the
per-document payloads (a CR ID yields its `cr show` payload as an entry).
Duplicate IDs are de-duplicated preserving first-seen order; any unknown ID
aborts with `E-ID-UNKNOWN` before any output (all-or-nothing).

| Flag | Meaning |
|---|---|
| `--body` | Also print the Markdown body (JSON: add a `body` field). |
| `--depth N` | Limit the downstream tree depth (default: unlimited). |
| `--json` | One object (single ID) or an array (multiple IDs): sidecar + `status`/`kind` + `outbound`/`inbound`/`upstream`/`downstream` + `template_info`. |

Interactive: document picker when ID is missing.

### `status`

```
gregraph status [--json]
```

Repository overview; always exits 0. Prints the WIP header
(`WIP: yes (3 drafts, 1 modified)` / `WIP: no`), counts of documents by
status, drafts (with paths), modified-unbumped documents, outdated/stale/
pending-outdated links, open `conflicts-with` pairs, documents on deprecated
template versions, CRs by effective status, CRs with pending decisions
(proposed ≠ effective), CRs with drift, hook installation state, and whether
the repository is degraded. Uncommitted, modified `v1` documents that have
inbound links are additionally listed under a
`pending initial version (v1 with inbound links): …` note — their status
stays `draft`; no new status is invented. `--json` emits the same as a
structured payload, carrying the noted IDs under `pending_initial_version`
when the list is non-empty.

### `graph`

```
gregraph graph [--root ID]… [--depth N] [--types t,…] [--edges e,…]
               [--include-superseded] [--direction TD|LR] [-o FILE] [--json]
```

Emits a Mermaid `flowchart` (spec §15) on stdout or to FILE. Default scope:
all non-superseded, non-deprecated nodes; all directed edges plus
`conflicts-with`.

| Flag | Meaning |
|---|---|
| `--root ID` | Root of the exported scope; repeatable. |
| `--depth N` | Depth limit downstream of the roots (only meaningful with `--root`). |
| `--types t,…` | Comma-separated type filter. |
| `--edges e,…` | Comma-separated edge-type filter. |
| `--include-superseded` | Also include superseded and deprecated nodes (dashed border). |
| `--direction TD\|LR` | Flowchart direction (default `TD`). |
| `-o FILE` | Write to FILE instead of stdout. |
| `--json` | `{diagram, findings}`. |

Warns `W-GRAPH-LARGE` above 300 nodes and suggests `--root`/`--types`.

### `schema`

```
gregraph schema [--type TYPE] [--json]
```

Prints the repository rulebook in one call — what the repository allows,
without reading `config.toml` or template files: the config policies (ID
prefix, baseline branch, `versioning`, `graph`, `assets` and `cr` settings),
the configured types (kind, folder, template, ID prefix, description), the
five kinds, the nine edge rules (direction, hierarchical, acyclic, source/
target kind sets, `same_kind_only`, mutual exclusions, and the §6.1
guidance as each rule's description), the active templates with their
required sections and placeholders, and the CR lifecycle (statuses,
transitions, scope intents).

| Flag | Meaning |
|---|---|
| `--type TYPE` | Filter `types` to one type and `templates` to those its entries reference (plus the CR template when CRs are enabled). The global sections (`kinds`, `edge_rules`, `cr_lifecycle`, policies) stay. Unknown type refuses `E-TYPE-UNKNOWN`. |
| `--json` | One object mirroring the human output: `schema`, `tool_version`, `id_prefix`, `baseline_branch`, `versioning`, `graph`, `assets`, `cr`, `types`, `kinds`, `edge_rules`, `templates` (with `sections`), `cr_lifecycle`. |

Useful before any authoring or linking call: `schema --json` is the
authoritative answer to "which edge types may this document use and which
sections must I fill?".

### `context`

```
gregraph context ID… [--depth N] [--direction both|upstream|downstream]
                     [--include-terms|--no-include-terms] [--json]
```

One call packing the reading context for one or more documents or CRs
(mixed allowed): the requested documents with their full bodies and parsed
sections, their neighbours up to depth `N` (default 1) with the connecting
edge, direction, depth and freshness state, the glossary terms occurring in
those bodies (included by default), and the validation/freshness findings
affecting the bundle.

| Argument/flag | Meaning |
|---|---|
| `ID…` | One or more document and/or CR IDs; an unknown ID refuses `E-ID-UNKNOWN` naming the offender. |
| `--depth N` | Neighbourhood depth (default 1, `N ≥ 0`). |
| `--direction both\|upstream\|downstream` | Which edges to follow (default `both`). |
| `--include-terms` / `--no-include-terms` | Glossary term scan on/off (default: on). |
| `--json` | One bundle object: `requested`, `depth`, `direction`, `targets` (full `show`/`cr show` payloads + `body` + `sections`), `neighbors` (`id`, `via`, `direction`, `depth`, `freshness`, `sidecar`, `body`), `terms` (`term`, `slug`, `aliases`, `body`), `findings`. |

Human mode prints one combined Markdown document (targets with bodies and
edges, neighbours, then a `## Glossary` section; `---` separators; no colour
codes) suitable for pasting to an LLM. Superseded and deprecated neighbours
are included — they matter for reading context. Lighter alternatives:
`show ID… --json` (multiple IDs) and `list --type T --body --json`.

### `supersede`

```
gregraph supersede [OLD…] [--title T] [--type TYPE]
                   [--copy-body|--no-copy-body] [--copy-links|--no-copy-links]
                   [--cr CR]
                   [--section "HEADING=CONTENT"]… [--section-file "HEADING=PATH|-"]…
                   [--body TEXT | --body-file PATH|-] [--strict] [--edit]
```

Creates a new document that replaces one or more old ones (spec §7.6):
edge `NEW supersedes OLD` per target; multi-target (`supersede A B`) is the
conflict-compromise pattern.

| Flag | Meaning |
|---|---|
| `--title T` | Title of the new document (prompted interactively). |
| `--type TYPE` | Type of the new document (same kind as the targets; default: the targets' common type). |
| `--copy-body` / `--no-copy-body` | Copy the old body (default on when the template resolves identically). |
| `--copy-links` / `--no-copy-links` | Copy the old outbound links, with their `target_version` values (default on). Failing copies are skipped and listed. |
| `--cr CR` | Record the new document as introduced by CR. |
| `--section` / `--section-file` / `--body` / `--body-file` / `--strict` | Same authoring flags as [`new`](#new), applied to the new document (unmentioned sections keep their template placeholders, as on `new`; whole-body input makes the created `v1` hash the real content). |
| `--edit` | Open the new document afterwards. |

Inbound links of OLD are left untouched; they become stale and are listed
with the exact `gregraph link refresh … --follow` commands to re-point them.
If OLD is outside the CR's scope, a notice suggests
`gregraph cr scope add CR OLD --intent supersede` (scope is never changed
implicitly). Interactive: multi-target picker (repeated picks, `q` to
finish).

### `deprecate` / `undeprecate`

```
gregraph deprecate [ID] [--reason R]
gregraph undeprecate [ID]
```

`deprecate` sets the one stored status flag with a reason; inbound links
become stale and are listed. `undeprecate` clears the flag. Deprecated
documents cannot be targets of new directed edges except `supersedes`
(`E-TARGET-DEPRECATED`). Interactive: document picker; `deprecate` prompts
for the reason when `--reason` is missing.

### `migrate`

```
gregraph migrate [ID… | --all | --template NAME] [--to VERSION]
                 [--supersede] [--dry-run]
```

Migrates documents between template versions (spec §7.7). Exactly one
selection: document IDs, `--all`, or `--template NAME` (documents pinned to
that template). With no selection, interactive multi-pick (repeated picks,
`q` to finish).

| Flag | Meaning |
|---|---|
| `--to VERSION` | Target template version (default: latest non-deprecated). |
| `--supersede` | Force a superseding migration (default: in-place when every step is non-breaking). |
| `--dry-run` | Print the plan without writing. |

In-place migration inserts missing sections (and applies `renamed_from`);
superseding migration creates a new document, copies matching sections, puts
unmatched content under `## Unmapped content (migration)`, supersedes the
old one and copies its links. Either way, the change is a content change and
inbound links become outdated — the correct "re-check" signal.

### `template`

```
gregraph template list
gregraph template add BUILTIN
gregraph template bump NAME [--breaking]
gregraph template show NAME [--version N]
```

| Subcommand | Meaning |
|---|---|
| `list` | Template names, versions, deprecated flags, document counts per version. |
| `add BUILTIN` | Copy a built-in template into the repository as `v1` (or the next version if the name exists). |
| `bump NAME` | Copy the latest version forward to the next version number; the user then edits the new files. `--breaking` marks the new version as breaking (so later in-place migrations across it refuse). |
| `show NAME` | Print the descriptor and skeleton of a version (`--version N`, default latest). Under `--json` the payload includes the resolved `sections` (`heading`, `required`, `placeholder`, `renamed_from`, in descriptor order) and the repository-relative `path` of the version's `template.md`. |

Users may edit a version's files only to set `deprecated` and `description`;
changing `sections` of a version with documents pinned to it is
`E-TEMPLATE-MUTATED` — create a new version with `template bump` instead.

### `cr`

Change requests (spec §9). Every `cr` subcommand refuses `E-CR-DISABLED`
when `cr.enabled = false`.

```
gregraph cr new [--title T] [--scope TARGET[:INTENT]]… [--external-ref R]
                [--section "HEADING=CONTENT"]… [--section-file "HEADING=PATH|-"]…
                [--strict] [--edit]
gregraph cr scope add CR TARGET [--intent modify|supersede|deprecate]
gregraph cr scope remove CR TARGET
gregraph cr set CR [key=value…]
gregraph cr reaffirm CR
gregraph cr reanalyze CR [TARGET…]
gregraph cr list [--status S]… [--effective] [--pending] [--drift]
gregraph cr show CR
```

| Subcommand | Meaning |
|---|---|
| `cr new` | Create a CR in status `open` from the `cr.template` template. `--scope TARGET[:INTENT]` (repeatable) adds scope entries; intent defaults to `modify`. `--external-ref R` stores an issue key or PR URL. `--section`/`--section-file`/`--strict` are the same authoring flags as [`new`](#new) (no whole-body pair; unmentioned sections keep their placeholders). `--edit` opens the body. Title is prompted when missing. |
| `cr scope add` | Add a scope entry. The target must be a live document that exists on the baseline branch; `base_version` is recorded from there. Violations refuse `E-CR-SCOPE-TARGET`. |
| `cr scope remove` | Remove a scope entry. |
| `cr set` | Set fields: `status` (appends a decision; transitions per spec §9.3), `branch`, `external_ref`, `tags=`/`tags+=`/`tags-=`, `extra.name=`. Invalid transitions refuse `E-CR-STATUS`; setting the current status points at `cr reaffirm`. |
| `cr reaffirm` | Append a decision confirming the current status at the current effective version (resolves `W-CR-MODIFIED-AFTER-DECISION`). |
| `cr reanalyze` | Reset `base_version` to the current baseline version for the given entries (or all). This changes the CR's content; a decided CR needs a reaffirm afterwards. Fixes drift. |
| `cr list` | List CRs. `--status` filters on proposed status (effective with `--effective`); `--pending` selects CRs whose proposed and effective status differ; `--drift` selects CRs with drift. |
| `cr show` | Impact view (spec §9.8): proposed/effective status, decision history, scope entries with base/baseline/working-tree versions and drift, introduced documents, and the impact set (1 level upstream + unlimited downstream per scope target). |

`new … --cr` and `supersede … --cr` refuse `E-CR-CLOSED` when the CR's
proposed status is `rejected` or `implemented`.

### `repair`

```
gregraph repair versions
gregraph repair regenerate-id PATH
gregraph repair cache
gregraph repair agents
```

| Subcommand | Meaning |
|---|---|
| `versions` | After a merge conflict in sidecars: parse conflict markers, set `version = max(versions seen) + 1`, recompute hashes, clamp `target_version` values. Reports "no conflicted sidecars found" on a clean tree. |
| `regenerate-id PATH` | Fix an ID collision (spec §4.4): derive a fresh ID for the document at PATH and rewrite links that unambiguously reference the old one from this branch's history; the rest is listed for manual re-linking. |
| `cache` | Delete and rebuild the index cache. |
| `agents` | Rewrite the agent instruction files idempotently: the `AGENTS.md` managed block is replaced in place (existing content otherwise untouched) and `.agents/skills/gregraph/SKILL.md` is rewritten only when its content differs. `--json` emits `{agents_files, changed, findings, notices}`. Run it after a tool upgrade or config change; [`sync`](#sync) also refreshes the files. |

Merge-conflict guidance (spec §12.6): resolve body conflicts as prose; for
sidecars, resolve to any syntactically valid JSON (or leave the markers) and
run `repair versions`; keep both sides of duplicated links —
`repair versions` de-duplicates.

### `term`

Glossary terms (spec §10) live in `glossary/`, outside the graph.

```
gregraph term add "Term" [--alias A]… [--section "HEADING=CONTENT"]…
                   [--section-file "HEADING=PATH|-"]… [--strict] [--edit]
gregraph term list
gregraph term show SLUG
gregraph term usage SLUG
gregraph term rename SLUG "New term"
gregraph term deprecate SLUG [--reason R]
```

| Subcommand | Meaning |
|---|---|
| `add` | Create `glossary/<slug>.md` + `<slug>.json` from the `term` template. The slug is derived from the term (lowercase, non-alphanumerics → `-`). `--alias` is repeatable. `--section`/`--section-file`/`--strict` are the same authoring flags as [`new`](#new) (no whole-body pair). |
| `list` | All terms with aliases and deprecation state. |
| `show SLUG` | The term's sidecar fields and body. |
| `usage SLUG` | Documents whose bodies mention the term or one of its aliases (case-insensitive, word-boundary). Informational; no edges. |
| `rename SLUG "New term"` | Rewrites the H1 and sidecar and moves the files. Never rewrites mentions in bodies (prose is human-owned) but lists them. |
| `deprecate SLUG` | Set `deprecated` with a reason (prompted when missing). |

Alias clashes refuse `E-TERM-ALIAS-CLASH`; slug problems `E-TERM-SLUG`;
unknown slugs `E-TERM-UNKNOWN`.

### `baseline`

```
gregraph baseline create NAME [-m MSG]
gregraph baseline list
```

A baseline is an annotated Git tag `baseline/<name>` whose message contains
a generated manifest (spec §12.4): per-document ID, version, body hash and
status, plus the ID prefix and tool version. `create` refuses
`E-BASELINE-UNCOMMITTED` when managed files are uncommitted,
`E-BASELINE-INVALID` when `validate` reports errors, `E-BASELINE-EXISTS`
when the tag exists, and `E-GIT-UNAVAILABLE` in degraded mode.

### `hooks`

```
gregraph hooks install
gregraph hooks uninstall
gregraph hooks status
```

`install` writes `.git/hooks/pre-commit` (creating the file, or appending a
delimited block if one exists) so that commits run `gregraph hook
pre-commit`; `uninstall` removes the block; `status` reports whether the
hook is installed and up to date.

### `hook pre-commit` (internal)

```
gregraph hook pre-commit
```

The hook body, hidden from `--help` and invoked by the Git hook. Scope =
staged files under `documents/`, `changes/`, `glossary/` plus documents with
staged asset changes. Bumps versions for staged content, re-stages the
rewritten sidecars, and aborts the commit (exit non-zero) on validation
errors, or on links newly outdated by this commit while
`versioning.on_outdated_links = "block"` (the report prints the exact
`gregraph link refresh …` commands that resolve it). Uncommitted `v1` items
are populated in place instead of bumped (version stays `1`, `initialised`
bucket) — the first commit of a document is its real first version. Warnings
never abort.
`versioning.on_cr_modified = "block"` additionally aborts on
`W-CR-MODIFIED-AFTER-DECISION`. Escape hatch: `git commit --no-verify`.

### `edit`

```
gregraph edit ID [--section "HEADING=CONTENT"]… [--section-file "HEADING=PATH|-"]…
                 [--body TEXT | --body-file PATH|-] [--strict]
```

Without content flags: opens the Markdown body in `$VISUAL`/`$EDITOR`
(prompted picker when ID is missing). Convenience only; prints nothing on
success.

With content flags the tool performs the edit instead of an editor:
`--body`/`--body-file` replace the whole body through the same
`update_body` operation the web UI uses (`base_hash` is taken from the
on-disk body immediately before writing, so a body changed on disk since it
was read refuses `E-BODY-STALE`); `--section`/`--section-file` assemble
per-section content, preserving unmentioned sections verbatim (extra
level-2 sections stay at the end); `--strict` refuses when a required
section is empty or placeholder-only after assembly. Heading matching,
precedence, stdin rules and the self-describing refusals
(`E-SECTION-UNKNOWN`, `E-SECTION-REQUIRED-EMPTY`) are as for
[`new`](#new); nothing is written on refusal. `edit --json` without any
content flag is a usage error (exit 2).

`edit` has no `--title` flag. On `--body`/`--body-file` the supplied text's
level-1 heading is the title authority: when the first non-blank line is a
`# Heading`, the sidecar `title` is synchronised to it (`update_body`
step 5); when the supplied text has no level-1 heading, the existing
document title is prepended as `# <title>` (the tool owns the H1). On
`--section`/`--section-file` the required-section check runs on the
assembled body: unmentioned required sections that are already filled on
disk are preserved verbatim, and only required sections that are empty or
placeholder-only after assembly trigger `E-SECTION-REQUIRED-EMPTY`.

### `serve`

```
gregraph [global options] serve [--host HOST] [--port PORT]
```

Starts the local web UI in the foreground. **Available only when the optional
`gregraph-webui` distribution is installed** (`pip install gregraph-webui`, or
`python -m pip install ./packages/core ./packages/cli ./packages/webui` from a
checkout). Without it `serve` is not a command: it is a usage error (exit 2)
with a hint to install `gregraph-webui`, and it does not appear in `--help`.
`--help` never loads the web UI code.

| Option | Default | Meaning |
|---|---|---|
| `--host HOST` | `127.0.0.1` | Loopback address to bind. Accepted values are exactly `127.0.0.1`, `localhost` and `::1`. Any other value is a usage error (exit 2) and no socket is opened. There is no option to listen on other interfaces. |
| `--port PORT` | `8765` | TCP port, integer from 1 to 65535. Otherwise a usage error (exit 2). |

- The repository is discovered as for every command (`--repo`, or upward from
  the current directory). No repository → exit 3.
- On start it prints the banner
  `GREGraph UI: http://127.0.0.1:8765/` (IPv6: `http://[::1]:8765/`) followed by
  `Press Ctrl-C to stop.`. Open the URL in a browser yourself; `serve` does not
  open one. The URL carries no token: the web application owns its token
  (`docs/design.md` §21.4).
- Ctrl-C stops the server and exits 0.
- A port that cannot be bound (for example, it is in use) exits 3, with a
  message that suggests `--port`.
- Only the repository's own files are read or written, through the core
  operations. The server accepts requests only from the local machine. Every HTTP
  request is checked for `Host`, `Origin` and `Fetch-Site`, and mutating requests
  must send the application's token header. These guards only stop web pages in
  your browser. They do not protect against other local users or programs, which
  can already read the repository directly (`docs/design.md` §21.4). Do not
  expose it through a tunnel or proxy: remote deployment is not supported.
- `serve` is a foreground process, not a daemon or service. The global
  `--json`, `--no-input` and `-q` options have no effect on it; `--repo` applies.

See `docs/webui.md` for what the web UI offers and how it saves changes, and
`docs/design.md` §21 for the specification.

---

## Finding codes beyond the §14 catalogue

`validate` reports the codes catalogued in `docs/design.md` §14. The
implementation additionally uses these refusal-only and command-level codes:

| Code | Where |
|---|---|
| `E-ID-UNKNOWN` | Unknown document/CR ID argument (`link`, `set`, `supersede`, `deprecate`, `link refresh`, `cr set`, …). |
| `E-SET-KEY` / `E-SET-VALUE` | Unsupported `set` key / malformed assignment. |
| `E-TAG-INVALID` | Tag outside `[a-z0-9-]+`. |
| `E-SUPERSEDE-FORK` | `link refresh --follow` on a forked supersession chain. |
| `E-SECTION-UNKNOWN` | Authoring refusal (`new`, `supersede`, `cr new`, `term add`, `edit --section`/`--section-file`): the heading matches no section of the pinned template. Self-describing — `details` carries `template`, the full `template_sections` and the given heading. |
| `E-SECTION-REQUIRED-EMPTY` (write-time) | The §14 catalogue row, reused as an *authoring* refusal: with `--section*` a required section has no provided entry, with `--strict` any required section is empty-or-placeholder after assembly. `details` carries `template_sections` and `missing_required`. |
| `E-TERM-UNKNOWN` | Unknown or ambiguous term slug. |
| `E-GIT-UNAVAILABLE` | Git-only command (`baseline`) in degraded mode. |
| `E-BASELINE-UNCOMMITTED` / `E-BASELINE-INVALID` / `E-BASELINE-EXISTS` | `baseline create` refusals. |
| `W-GRAPH-LARGE` | `graph` export above 300 nodes. |
| `W-BASELINE-MISSING` | Baseline branch missing locally; status degrades to `unknown`. |
| `E-BODY-STALE` | Catalogued by `docs/design.md` §21.8 (optional web UI extension), so it is not in the §14 table itself. Web UI save refused: the Markdown body changed on disk since the editor read it. Nothing is written; reload and re-apply the edit. Since the agent-readiness amendment it is also raised by `edit --body`/`--body-file` (same `update_body` path). |
| `E-PATH-UNSAFE` | Catalogued by `docs/design.md` §21.8. Web UI save refused (HTTP 400): a symbolic link or Windows junction is in the body or sidecar path or a folder above it, or the path would leave the repository. Nothing is written. No CLI command raises it. |
| `E-USAGE` / `E-NO-REPOSITORY` / `E-ENV` / `E-INTERNAL` | Not findings: these are the *protocol* codes of the `--json` error envelope on exits 2/3/4/5 (see [Output conventions](#output-conventions)). They never appear as findings and are not part of the §14 catalogue. |

These are tracked in `docs/backlog.md` as spec gaps (the §14 catalogue does
not list them).
