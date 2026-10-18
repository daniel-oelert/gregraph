# Migrating to typed document IDs

GREGraph 0.2.0 introduces typed identifiers and configuration schema 2:

```
<ID>        = <PREFIX>-<ABBREVIATION>-<6-char Crockford body>
example     = RE-FEAT-7F3K2Q
change req. = RE-CHG-3M9XA1
```

`PREFIX` is the existing `ids.prefix`. Every configured document type now
requires a unique `abbreviation` (`[A-Z]{3,5}`) under `[types.<name>]`, and
change requests always use the fixed, reserved abbreviation `CHG`. The
six-character body is unchanged.

This is a **hard cutover**: old two-segment IDs such as `RE-7F3K2Q` are
rejected everywhere, and there are no legacy aliases. The one-time rewrite is
performed by the standalone script `scripts/migrate_type_ids.py`, never by a
`gregraph` command. The script does not import `gregraph`, so it runs before
the 0.2 packages are installed. The design rationale is in `docs/design.md`
§4 and §7.2 and `docs/decisions.md` (D-TYPED-IDS).

## Who needs it

Run the migration if the repository was created by GREGraph 0.1.x and its
`.gregraph/config.toml` contains `config_schema = 1`.

Repositories created by `gregraph init` in 0.2.0 already have schema 2 and
abbreviations, so they need nothing. A schema-1 config is refused by every
command except `init` with exit 3 and a message naming this script; the 0.2
tool never reads or partially supports such a repository.

## What the script changes

The migration works only on a schema-1 config and:

- adds the shipped abbreviation to each shipped type (`context` CTX, `goal`
  GOAL, `epic` EPIC, `feature` FEAT, `user-story` STORY,
  `functional-requirement` FUNC, `non-functional-requirement` NFR,
  `constraint` CON, `design` DSGN, `decision` DEC, `test-case` TEST,
  `stakeholder` STKH, `assumption` ASM);
- sets `config_schema = 2` and updates `tool_version`;
- rewrites every old ID in sidecar `id` fields, filenames, links,
  `origin_cr`, CR `scope` entries and `introduces`, explicit mentions in
  bodies, and `assets/<ID>/` directory names;
- recomputes `body_hash` and `scope_hash` because identifier text changed.

It does **not** rewrite Git history, branches or tags.

## Preconditions

Before applying:

1. **Commit or back up.** Start from a clean working tree and record the
   commit you can return to. The script rewrites files in place.
2. **Upgrade every collaborator.** After the migration the repository needs
   the 0.2 tool; older binaries reject schema 2.
3. **Choose custom abbreviations.** Shipped types are mapped automatically.
   For every custom type that is not in the shipped mapping, supply
   `--abbreviation TYPE=ABBR` (repeatable). The abbreviation must match
   `[A-Z]{3,5}`, be unique across types, and must not be `CHG`.
4. **Coordinate branches.** Do not merge old-ID work into a migrated branch
   without rewriting it first (see below).

## Dry run (default)

Run the script from the repository root:

```
python scripts/migrate_type_ids.py
```

The default is a dry run: it prints the planned config changes, the
old-ID → new-ID mapping and the files it would rewrite, and writes nothing.
For custom types:

```
python scripts/migrate_type_ids.py --abbreviation ui-design=UI
```

Save the mapping for review or for updating references outside the
repository (commit messages, tickets, chat):

```
python scripts/migrate_type_ids.py --map-out /tmp/id-map.json
```

Review the mapping before applying, especially if a custom type or an
unusual mention appears.

## Apply

```
python scripts/migrate_type_ids.py --apply
```

`--apply` writes the rewritten config, sidecars, bodies, filenames and asset
directories. It accepts the same `--abbreviation TYPE=ABBR` and `--map-out
PATH` options as the dry run. Afterwards:

```
gregraph validate
git add -A
git commit -m "migrate to typed document IDs (config schema 2)"
```

`validate` should be free of `E-ID-LEGACY`, `E-ID-DERIVATION` and
`E-TYPE-ABBREVIATION-CHANGED`.

## Preserved versions and hashes

The rewrite is an identifier change, not a semantic content change. The
migration preserves:

- every document and CR `version`;
- every link `target_version`;
- every CR scope `base_version`.

It recomputes `body_hash` and `scope_hash`, because IDs are part of the body
text and scope JSON. This is the one documented case where a stored hash
changes without a version bump (`docs/design.md` §7.2), so link freshness is
unchanged: both the target version and the link's `target_version` stay the
same.

## Branch coordination

Treat the migration as a repository-wide change:

- Run it on a short-lived migration branch and merge that branch to the
  baseline branch before other work lands.
- Rebase or merge every open feature branch onto the migrated baseline.
  Branches that still contain schema-1 configs or old IDs must be migrated
  with the same mapping (use `--map-out` from the baseline run) before they
  are merged. Do not merge a schema-2 config with remaining old IDs; that is
  exactly what `E-ID-LEGACY` reports.
- Announce the cutover so nobody runs the 0.1 tool or creates new old-format
  IDs after the merge.

## Old history and baselines

Only the working tree is rewritten. Existing commits, branches and annotated
baseline tags keep their old IDs and manifest contents. That is intentional:
history is immutable. Use the `--map-out` mapping when you need to translate
an old ID found in `git log`, a baseline manifest or an external tracker.

## No old-ID aliases

After the cutover, an old two-segment ID is not accepted by any command,
link, scope entry or mention. It is not silently resolved to the new ID.
`--map-out` is a migration aid for humans and external tools, not a runtime
alias table. A schema-2 repository that still contains an old ID reports
`E-ID-LEGACY`.

## Rollback

There is no automatic reverse migration. To roll back:

- restore the pre-migration commit (for example
  `git reset --hard <pre-migration-commit>` on a private branch, or revert
  the migration commit if it is already merged), or restore the backup you
  took; and
- reinstall or keep available the 0.1 tool that understands schema 1.

The `--map-out` file lets you reverse references by hand if you cannot
restore a snapshot. Once the migration has been shared, prefer a forward fix
with the same mapping over a partial rollback.
