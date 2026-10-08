# GREGraph CLI reference

Every command, flag, exit code and interactive behaviour of GREGraph v0.1.1.
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
`--help`/`--version` exit 0.

### Global options

| Option | Meaning |
|---|---|
| `--repo PATH` | Use PATH as the repository root instead of discovering it upward from the current directory. PATH must contain `.gregraph/config.toml`, otherwise exit 3. |
| `--no-input` | Never prompt. Missing required inputs become usage errors (exit 2). |
| `--json` | Machine-readable output. Supported by `list`, `show`, `status`, `validate`, `check`, `graph`; ignored elsewhere. |
| `-q`, `--quiet` | Suppress non-essential output (findings and errors still print). |
| `-v`, `--verbose` | Extra detail; an internal error prints its traceback. |
| `--version` | Print the tool version and exit. |
| `-h`, `--help` | Help for the command tree or the nearest subcommand. |

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Success. |
| `1` | Validation errors found, or the operation is blocked (`check`, `hook pre-commit`, `validate --strict` with warnings). |
| `2` | Usage error: bad flags, missing required input with `--no-input`, cancelled picker. |
| `3` | No repository found or environment error (bad `--repo`, missing Git, editor failure, corrupt config). |
| `4` | Operation refused: cycle, edge-rule violation, refusal to overwrite, closed CR, and similar. The refusal finding is printed on stderr. |
| `5` | Internal error. |

`validate` exits 1 on errors, or on warnings when `--strict` is given.
`check` exits 1 when the pre-commit hook would block. `hook pre-commit`
exits non-zero to abort the commit. `status` always exits 0.

### Output conventions

- Findings are one per line on stdout (refusals on stderr), prefixed with the
  code and subject: `E-CYCLE RE-1 refines RE-2: … (fix: …)`. Warnings use
  `W-…`, errors `E-…`.
- Colours are used only when stdout is a TTY and `NO_COLOR` is unset.
- `note: not a git repository — <feature> unavailable` lines mark degraded
  mode (see below); at most one per feature per invocation.
- With `--json`, stdout is exactly one canonical JSON document
  (indent 2, sorted keys, trailing newline); human lines are suppressed.

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
document types, `.gitignore`, and a starter `README.md`.

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
             [--cr CR] [--edit]
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
| `--edit` | Open the Markdown in `$VISUAL`/`$EDITOR` afterwards. |

Interactive: type picker over configured types, title prompt, then an
optional `link (TYPE:TARGET, empty to finish)` loop when no `--link` was
given. Warns `W-NO-GIT-IDENTITY` when no Git identity is available for
`created_by`. Refuses `E-CR-DISABLED` when `--cr` is used with
`cr.enabled = false`; `E-CR-CLOSED` when the CR is `rejected`/`implemented`;
`E-CR-SCOPE-TARGET` when the CR does not know the ID. Unknown types refuse
`E-TYPE-UNKNOWN`.

### `link`

```
gregraph link [SOURCE] [TYPE] [TARGET]
```

Adds a directed or symmetric edge from SOURCE to TARGET. Records
`target_version` = the target's effective version (its `version`, plus one
when the target has unbumped modifications).

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
the bumping). Reports bumped documents, newly/already outdated links, stale
and pending-outdated links, and validation findings.

### `check`

```
gregraph check [--json]
```

"What would the hook say": the pre-commit simulation over all working-tree
changes (staged or not), report-only. Exits 1 when the hook would block —
validation errors, or newly outdated links while
`versioning.on_outdated_links = "block"`. `--json` emits
`{blocked, block_reasons, would_bump, findings, newly_outdated}`.

### `validate`

```
gregraph validate [--strict] [--only-errors] [--json]
```

Full validation (the spec §14 catalogue). Intended for CI.

| Flag | Meaning |
|---|---|
| `--strict` | Treat warnings as errors for the exit code. |
| `--only-errors` | Display errors only; the exit code still sees the full report. |
| `--json` | Emit `[{code, severity, id\|path, message, fix?}]` (`fix` is a suggested command where one exists). |

Exits 1 on errors (or warnings with `--strict`), else 0.

### `list`

```
gregraph list [--type T]… [--kind K]… [--status S]… [--tag t]…
              [--roots] [--orphans] [--outdated] [--stale]
              [--deprecated-templates] [--sort id|title|created|version]
              [--json]
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
| `--json` | Array of sidecars plus derived `status` and `kind` fields. |

### `show`

```
gregraph show [ID] [--body] [--depth N] [--json]
```

Prints one document: sidecar fields, derived status, outbound and inbound
edges with freshness (`target_version / effective`, state), one level of
upstream (hierarchical edges to this document), the downstream tree
(documents that transitively link here over directed edges), assets, and
template info. If ID is a CR, delegates to `cr show`.

| Flag | Meaning |
|---|---|
| `--body` | Also print the Markdown body (JSON: add a `body` field). |
| `--depth N` | Limit the downstream tree depth (default: unlimited). |
| `--json` | One object: sidecar + `status`/`kind` + `outbound`/`inbound`/`upstream`/`downstream` + `template_info`. |

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
the repository is degraded. `--json` emits the same as a structured payload.

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

### `supersede`

```
gregraph supersede [OLD…] [--title T] [--type TYPE]
                   [--copy-body|--no-copy-body] [--copy-links|--no-copy-links]
                   [--cr CR] [--edit]
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
| `show NAME` | Print the descriptor and skeleton of a version (`--version N`, default latest). |

Users may edit a version's files only to set `deprecated` and `description`;
changing `sections` of a version with documents pinned to it is
`E-TEMPLATE-MUTATED` — create a new version with `template bump` instead.

### `cr`

Change requests (spec §9). Every `cr` subcommand refuses `E-CR-DISABLED`
when `cr.enabled = false`.

```
gregraph cr new [--title T] [--scope TARGET[:INTENT]]… [--external-ref R] [--edit]
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
| `cr new` | Create a CR in status `open` from the `cr.template` template. `--scope TARGET[:INTENT]` (repeatable) adds scope entries; intent defaults to `modify`. `--external-ref R` stores an issue key or PR URL. `--edit` opens the body. Title is prompted when missing. |
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
```

| Subcommand | Meaning |
|---|---|
| `versions` | After a merge conflict in sidecars: parse conflict markers, set `version = max(versions seen) + 1`, recompute hashes, clamp `target_version` values. Reports "no conflicted sidecars found" on a clean tree. |
| `regenerate-id PATH` | Fix an ID collision (spec §4.4): derive a fresh ID for the document at PATH and rewrite links that unambiguously reference the old one from this branch's history; the rest is listed for manual re-linking. |
| `cache` | Delete and rebuild the index cache. |

Merge-conflict guidance (spec §12.6): resolve body conflicts as prose; for
sidecars, resolve to any syntactically valid JSON (or leave the markers) and
run `repair versions`; keep both sides of duplicated links —
`repair versions` de-duplicates.

### `term`

Glossary terms (spec §10) live in `glossary/`, outside the graph.

```
gregraph term add "Term" [--alias A]… [--edit]
gregraph term list
gregraph term show SLUG
gregraph term usage SLUG
gregraph term rename SLUG "New term"
gregraph term deprecate SLUG [--reason R]
```

| Subcommand | Meaning |
|---|---|
| `add` | Create `glossary/<slug>.md` + `<slug>.json` from the `term` template. The slug is derived from the term (lowercase, non-alphanumerics → `-`). `--alias` is repeatable. |
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
`gregraph link refresh …` commands that resolve it). Warnings never abort.
`versioning.on_cr_modified = "block"` additionally aborts on
`W-CR-MODIFIED-AFTER-DECISION`. Escape hatch: `git commit --no-verify`.

### `edit`

```
gregraph edit [ID]
```

Opens the Markdown body in `$VISUAL`/`$EDITOR` (prompted picker when ID is
missing). Convenience only; prints nothing on success.

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
| `E-TERM-UNKNOWN` | Unknown or ambiguous term slug. |
| `E-GIT-UNAVAILABLE` | Git-only command (`baseline`) in degraded mode. |
| `E-BASELINE-UNCOMMITTED` / `E-BASELINE-INVALID` / `E-BASELINE-EXISTS` | `baseline create` refusals. |
| `W-GRAPH-LARGE` | `graph` export above 300 nodes. |
| `W-BASELINE-MISSING` | Baseline branch missing locally; status degrades to `unknown`. |

These are tracked in `docs/backlog.md` as spec gaps (the §14 catalogue does
not list them).
