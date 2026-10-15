# GREGraph — Agent Readiness Specification

**Status:** Accepted direction (decisions confirmed by the project owner, 2026-10-15).
**Scope:** Implementation specification for making GREGraph a fully agent-first tool.
**Authority:** This document specifies *new* behaviour on top of `docs/design.md`
(revision 0.3, tool release 0.1.x). Where it restates baseline behaviour it cites the
section. It does not amend `docs/design.md` by itself; each implemented milestone
must land its `docs/design.md` / `docs/cli.md` / `docs/concepts.md` amendments in the
same commit, and `docs/decisions.md` must record the `D-AGENT-*` decisions of §1.3.
**Target:** The requirements in §11 (EARS format) are destined for the
`gregraph-requirements` repository; they are written in the style of `docs/design.md`
Appendix A so they can be imported directly (provisional keys `AGENT-nnn`).

Conventions: "must" = required; "should" = default with deviations needing a
documented reason; "may" = optional. Code citations refer to the repository at
tool version 0.1.1.

---

## §1 Overview & Goals

### 1.1 Why agent-readiness

GREGraph is designed so that *humans edit only Markdown prose* (design §1.2) while the
tool owns all structure. The primary consumer of prose is increasingly a **coding
agent**: an agent that reads requirements before implementing, writes requirements
when behaviour changes, and keeps the graph consistent through the CLI instead of a
GUI. Today the tool is agent-*tolerated* (`--no-input` pickers have flag equivalents),
but not agent-*ready*:

| # | Problem (evidence in code) | Effect on an agent |
|---|---|---|
| P1 | `--json` is honoured by only 6 commands (`list`, `show`, `status`, `validate`, `check`, `graph` — `grep json_mode packages/cli/src/gregraph/cli/commands/*.py`). `Output.line()` suppresses stdout under `json_mode` (`output.py:138-142`), so mutating commands (`new --json`, `link --json`, …) print **nothing**. Errors and refusals print plain text to **stderr** in every case (`main.py:849-878`). | An agent cannot learn *what happened* from a mutating call, and cannot rely on a single parseable stream. |
| P2 | `new` renders the template skeleton and hashes it into `v1`; filling the file in makes the first hook commit land at `v2` (`docs/backlog.md:582-586`). `--body`/`--section` authoring does not exist; `update_body` (§21.5) is web-UI-only (`operations.py:1456`). | Every file-first authored document starts its history as a fake `v2` of a skeleton, and the agent must *remember* template headings instead of being told them. |
| P3 | No command exposes configured types, kinds, edge rules, or template `required` flags. Interactive filtering lives in `commands/link.py:61-114` only. | An agent must read `config.toml`, template JSON files, and tool source to learn the rulebook — or discover rules by trial-and-error refusals. |
| P4 | `find_mentions` scans prose for any ID-shaped token case-insensitively (`markdown.py:28-31, 242-272`), so ordinary hyphenated words ("multi-target", "baseline-branch") fire `E-MENTION-UNKNOWN` and block commits (`docs/backlog.md:552-559`). `validate` reports `E-LINK-VERSION-AHEAD` literally for freshly refreshed links against modified targets (`docs/backlog.md:423-433, 561-567`). | False errors block legitimate agent work and teach agents to distrust validation. |
| P5 | Reading context = one `show --body --json` per document, plus manual link chasing and manual glossary lookup. | A 10-document context costs 10+ tool calls with no freshness information attached. |
| P6 | Nothing tells an agent the golden rules (never touch sidecars, no YAML front matter, `[[ID]]` syntax, `--no-input --json`). `init` writes `README.md` for humans only (`operations.py:1952`). | Every new agent session re-derives the rules — or violates them. |

### 1.2 Design principles for agent readiness

1. **One parseable stream.** With `--json`, stdout carries exactly one canonical JSON
   document — success, validation result, or error — and stderr is empty. An agent
   parses once, never interleaves.
2. **Self-describing failures.** Every refusal tells the agent what *would have been
   accepted* (rulebook excerpt, template sections, candidate list) so the next call
   can succeed without a lookup round-trip.
3. **Both authoring directions are first-class.** File-first (agent edits the `.md`
   with its native Edit tool, guided by `new --json`) and CLI-first (`--section`
   flags) must be equally supported and equally versioned.
4. **Explicit over inferred.** Prose references use explicit syntax; the tool stops
   guessing that ID-shaped words are IDs. Validation is only trustworthy if it never
   fires on ordinary prose.
5. **Zero new dependencies, zero services.** Agent readiness is achieved with the
   existing runtime footprint (pydantic, jinja2, markdown-it-py + mdit-py-plugins;
   AGENTS.md ground rules). No MCP server, no daemon, no network (design §1.2,
   §16.3, BOOT-201/205).
6. **The repo teaches the agent.** `gregraph init` writes the instructions into the
   repository (`AGENTS.md` + `.agents/skills/gregraph/SKILL.md`), following the same
   managed-block pattern as the pre-commit hook (`hooks.py:46-69`).

### 1.3 Resolved decisions

| ID | Decision | Pillar |
|---|---|---|
| D-AGENT-1 | Integration model: local CLI + core library; no MCP server package. Agent readiness via (a) complete `--json` contract, (b) template-aware authoring + `v1` grace period, (c) schema/rule introspection, (d) explicit prose mention syntax + freshness fixes, (e) single-call context packing, (f) automatic `AGENTS.md` and `.agents/skills/gregraph/SKILL.md` scaffolding on `init`. | all |
| D-AGENT-2 | Every command and subcommand supports `--json`; exactly one canonical JSON document on **stdout**; errors (exit 2/3/4/5) are JSON on **stdout** with **empty stderr**. | 1 |
| D-AGENT-3 | `new --json` returns a rich authoring payload (paths, template sections, rendered body, sidecar). Uncommitted `v1` documents are populated in place (`version` stays `1`) by reconcile/edit workflows; `effective_version` of an uncommitted `v1` is `1`. | 2 |
| D-AGENT-4 | Template-guided `--section`/`--section-file` flags on `new`, `supersede`, `cr new`, `term add`, `edit`; whole-body `--body`/`--body-file` on `new`, `supersede`, `edit`; self-describing template refusals (`E-SECTION-UNKNOWN`, `E-SECTION-REQUIRED-EMPTY` with the template's section spec in `details`). | 2 |
| D-AGENT-5 | `gregraph schema`, richer `template show --json`, and `link --candidates` expose the full rulebook for agents. | 3 |
| D-AGENT-6 | Prose mentions are recognised **only** in explicit syntax (`[[ID]]`, `[[ID|label]]`, Markdown links resolving to an ID or a managed `.md` path, case-sensitive uppercase); bare ID-shaped tokens are never mentions. | 4 |
| D-AGENT-7 | `E-LINK-VERSION-AHEAD` is measured against the target's **effective** version; a link matching an unbumped target is a `W-LINK-PENDING` warning, not an error. This resolves the §7.4 spec question (`docs/backlog.md:423-433`). | 4 |
| D-AGENT-8 | `gregraph context` packs targets + neighbours + glossary terms + findings into one call; `show` accepts multiple IDs; `list --body` includes Markdown bodies. | 5 |
| D-AGENT-9 | `init` writes `AGENTS.md` (managed block, idempotent, preserving existing content) and `.agents/skills/gregraph/SKILL.md`; `repair agents` and `sync` refresh them. | 6 |

### 1.4 Non-goals

- No MCP server, LSP, daemon, watch mode, or network service (design §1.2, §21.3).
- No new runtime dependency in `gregraph-core` or `gregraph-cli`; the optional
  `gregraph-webui` distribution is unchanged and gains nothing (design §21.2).
- No change to the on-disk document/sidecar formats of design §3–§5 (the only file
  additions are `AGENTS.md` and `.agents/skills/gregraph/SKILL.md` at the root).
- No query language, no custom edge types, no requirement-sentence linting
  (design §1.4 out-of-scope list stands).
- `--help`/`--version` stay plain-text argparse output (SystemExit); agents discover
  structure via `gregraph schema --json` instead (Pillar 3).

### 1.5 Shared conventions (restated for this document)

- **Canonical JSON** (design §5.4): `json.dumps(obj, indent=2, ensure_ascii=False,
  sort_keys=True)` plus a trailing newline; arrays keep semantic order, object keys
  are sorted.
- **Exit codes** (design §13): `0` success · `1` validation errors or blocked ·
  `2` usage error · `3` no repository / environment error · `4` operation refused ·
  `5` internal error.
- **ID pattern** (`core/ids.py:26`): `[A-Z][A-Z0-9]{0,7}-[0-9A-HJKMNP-TV-Z]{6}`
  (Crockford base32 body, uppercase). Input arguments stay case-insensitive
  (§4.5); prose mentions must be canonical uppercase (Pillar 4).
- **Boundaries** (design §16.2): `core` never prints and never imports `cli`;
  `cli` never touches the filesystem directly; every CLI command maps to one
  `operations.py` function (exception: `serve`, design §21.3 — which ignores
  `--json` per §21.3 and stays out of the contract).

---

## §2 Pillar 1 — Complete `--json` contract & structured error envelopes on stdout

### 2.1 Contract rules

R1. Every `gregraph` command and subcommand accepts the global `--json` flag.
    (`serve` is the lifecycle exception, design §21.3: it accepts and ignores it.)

R2. With `--json`, the command writes **exactly one canonical JSON document to
    stdout** and terminates. Nothing else is written to stdout; **stderr is empty**
    for exit codes 0, 1, 2, 3, 4 (and for 5 unless the debug escape hatch below).

R3. With `--json`, warnings that human mode writes to stderr (degraded-mode notes,
    `result.notices`, git-identity warnings) are carried **inside the payload** as
    `notices: [string]`; refusal/validation findings as `findings: [{…}]` (§14
    `Finding` shape: `{code, severity, id|path, message, fix?, details?}`).
    `Output.warn`/`Output.note`/`Output.finding` must become no-ops on stderr when
    `json_mode` is set (the command or the envelope carries them instead).

R4. `--json` takes precedence over `--quiet`: `--json --quiet` still prints the JSON
    document. `--quiet` suppresses human output only.

R5. Exit-1 documents are **result-shaped**, not error envelopes (exit 1 means "the
    operation ran and reports findings"): `validate --json` keeps
    `[{code, severity, id|path, message, fix?, details?}]` (design §14);
    `check --json` keeps `{blocked, block_reasons, would_bump, findings,
    newly_outdated, …}`; `hook pre-commit --json` uses the same shape as `check`
    plus `bumped` (§2.4.4).

R6. Exit-2/3/4/5 with `--json` produce one **error envelope** on stdout (§2.2).
    In human mode the existing plain-text stderr behaviour is unchanged.

R7. `--help`, `-h`, `--version` remain plain text (argparse `SystemExit`, exit 0);
    `gregraph` with no command prints help to stdout and exits 2 — under `--json`
    this becomes an `E-USAGE` envelope with the help text in `details.usage`.

R8. `--edit` (spawn `$VISUAL`/`$EDITOR`) and `--json` are mutually exclusive
    (usage error, exit 2): an interactive editor cannot be part of a
    machine-readable call. Human mode is unaffected.

R9. Exactly-one-document is enforced by a regression test that runs **every**
    registered command (and every `cr`/`template`/`term`/`repair`/`baseline`/
    `hooks`/`link` subcommand) with a fixed argument set in a `tmp_repo` fixture,
    asserts canonical serialisation, empty stderr, and that stdout parses as one
    JSON value (§10, milestone AG-1/AG-2).

### 2.2 Error envelope (exit 2/3/4/5)

```json
{
  "error": {
    "code": "E-CYCLE",
    "exit_code": 4,
    "message": "adding RE-A refines RE-B creates a cycle: RE-B → RE-A → RE-B",
    "finding": {
      "code": "E-CYCLE",
      "severity": "E",
      "id": "RE-B",
      "message": "adding RE-A refines RE-B creates a cycle: RE-B → RE-A → RE-B",
      "fix": "gregraph link RE-B refines RE-A",
      "details": { "cycle": ["RE-B", "RE-A", "RE-B"] }
    },
    "details": { "cycle": ["RE-B", "RE-A", "RE-B"] }
  }
}
```

Field rules:

| Field | Exit 2 (usage) | Exit 3 (environment) | Exit 4 (refused) | Exit 5 (internal) |
|---|---|---|---|---|
| `code` | `"E-USAGE"` | `"E-NO-REPOSITORY"` when root discovery fails (design §3); otherwise `"E-ENV"` (OSError, sidecar/config read failure) | the refusal's finding code (`E-CYCLE`, `E-EDGE-RULE`, `E-SECTION-UNKNOWN`, …) | `"E-INTERNAL"` |
| `message` | human-readable usage problem | human-readable problem | `finding.message` | `str(exc)` |
| `finding` | `null` | `null` | the complete `Finding` (serialised like §14, including `details`) | `null` |
| `details` | `{"usage": "<argparse usage string>"}` when available; always present (may be `{}`) | `{"path": "<argparse PATH>"}` when a bad path caused it; else `{}` | mirrors `finding.details` (may be `{}`) | `{}` |

Envelope codes `E-USAGE`, `E-ENV`, `E-NO-REPOSITORY`, `E-INTERNAL` are **protocol
codes** for this envelope only; they are not added to the §14 validation catalogue
and never appear as findings.

Refusal findings gain an optional machine-readable `details` field:
`Finding.details: dict[str, Any] | None = None` in `core/models.py`. Serialise it in
`validate --json` and every payload/envelope **only when present** (like `fix`).
All self-describing refusals of Pillars 2–4 use it.

Implementation note (CLI, `main.py`): the exception handlers of
`main.py:849-878` gain a `json_mode` branch that builds the envelope via a new
`output.error_envelope(...)` helper and writes it with `Output.json(...)`; the
`UsageError.usage` string and the `OperationRefused.finding` are the only extra
inputs needed. `traceback` printing (exit 5) is suppressed under `--json` unless the
environment variable `GREGRAPH_DEBUG=1` is set (then the traceback goes to stderr —
a debugging escape hatch, not part of the contract).

### 2.3 Success payloads — shared fields

Every mutating and lifecycle command's exit-0 payload carries:

- `findings: [Finding…]` — non-fatal findings recorded by the operation
  (e.g. `W-NO-GIT-IDENTITY`); `[]` when none.
- `notices: [string…]` — human-mode stderr warnings/degraded notes and duplicate/
  no-op notices, machine-readable here; `[]` when none.

JSON-only errors that human mode reports as `Output.error` lines still terminate the
process (envelope path); they are never inlined into a success payload.

### 2.4 Success payload schemas

Field tables below name the payload's keys. Unless stated, everything already exists
as a result dataclass in `core/operations.py` — serialisation is a mechanical
`dataclasses.asdict` / `model_dump(mode="json", by_alias=True)` job in the command
module, keeping the thin-command rule (design §16.1).

#### 2.4.1 Mutating document commands

**`new --json`** (rich authoring payload; Pillar 2A):

```json
{
  "id": "RE-7F3K2Q",
  "uuid": "6f3c2f1e-…",
  "type": "user-story",
  "kind": "requirement",
  "md_path": "documents/user-stories/RE-7F3K2Q.md",
  "json_path": "documents/user-stories/RE-7F3K2Q.json",
  "template": { "name": "user-story", "version": 1 },
  "version": 1,
  "body_hash": "sha256:9c1d…",
  "sections": [
    { "heading": "Story", "required": true, "placeholder": "As a <role>, …",
      "renamed_from": [] },
    { "heading": "Acceptance criteria", "required": true,
      "placeholder": "Given … When … Then …", "renamed_from": [] },
    { "heading": "Rationale", "required": false, "placeholder": "",
      "renamed_from": ["Motivation"] },
    { "heading": "Notes", "required": false, "placeholder": "", "renamed_from": [] }
  ],
  "body": "# Upload documents to a knowledge base\n\n## Story\n\n*As a <role>, …*\n\n…",
  "sidecar": { …complete sidecar object exactly as written to json_path… },
  "links": [ { "type": "refines", "target": "RE-2K7QMB", "target_version": 4 } ],
  "findings": [],
  "notices": []
}
```

`sections` is the pinned template's descriptor sections (design §5.5,
`TemplateSection`: `heading`, `required`, `placeholder`, `renamed_from`);
`body` is the body **as written on disk** (the agent's Edit tool can address it
directly); `sidecar` is the parsed on-disk sidecar object; `body_hash` doubles as
the `base_hash` for a subsequent `edit`/`update_body` call (design §21.5).
`CreateResult` (operations.py:270) gains `kind: str`, `sections:
tuple[TemplateSection, …]`, `body_text: str`, and `sidecar_document: Document`
(path fields stay repo-relative `pathlib.Path`, rendered `as_posix()` in JSON).

**`supersede --json`** — `SupersedeResult` (operations.py:414) plus the new
document's rich payload nested under `new`:

```json
{
  "old": ["RE-A"],
  "new": { "id": "RE-C", "md_path": "…", "json_path": "…", "template": {"name": "…", "version": 1},
           "sections": [ … ], "body": "…", "sidecar": { … }, "kind": "requirement", "type": "feature",
           "body_hash": "sha256:…" },
  "supersedes": ["RE-A"],
  "copied_links": [ { "type": "…", "target": "…", "target_version": 2 } ],
  "skipped_links": [],
  "stale_inbound": [ { "source": "RE-D", "type": "refines", "target": "RE-A", "target_version": 1 } ],
  "findings": [], "notices": []
}
```

**`edit --json`** (with `--body`/`--body-file`/`--section`/`--section-file`,
Pillar 2C; without them `--json` is a usage error per R8-analogue: `edit` with
`--json` and no content flags is refused `E-USAGE`):

```json
{
  "id": "RE-7F3K2Q", "md_path": "…", "json_path": "…",
  "body": "…full new body text…", "body_hash": "sha256:…", "title": "…",
  "changed": true,
  "sections": [ …pinned template sections… ],
  "findings": [], "notices": []
}
```
This is `BodyUpdateResult` (operations.py:375) plus `md_path`, `json_path`,
`sections`. `--body-file -` / `--section-file X=-` read stdin once.

**`set --json`** — `SetResult` (operations.py:393): `{id, applied: {key: value…},
findings, notices}`.

**`deprecate --json` / `undeprecate --json`** — `DeprecateResult` (operations.py:432):
`{id, changed, deprecated: {at, by, reason} | null, stale_inbound: [StaleInbound…],
findings, notices}`.

**`migrate --json`** — `MigrateResult` (operations.py:3660): `{dry_run,
items: [MigrationItem…]}` with `MigrationItem` (operations.py:3641) serialised as
`{id, kind: "in-place"|"superseding"|"skipped", from_version, to_version, new_id,
renamed, inserted, unknown, unmapped, manual_attention, stale_inbound, findings,
notices}`.

#### 2.4.2 Link commands

- **`link --json`** — `LinkResult`: `{source, type, target, created, target_version,
  notice, findings, notices}`. Duplicate link: `created: false`, `notice: "…"`,
  exit 0 (design §6.4 no-op rule).
- **`unlink --json`** — `UnlinkResult`: `{source, type, target, removed, removed_from,
  notice, findings, notices}`.
- **`link refresh --json`** — `RefreshResult` (operations.py:364): `{refreshed:
  [RefreshedLink…], stale: [StaleLink…], dry_run, findings, notices}` with
  `RefreshedLink = {source, type, old_target, new_target, old_target_version,
  new_target_version, repointed}` and `StaleLink = {source, type, target, reason,
  chain, fork_at, fork_successors}` (fields per operations.py:332-373).

#### 2.4.3 Workspace / lifecycle commands

- **`init --json`** — `InitResult` (operations.py:1819) extended by Pillar 6:
  `{root, created: [paths…], templates: [names…], git_initialised, hooks_installed,
  agents_files: ["AGENTS.md", ".agents/skills/gregraph/SKILL.md"], findings,
  notices}`.
- **`sync --json`** — `SyncResult` (operations.py:2327) plus the Pillar 2B bucket:
  `{mode, bumped, initialised, changed, normalised, rewritten, newly_outdated,
  previously_outdated, stale, pending, findings, notices}`. `Freshness` entries
  serialise as `{source, type, target, link_target_version, target_version,
  effective, state, newly}` (`state ∈ fresh | outdated | stale | pending-outdated`).
- **`check --json`** — existing shape (`docs/backlog.md:459-462`), plus
  `initialised`: `{blocked, block_reasons, would_bump, initialised, findings,
  newly_outdated, previously_outdated, stale, pending, refresh_commands}`.
- **`hook pre-commit --json`** — `HookPreCommitResult` (operations.py:4592) plus
  `initialised`: `{blocked, block_reasons, bumped, initialised, newly_outdated,
  previously_outdated, stale, pending, findings, refresh_commands, notices}`.
  Exit 1 when blocked (result document, R5), else 0.
- **`repair versions --json`** — `{repaired: [{path, version, versions_seen,
  clamped_links, deduplicated_links, changes}…], findings, notices}`.
  **`repair regenerate-id --json`** — `{old_id, new_id, uuid, body, sidecar,
  rewritten: [{source, type, old_target, new_target}…], manual, findings, notices}`.
  **`repair cache --json`** — `{file_count, types_seen, templates_seen, findings,
  notices}`. **`repair agents --json`** — `{agents_files, changed: [paths…],
  findings, notices}` (Pillar 6).
- **`baseline create --json`** — `{name, tag, manifest, head, findings, notices}`
  (`manifest` is the generated JSON manifest string, design §12.4).
  **`baseline list --json`** — `{tags: […], findings, notices}`.
- **`hooks install/uninstall --json`** — `{hook: "pre-commit", path:
  ".git/hooks/pre-commit", installed, up_to_date, findings, notices}`.
  **`hooks status --json`** — the same shape.

#### 2.4.4 Subcommands

- **`cr new --json`** — same rich shape as `new` plus `scope` and `status`:
  `{id, md_path, json_path, template, sections, body, sidecar, scope: [ScopeEntry…],
  status: "open", findings, notices}`.
- **`cr scope add --json`** — `{cr, added: {id, intent, base_version}, scope: [all
  entries], findings, notices}`; **`cr scope remove --json`** — `{cr, removed: "<ID>",
  scope: [remaining entries], findings, notices}`.
- **`cr set --json`** — `{cr, applied: {…}, decision: {status, at, by, at_version}
  | null, findings, notices}` (a `decision` is appended only for `status=`).
- **`cr reaffirm --json`** — `{cr, decision: {…}, findings, notices}`.
- **`cr reanalyze --json`** — `{cr, updated: [{id, intent, old_base_version,
  new_base_version}…], findings, notices}`.
- **`cr list --json`** — array of rows `{id, title, status, effective, drift}`
  (filters as today, design §13.18).
- **`cr show --json`** — the existing `cr show` payload (commands/show.py:165-181)
  unchanged.
- **`template list --json`** — `{templates: [{name, description, latest_version,
  versions: [{version, deprecated, breaking, documents}…]}…]}`.
- **`template add --json`** — `{name, version, path, findings, notices}`;
  **`template bump --json`** — `{name, version, path, breaking, findings, notices}`.
- **`template show --json`** — extended (Pillar 3): `{name, version, description,
  deprecated, breaking, sections: [{heading, required, placeholder, renamed_from}…],
  skeleton, path, findings, notices}` (`path` = repo-relative `template.md`).
- **`term add --json`** — `{term, slug, aliases, md_path, json_path, sections,
  body, body_hash, findings, notices}` (rich shape mirroring `new`).
- **`term list --json`** — `{terms: [{term, slug, aliases, version, deprecated}…]}`.
- **`term show --json`** — `{term, slug, aliases, created, created_by, version,
  body_hash, deprecated, template, status}`.
- **`term usage --json`** — `{slug, term, documents: [{id, mentions: [names…]}…]}`.
- **`term rename --json`** — `{old_slug, new_slug, term, mentioning_documents: [IDs…],
  findings, notices}` (renames files; never rewrites prose, design §10.2).
- **`term deprecate --json`** — `{slug, deprecated: {…} | null, findings, notices}`.

Read-only commands keep today's shapes (`list` — array of `document_payload`;
`show` — object; `status`; `validate` — findings array; `check`; `graph`), with the
additive extensions of Pillar 5.

### 2.5 Test-first requirements (Pillar 1)

- `tests/cli/test_json_contract.py` (new): the matrix of R9 — every command ×
  representative argument set × {success, refusal} asserting: exit code, exactly one
  canonical JSON value on stdout, empty stderr, `error`-envelope shape on 2/3/4/5,
  `findings`/`notices` present on success payloads.
- Extend `tests/core/test_models.py`: `Finding.details` serialises when present and
  is omitted when absent.
- Every existing JSON test (e.g. `tests/cli/test_show.py`, `test_validate.py`) keeps
  passing unchanged (backward compatibility).

---

## §3 Pillar 2 — Template-aware authoring & uncommitted `v1` grace period

### 3.1 Problem (evidence)

- `new` renders the template skeleton; the stored `v1` `body_hash` is the
  *skeleton's* hash. The agent then fills the file; the first hook commit bumps to
  `v2` (`docs/backlog.md:582-586`), so `v1` never existed as real content and links
  recorded against the skeleton show as outdated after the first commit.
- With `--no-input`, an agent has no way to learn a template's required `## Heading`
  sections except reading `.gregraph/templates/.../template.json` by hand.
- `operations.update_body` exists (operations.py:1456, design §21.5) but no CLI flag
  reaches it.

### 3.2 (A) Rich `new --json` response for native file editing

Specified in §2.4.1. Consequence: an agent that calls
`gregraph new user-story --title "…" --no-input --json` immediately has
`md_path`, the exact rendered `body`, and the `sections` spec (headings, required
flags, placeholders) — it can edit the file with its native Edit tool and never
read the template. This is the *file-first* workflow, and it is supported by
**grace period (B)** so the first commit does not fabricate a `v2`.

### 3.3 (B) Uncommitted `v1` grace period

**Definition.** A document is in the *initial-grace state* iff:

- `document.version == 1`, **and**
- the document is absent from Git `HEAD`: `workspace.git.file_at("HEAD", body_path)
  is None` (covers untracked *and* staged-but-uncommitted files).

In degraded mode (no Git) the grace state never applies: there is no commit step, so
`sync` keeps the current bump semantics of design §7.2 (`sync` *is* the versioning
act there). Document this explicitly — degraded mode has no grace period.

**Behaviour.** While a document is in the initial-grace state, the reconcile pass
(design §7.5 — shared by `sync`, `check`, `hook pre-commit`) treats an effective
content change as *populating the initial version*, not as a change:

1. `version` stays `1`; the recomputed `body_hash`, `title` (from H1, §5.6) and
   `assets` are updated **in place**. Nothing else changes.
2. The reconcile report classifies the item in a new **`initialised`** bucket
   (instead of `bumped`). `SyncResult`, `CheckResult`, `HookPreCommitResult` gain
   `initialised: tuple[str, …]` (§2.4.3). The hook still re-stages the rewritten
   sidecar (`git add`, design §7.5 step 2).
3. **`effective_version` returns `1`**, not `2` (D-AGENT-3):
   `_effective_version` (operations.py:533) and `versioning.effective_version`
   (versioning.py:78) must consult the grace predicate. Consequently `link`,
   `new --link`, and `link refresh` record `target_version = 1` for such targets,
   and the freshness table sees fresh links both before and after the initial
   commit.
4. `W-LINK-PENDING` is not raised for links whose target is in the initial-grace
   state (a draft being populated is not a pending-outdated state).
5. **End of grace.** The state ends when the document first appears in `HEAD`
   (its initial commit). From then on, normal semantics apply: any further content
   change is an unbumped modification and the next hook/`sync --bump` increments
   `version` to `2` (design §7.2).

**Where it applies:** `sync`, `check`, `hook pre-commit` (via the shared reconcile),
`link`/`link refresh` (via `effective_version`), and `validate`
(`W-LINK-PENDING` suppression + freshness table). `status` shows such documents as
`draft`/untracked as today; it also lists them under a *pending initial version*
note only if they also have inbound links (no new status is invented).

**Edge cases.**

- A `v1` document that *is* in `HEAD` (already committed once) and is edited again
  is **not** in the grace state — it bumps to `v2` normally.
- A document whose body file is missing counts as modified (`operations.py:502-514`
  already treats `OSError` as modified); with grace, that means the sidecar hash is
  refreshed at `v1` only when the body exists and hashes differently — a missing
  body is a validation error (`E-BODY-MISSING`), not a grace case.
- `repair versions` (merge-conflict recovery) is untouched: it clamps and recomputes
  regardless of grace.
- CRs and glossary terms go through the same reconcile pass. Apply the same grace
  rule to them (a CR at `v1` absent from `HEAD` is populated at `v1`; a term at
  `v1` likewise). CR `at_version` for the first decision then stays `1`, matching
  "creation appends the initial `open` decision with `at_version = 1`" (§9.3).

**Test-first list:** grace population keeps `version == 1` and rewrites
`body_hash`/`title`; first commit does not bump; `link` into an uncommitted `v1`
target records `target_version = 1` and stays fresh after the initial commit;
post-`HEAD` edit bumps normally; degraded mode bumps normally (unchanged); the
`initialised` bucket appears in `sync --json`/`check --json`/`hook pre-commit
--json`. Extend `tests/core/test_versioning.py`, `tests/core/test_operations.py`,
`tests/cli/test_sync.py`, `tests/cli/test_hook.py`, `tests/cli/test_link.py`.

### 3.4 (C) Template-guided `--section` and whole-body flags

New/extended flags (exact syntax):

```
gregraph new <TYPE> [--title T] [--section "<Heading>=<Content>"]…
                    [--section-file "<Heading>=<PATH|->"]…
                    [--body <TEXT> | --body-file <PATH|->]
                    [--strict] [--json] [existing flags]

gregraph edit <ID> [--section "<Heading>=<Content>"]…
                   [--section-file "<Heading>=<PATH|->"]…
                   [--body <TEXT> | --body-file <PATH|->]
                   [--strict] [--json]

gregraph supersede <OLD…> [--title T] [--section …]… [--section-file …]…
                           [--body <TEXT> | --body-file <PATH|->] [--strict]
                           [existing flags]

gregraph cr new [--title T] [--section …]… [--section-file …]… [--strict]
                [existing flags]

gregraph term add "<Term>" [--alias A]… [--section …]… [--section-file …]…
                           [--strict] [existing flags]
```

Rules:

1. **Precedence.** `--body`/`--body-file` (whole-body replacement) > `--section`/
   `--section-file` (per-section assembly) > template skeleton / `--copy-body`
   default. `--body` and `--section` together, or `--body` with `--body-file`, or
   `--section` with `--section-file` naming the same heading twice → usage error
   (exit 2). Two `--section` flags naming the same heading → usage error (last
   duplicate refused; content is never silently merged).
2. **Heading matching.** `<Heading>` is matched against the pinned (or resolved)
   template's `sections` — exact, trimmed, **case-sensitive**, matching `heading`
   first, then any `renamed_from` alias (design §5.5, §7.7; matching logic is
   `markdown.heading_matches`, markdown.py:147). If a heading could match two
   template sections (e.g. one section's `renamed_from` equals another's current
   `heading`), the first match in template order wins.
3. **Assembly order.** The assembled body lists level-2 sections in **canonical
   template order** (design §5.5), with the H1 first. On `new`/`supersede`/`cr new`/
   `term add`, unmentioned sections are emitted with their template placeholder
   text; on `edit`, unmentioned sections keep their **existing content verbatim**;
   existing extra level-2 sections not in the template are preserved at the end
   (they remain `W-SECTION-UNKNOWN`, design §5.2/D12). Content before the first
   level-2 heading (rare) is preserved before the first section.
4. **Whole-body input.** `--body TEXT` / `--body-file PATH|-` supplies the body
   text (LF normalisation only, design §21.5 step 4 — stored as sent). The tool
   owns the H1 (design §5.6): if the text's first non-blank line is a level-1
   heading it is replaced by `# <title>` (notice when the heading text differed);
   when it is not, `# <title>` is prepended. On `edit` the write goes through
   `operations.update_body` (design §21.5) with `base_hash` computed from the
   on-disk body immediately before writing; on `new`/`supersede` the text is used
   at creation, so `v1` hashes the **real** content (backlog idea, lines 582-586).
5. **Self-describing template errors** (nothing is written on refusal):
   - Unknown `<Heading>` → refusal `E-SECTION-UNKNOWN` (exit 4) whose finding
     `details` carries the full template section specification:
     `{"template": {"name": …, "version": …}, "template_sections": [{heading,
     required, placeholder, renamed_from}…], "given_heading": "…"}` — the agent can
     self-correct on the next call without a template lookup.
   - **Required-section enforcement.** Using `--section*` (authoring deliberately)
     or `--strict` activates the check at write time: refuse
     `E-SECTION-REQUIRED-EMPTY` (exit 4) when a template-required section either
     has no provided entry (`--section` mode) or is empty-or-placeholder after
     assembly (`--strict`; §5.5 emptiness rule). `details` again carries
     `template_sections` plus `"missing_required": ["Heading", …]`.
   - Plain `new`/`cr new`/`term add` **without** `--section*`/`--strict` keeps
     today's behaviour (placeholders allowed at creation; `validate` reports
     `E-SECTION-REQUIRED-EMPTY` later; grace period covers the file-first fill-in).
     Plain `edit` without content flags keeps spawning the editor (R8: not with
     `--json`).
6. **`--strict` flag.** New boolean on `new`, `edit`, `supersede`, `cr new`,
   `term add`: after assembly (and in addition to rule 5's `--section` check),
   refuse when any required section is empty-or-placeholder in the final body.
   It validates at write time instead of at the next `validate`.
7. **stdin.** At most one `--body-file -` **or** one `--section-file X=-` per
   invocation may read stdin; two stdin consumers are a usage error. stdin content
   is read fully before any write.
8. **Sidecar effects.** Assembly/whole-body writes update the sidecar `title`
   from the H1 (design §5.6 / `update_body` step 5). `version`, `body_hash`,
   `links`, `assets` are left to the reconcile pass — a saved change is visible as
   "modified, unbumped" until the hook or `sync --bump` runs (design §21.5), except
   at creation where `body_hash` is hashed from the final text (rule 4).

### 3.5 Core operations (signatures)

```python
# core/operations.py (new; keyword-only, Workspace-first, per §16.2)

@dataclass(frozen=True, slots=True)
class BodyState:
    """Current on-disk body of a document: text, hash, parsed sections."""
    id: str
    body: Path          # repository-relative
    text: str
    body_hash: str
    sections: tuple[Section, …]   # markdown.parse_sections of text

def body_state(workspace: Workspace, *, doc_id: str) -> BodyState: ...

def update_sections(
    workspace: Workspace,
    *,
    doc_id: str,
    content: Mapping[str, str],      # heading (template-canonical) -> content
    base_hash: str,
) -> BodyUpdateResult:
    """Assemble the body from `content` over the current body (template order),
    write it via the `update_body` path (§21.5), sync the sidecar title."""

def template_sections(
    workspace: Workspace, *, template: TemplateRef
) -> tuple[TemplateSection, …]: ...   # helper used by new/edit/schema
```

`create_document` (operations.py:827) gains keyword parameters
`sections: Sequence[tuple[str, str]] = ()`, `body_text: str | None = None`,
`strict: bool = False` and returns the extended `CreateResult` (§2.4.1).
Refusals (`E-SECTION-UNKNOWN`, `E-SECTION-REQUIRED-EMPTY`, `E-BODY-STALE` on
`edit`) write nothing — the create-refuses-write-nothing invariant of §13.2 holds.

CLI assembly helper: `gregraph/cli/commands/sections.py` (new, small): parses
`--section`/`--section-file` arguments (including `-`/stdin rules), resolves
headings against `template_sections(...)` (raising `UsageError` for malformed
`Heading=Content` text — that is a syntax problem, exit 2 — and mapping template
refusals from core for unknown headings), and produces the `content` mapping. The
CLI never touches files; section-file reading happens through a tiny `core`
helper (`storage.read_text_file(path)` — needed because "cli never touches the
filesystem directly"; reading stdin is CLI's job).

### 3.6 Interaction with migration

`edit --section` on a document pinned to an older template version uses the
**pinned** version's sections (validation pins templates, design §7.7) — its
`details.template_sections` therefore reflect the pinned descriptor. Agents that
want the latest rules call `gregraph schema --json` (Pillar 3).

---

## §4 Pillar 3 — Self-discovery & schema introspection

### 4.1 `gregraph schema`

```
gregraph schema [--type TYPE] [--json]
```

Core operation: `describe_schema(workspace, *, type: str | None = None) ->
SchemaInfo` in `operations.py`; command module `gregraph/cli/commands/schema.py`
(new). Unknown `--type` → `E-TYPE-UNKNOWN` refusal (exit 4). `--json` payload:

```json
{
  "schema": 1,
  "tool_version": "0.1.1",
  "id_prefix": "RE",
  "baseline_branch": "main",
  "versioning": { "on_outdated_links": "block", "on_cr_modified": "warn" },
  "graph": { "open_conflicts": "warn" },
  "assets": { "max_size_kb": 5120 },
  "cr": { "enabled": true, "template": "change-request", "deciders": [] },
  "types": {
    "user-story": {
      "kind": "requirement",
      "folder": "user-stories",
      "template": "user-story",
      "id_prefix": "RE",
      "description": "…template description…"
    }
  },
  "kinds": ["goal", "requirement", "design", "verification", "information"],
  "edge_rules": [
    {
      "type": "refines",
      "direction": "directed",
      "hierarchical": true,
      "acyclic": true,
      "source_kinds": ["goal", "requirement"],
      "target_kinds": ["goal", "requirement"],
      "same_kind_only": false,
      "mutually_exclusive_with": ["derives-from"],
      "mutually_exclusive_opposite": ["depends-on"],
      "description": "Source states the same intent as target, more concretely."
    }
  ],
  "templates": {
    "user-story": {
      "latest_version": 1,
      "versions": [1],
      "deprecated": false,
      "breaking": false,
      "description": "…",
      "sections": [
        { "heading": "Story", "required": true, "placeholder": "As a <role>, …",
          "renamed_from": [] }
      ]
    }
  },
  "cr_lifecycle": {
    "statuses": ["open", "accepted", "rejected", "implemented"],
    "transitions": {
      "open": ["accepted", "rejected"],
      "accepted": ["implemented", "open"],
      "rejected": ["open"],
      "implemented": ["open"]
    },
    "scope_intents": ["modify", "supersede", "deprecate"]
  }
}
```

Notes:

- `types.<name>.id_prefix` is informational: the repository-wide prefix (design
  §4.1) repeated per type so one call answers "what does an ID look like".
  `description` is the referenced template's descriptor description.
- `edge_rules` is the 9-row §6.1 table rendered from `core/rules.py` data
  (`EdgeRule.direction/hierarchical/source_kinds/target_kinds/same_kind_only`,
  `MUTUALLY_EXCLUSIVE_SAME_PAIR`/`MUTUALLY_EXCLUSIVE_OPPOSITE`);
  `acyclic` = `direction == "directed"` (design §6.2). `description` carries the
  §6.1 "Meaning / use when" and the picker hints of `commands/link.py:27-37`.
- `templates` lists the active (latest non-deprecated) version per template, plus
  all version numbers present. With `--type TYPE`, `types` is filtered to that
  type, `templates` to the templates its entries reference (plus the CR template
  when `cr.enabled`); `edge_rules`, `kinds`, `cr_lifecycle` are global and stay.
- Human mode: aligned sections mirroring the JSON (types table, edge-rules table
  with the §6.1 guidance lines, template section lists).

### 4.2 `gregraph template show NAME [--version N] --json`

`TemplateShowResult` (operations.py:3631) already carries the descriptor; the
command's `--json` payload adds `sections` in resolved order and `path`:

`{name, version, description, deprecated, breaking, sections: [{heading, required,
placeholder, renamed_from}…], skeleton, path, findings, notices}`.

### 4.3 `gregraph link --candidates`

```
gregraph link --candidates <SOURCE_ID> [--type EDGE_TYPE] [--json]
```

- New mode flag `--candidates` on the `link` parser, mutually exclusive with
  positional `TARGET` (and with positional `TYPE` when no `--type` given);
  `link --candidates SRC --type refines TARGET` → usage error. Existing positional
  `link SOURCE TYPE TARGET` behaviour is unchanged.
- Core operation `link_candidates(workspace, *, source: str, edge_type: LinkType |
  None) -> LinkCandidatesResult`, **reusing the filtering of the interactive
  picker** — the logic of `commands/link.py:61-114` (`_type_rows`, `_target_rows`)
  moves into core so the CLI stays thin and the picker becomes a caller of it:
  kind rule (`edge_kind_allowed`), target liveness (not deprecated, not
  superseded), and cycle pre-exclusion (`Graph.check_link` → `E-CYCLE` candidates
  dropped). Unknown edge type → usage error; unknown source → `E-ID-UNKNOWN`
  refusal (exit 4, same as `link` today).
- Payload:

```json
{
  "source": "RE-A",
  "source_kind": "requirement",
  "allowed_edge_types": ["refines", "derives-from", "depends-on", "constrains",
                          "conflicts-with", "relates-to"],
  "candidates": [
    { "type": "refines", "target": "RE-B", "target_title": "…",
      "target_type": "feature", "target_kind": "requirement" }
  ]
}
```
Candidates are sorted by `(type, target)`. `allowed_edge_types` is `[]` when the
source kind permits no edge type. Human mode prints the picker's rows.

---

## §5 Pillar 4 — Explicit prose mention syntax & link freshness fix

### 5.1 Problem 1 — mention false positives

`find_mentions` (`markdown.py:242-272`) scans bare text and link targets with
`_ID_RE` compiled case-insensitively (`markdown.py:28-31`). Any hyphenated word
whose second half is 6 Crockford characters — "multi-target", "baseline-branch",
"system-design" — matches, fires `E-MENTION-UNKNOWN`, and the pre-commit hook
blocks the commit (`docs/backlog.md:552-559`; one M6 seed commit was blocked by
this and worked around by rewording).

### 5.2 Decision 1 — explicit syntax only (D-AGENT-6)

`find_mentions` is changed so a prose mention is recognised **only** in explicit
reference syntax, outside fenced code blocks, code spans and HTML (the
markdown-it token walk already guarantees this for `text`/`link_open` children):

1. **WikiLink:** `[[ID]]` or `[[ID|label]]` — e.g. `[[RE-1A2B3C]]`,
   `[[CR-1A2B3C]]`. `ID` must match the full pattern
   `[A-Z][A-Z0-9]{0,7}-[0-9A-HJKMNP-TV-Z]{6}` **case-sensitively** (canonical
   uppercase; `[[re-7f3k2q]]` is prose, not a mention — input-argument matching
   of §4.5 is unchanged, prose matching is not).
2. **Markdown links:** `[text](target)` where
   - `target` matches the ID pattern (case-sensitive), or
   - `target` is a relative link that, resolved against the document's directory,
     names a managed `.md` file whose stem matches the ID pattern
     (e.g. `[RE-1A2B3C](../requirements/RE-1A2B3C.md)`), or
   - the link **text** (trimmed) matches the ID pattern case-sensitively.
   Asset links (targets landing in `assets/<ID>/`) remain asset references, never
   mentions (existing rule, markdown.py:249-250).

`Mention.via` becomes `Literal["wikilink", "link"]`. Everything a bare-token
mention used to do now applies only to explicit mentions:

- `W-MENTION-UNLINKED` — explicit mention of a document ID with no edge either way
  (CR IDs exempt, design §5.2).
- `E-MENTION-UNKNOWN` — explicit mention matching neither document nor CR.
- CR bodies (§9.7): same extractor; `W-CR-MENTION-UNSCOPED` / `E-MENTION-UNKNOWN`
  apply to explicit mentions only.
- `term usage` is **not** affected (term matching is name/alias based, design
  §10.2).

Consumers to update in the same change: `validation.py:826`, `operations.py:4490`
(hook scan), `changes.py:1147`. Documentation updates in the same commit:
`docs/design.md` §5.2 and §9.7, `docs/concepts.md`, `docs/cli.md`.

**Migration note.** Repositories seeded with bare-ID mentions (e.g.
`gregraph-requirements`) must be re-checked after upgrade: bare IDs stop being
mentions, so `E-MENTION-UNKNOWN` disappears but `W-MENTION-UNLINKED` coverage
shrinks to explicit references. The release notes for the version carrying this
change must call this out; the `gregraph-requirements` repo converts to `[[ID]]`
syntax as its first agent-managed CR (this document §11 seeds that workflow).

**Test-first list** (`tests/core/test_markdown.py` rewrites, plus
`tests/core/test_validation.py` / `test_changes.py` mentions cases):
"multi-target"/"baseline-branch" prose → no mention; `[[RE-7F3K2Q]]`,
`[[RE-7F3K2Q|label]]` → mention; lowercase `[[re-…]]` → no mention; link href as
ID, link href as relative `.md` path, link text as ID → mention; mentions in
code spans/fences/HTML stay ignored; wikilink inside a Markdown link
`[[RE-…]](x)` → the wikilink counts (text token), the link target `x` does not.

### 5.3 Problem 2 — the `E-LINK-VERSION-AHEAD` trap

`validate` reports `E-LINK-VERSION-AHEAD` when `link.target_version >
target.version` (design §14), but `link`/`link refresh` legitimately record the
target's *effective* version `version + 1` while it has unbumped modifications
(design §7.4) — so `validate` flags the very state the tool just created, until
the hook bumps the target (`docs/backlog.md:423-433, 561-567`). `check`/hook
already suppress exactly this case (`_ahead_false_positives`,
operations.py:2681-2703); `validate` does not.

### 5.4 Decision 2 — compare against the effective version (D-AGENT-7)

- The invariant becomes: `target_version` must never exceed the target's
  **effective version** (`versioning.effective_version`, honouring the Pillar 2B
  grace predicate). `validate` reclassifies:
  - `target_version == effective_version` **and the target has unbumped
    modifications** → `W-LINK-PENDING` (existing code, design §14) whose `fix` is
    `gregraph sync --bump` (or, in hook context, the note that the commit in
    progress resolves it).
  - `target_version > effective_version` → `E-LINK-VERSION-AHEAD` (a real merge
    mishap; `repair versions` clamps).
  - Freshness table states (`versioning.Freshness.state`) already use effective
    versions and are unchanged.
- After this change the `_ahead_false_positives` suppression in
  `check`/`hook_pre_commit` (operations.py:2681-2712) is subsumed by validation
  itself; it may be removed if the hook's findings list equals `validate`'s for
  the same tree (keep one code path — design §7.1 refinement 1). Removing it is
  part of this milestone's tests: `check --json` and `validate --strict --json`
  must agree on `E-LINK-VERSION-AHEAD`/`W-LINK-PENDING` for the same tree.
- With Pillar 2B, newly created uncommitted `v1` targets have
  `effective_version = 1`, so the seeding-time trap (`docs/backlog.md:561-567`)
  disappears completely during initial creation.

**Test-first list** (`tests/core/test_validation.py`,
`tests/core/test_versioning.py`): refreshed link against an unbumped committed
`v2` target → `W-LINK-PENDING` with `fix: gregraph sync --bump`, exit stays
warning-only; `target_version = version + 2` → `E-LINK-VERSION-AHEAD`;
`validate`/`check` agreement test; grace-target link stays fresh.

---

## §6 Pillar 5 — Context packing for coding agents

### 6.1 `gregraph context`

```
gregraph context <ID…> [--depth N] [--direction both|upstream|downstream]
                       [--include-terms | --no-include-terms] [--json]
```

- Accepts one or more document IDs and CR IDs (mixed allowed; unknown ID →
  `E-ID-UNKNOWN` refusal naming the offending ID). `--depth N` default `1`,
  `N ≥ 0` (else usage error). `--direction` default `both`.
- Terms are included by **default**; `--no-include-terms` omits the term scan;
  `--include-terms` is the explicit confirmation (argparse boolean pair).
- Core operation: `build_context(workspace, *, ids: Sequence[str], depth: int = 1,
  direction: Literal["both", "upstream", "downstream"] = "both",
  include_terms: bool = True) -> ContextResult` in `operations.py`; command module
  `gregraph/cli/commands/context.py` (new).

`--json` payload:

```json
{
  "requested": ["RE-A"],
  "depth": 1,
  "direction": "both",
  "targets": [
    { …document_payload (sidecar + status + kind)…, "body": "…", 
      "sections": [ {"heading": "…", "content": "…"} ],
      "outbound": [LinkView…], "inbound": [LinkView…] }
  ],
  "neighbors": [
    { "id": "RE-B", "via": { "source": "RE-A", "type": "refines", "target": "RE-B" },
      "direction": "downstream", "depth": 1, "freshness": "fresh",
      "sidecar": { … }, "body": "…" }
  ],
  "terms": [
    { "term": "Knowledge base", "slug": "knowledge-base", "aliases": ["KB"],
      "body": "# Knowledge base\n\n## Definition\n\n…" }
  ],
  "findings": [ … ]
}
```

Rules:

- `targets` reuses the `show --json` document payload per requested ID
  (`show_document` result); for a CR target the entry is the `cr show` payload
  (commands/show.py:165-181) plus `body`, and its `neighbors` come from the CR's
  impact set (design §9.8) as downstream edges.
- `neighbors`: BFS over graph edges (outbound, inbound, and symmetric edges
  resolved to the other endpoint) starting at all targets, up to `--depth N`,
  filtered by `--direction` (upstream = edges where the target document is the
  *source*'s hierarchical upstream and inbound edges generally: a neighbour is
  upstream when the edge is stored on the neighbour pointing at a bundle node).
  Each entry carries the connecting edge (`via`), its `direction`
  (`upstream`/`downstream`), BFS `depth`, and the design §7.4 freshness `state`
  of that edge (`fresh|outdated|stale|pending-outdated`). Neighbours include
  superseded/deprecated documents (they matter for reading context) — their
  `sidecar.deprecated`/inbound `supersedes` make that visible; orphans and
  unrelated documents are not included.
- `terms`: every glossary term (or alias) appearing in any target or neighbour
  body, matched with the §10.2 word-boundary matcher (`term usage` logic,
  `_word_pattern`/`_document_mentions`, operations.py:3248-3278); each matched
  term appears once with its full body text.
- `findings`: the freshness entries of all edges **among bundle documents** with
  `state != "fresh"`, plus the `validate` findings whose subject is one of the
  bundle IDs (so `E-SECTION-REQUIRED-EMPTY`, `W-LINK-OUTDATED`, etc. for these
  documents travel with the context). Findings are de-duplicated by
  `(code, subject, message)`.
- Human mode (no `--json`): one combined, LLM-friendly Markdown document on
  stdout: for each target `# <ID> — <title>` + status line + body, then its
  edges; neighbours at their depth (`## Neighbours`), then a `## Glossary`
  section with term bodies; separators `---` between documents. No colour codes
  inside the Markdown block.

### 6.2 Multi-ID `show`

`gregraph show <ID…> [--body] [--depth N] [--json]`:

- One ID: today's behaviour, byte-for-byte (backward compatible).
- Multiple IDs: human mode prints the documents sequentially separated by a
  blank line and `---`; `--json` emits a **JSON array** of the same per-document
  payloads (a CR ID yields its `cr show` payload entry). Duplicate IDs are
  de-duplicated preserving first-seen order. Any unknown ID aborts with
  `E-ID-UNKNOWN` before any output (all-or-nothing).
- Implementation: `show_document` keeps single-ID semantics; the command loops
  and assembles the array. The positional becomes `nargs="+"` only when more than
  one positional is given — argparse `nargs="?"`-style compatibility is kept by
  parsing `args.id` as `nargs="*"` and branching on its length (usage error on
  zero IDs in non-interactive mode, as today).

### 6.3 `list --body`

`gregraph list … [--body]`:

- `--json`: each item gains `"body": "<full Markdown text>"` (additive key).
- Human mode: the table is unchanged; `--body` is ignored (documented in
  `docs/cli.md`; agents use `--json`).
- Core: `list_documents(..., include_body: bool = False)` (operations.py:2088);
  bodies are read via the existing per-row body path (bounded by the design
  §1.5 sizing assumption; a 5,000-doc `list --body` is an explicit large call,
  not a fast path).

---

## §7 Pillar 6 — Automatic `AGENTS.md` and `.agents/skills/gregraph/SKILL.md`

### 7.1 Files written by `gregraph init`

1. **`<root>/AGENTS.md`** — repository instructions for coding agents. If absent,
   created with a short header and the managed block (Appendix A). If present
   (GREGraph initialised inside an existing code repository), **all existing
   content is preserved** and the managed block is appended — or replaced in
   place when a block already exists — following exactly the pattern of
   `hooks.install` (`hooks.py:46-69`): marker search, append-after-content,
   idempotent rewrite. Markers:

   ```
   <!-- >>> gregraph agent instructions >>> -->
   …
   <!-- <<< gregraph agent instructions <<< -->
   ```

2. **`<root>/.agents/skills/gregraph/SKILL.md`** — a complete, portable Agent
   Skill (draft text in Appendix B) with YAML frontmatter:

   ```yaml
   ---
   name: gregraph
   description: Operate a GREGraph requirements repository from an agent — create,
     link, validate and read requirement documents with the gregraph CLI. Use when
     the repository contains a .gregraph/config.toml directory.
   ---
   ```

   The file is **wholly owned** by gregraph (no managed block; agents do not edit
   it): on refresh it is rewritten wholesale when its content differs. The YAML
   frontmatter exception to "no front matter" applies only to this file (and
   AGENTS.md is plain Markdown, no front matter); document bodies never get
   front matter (`E-FRONTMATTER-FORBIDDEN`, design §5.2).

3. `init` reports both paths in `InitResult.agents_files` (§2.4.3) and prints them
   in human mode (`agents files written: AGENTS.md, .agents/skills/gregraph/SKILL.md`).

### 7.2 Content requirements

The managed `AGENTS.md` block must state (concise, ≤ 60 lines):

- What the repository is (GREGraph requirements repository; managed directories
  `documents/`, `changes/`, `glossary/`, `assets/`; config `.gregraph/config.toml`;
  templates `.gregraph/templates/`).
- Golden rules (numbered): never hand-edit `*.json` sidecars or `.gregraph/`;
  no YAML front matter in `*.md` bodies; for automation always pass
  `--no-input --json` and parse stdout only (errors are JSON on stdout);
  prose references only as `[[ID]]` or `[text](relative.md)`; create documents
  with `gregraph new <type> --title "…" --json` and fill the returned `md_path`
  (native Edit tool) or pass `--section`; never create/rename/delete document
  files; commit through the installed pre-commit hook (preview with
  `gregraph check`); run `gregraph validate --strict` before finishing.
- The three discovery/read entry points: `gregraph schema --json`,
  `gregraph context <ID…> --json`, `gregraph link --candidates SRC --json`.
- Where the full skill lives: `.agents/skills/gregraph/SKILL.md`.

The SKILL.md must cover, in order: when to use; golden rules (same list, full
sentences); discovering the rulebook (`schema`, `template show`, `link
--candidates`); creating and editing documents (file-first workflow with
`new --json` + native Edit; CLI-first workflow with `--section`/`--body`,
including the `E-SECTION-UNKNOWN`/`E-SECTION-REQUIRED-EMPTY` self-describing
errors and the uncommitted-`v1` grace period); traceability (`link`,
`--candidates`, `link refresh`, freshness states); reading context
(`context`, multi-`show`, `list --body`); change requests (`cr new/scope/set/
reaffirm/reanalyze`, statuses); the commit lifecycle (`hook pre-commit`,
`sync --bump`, `repair versions`); exit codes 0-5 and the error envelope;
troubleshooting (most common refusals and their fixes).

Both texts are static strings/templates in core (no rendering from user config
beyond the ID prefix and the command examples), so `repair agents` is a pure
rewrite. Line endings LF (Windows: written LF, read with CRLF normalisation —
same rule as bodies, design §5.2).

### 7.3 Refreshing (staying correct over time)

- **`gregraph repair agents`** (new subcommand, §13.19 extension): rewrite both
  files idempotently — the managed block is replaced in place, `SKILL.md` is
  rewritten when its content differs. Refuses nothing except no-repository
  (exit 3). `--json` payload `{agents_files, changed, findings, notices}`.
- **`gregraph sync`** refreshes both files as its last step (cheap, idempotent:
  write only on content difference) so normal workflow heals drift after a
  GREGraph upgrade or a config change. `SyncResult` gains
  `agents_files_changed: tuple[Path, …]`.
- **`gregraph init`** always writes them (§7.1). `gregraph repair` without a
  subcommand keeps its merge-guidance behaviour.
- Hook/install does **not** touch agent files (single responsibility; hooks stay
  `.git/hooks/pre-commit` only).

### 7.4 Core module

New `packages/core/src/gregraph/core/agents.py` (mirrors `hooks.py`'s
architecture):

```python
AGENTS_BLOCK_START / AGENTS_BLOCK_END: Final[str]   # HTML-comment markers
def agents_block() -> str            # managed block text
def write_agents_md(root: Path) -> Path | None   # returns path; None = unchanged
def skill_text() -> str
def write_skill(root: Path) -> Path | None
def refresh(root: Path) -> tuple[Path, …]        # both files, writes only diffs
```

`init_repository` (operations.py:1952) calls `agents.refresh` and reports paths;
`sync` calls it; `repair_agents(workspace) -> RepairAgentsResult` wraps it for
the CLI. `find_root`-based path safety: files are written only under
`workspace.root` (no managed-path concerns — plain root files).

---

## §8 Cross-cutting specification updates

These §14-catalogue and §13 amendments land with the pillars above and must be
reflected in `docs/design.md` (r0.4), `docs/cli.md`, `docs/concepts.md` in the
same commits:

| Change | Where |
|---|---|
| `Finding.details: dict[str, Any] \| None` — optional machine-readable details on findings; serialised when present. | design §14 (`validate --json` shape), `core/models.py` |
| New refusal codes `E-SECTION-UNKNOWN` (unknown `--section` heading) and write-time `E-SECTION-REQUIRED-EMPTY` reuse (authoring refusal distinct from the §14 validation code of the same name; both carry `details.template_sections`). | design §14 + §13.2/§13.23 |
| `--json` contract: every command; error envelope on stdout (exit 2/3/4/5); `notices` in payloads; precedence over `--quiet`; `--edit`×`--json` mutual exclusion. | design §13 general |
| `new`: `--section`, `--section-file`, `--body`, `--body-file`, `--strict`. `edit`: same content flags (without them: editor, as today). `supersede`, `cr new`, `term add`: `--section*` (+`--body*` on `supersede`). | design §13.2, §13.14, §13.18, §13.20, §13.23 |
| `schema`, `context` commands; `link --candidates`; `repair agents`; `list --body`; multi-ID `show`; `--include-terms/--no-include-terms`. | design §13 (new §13.24/§13.25 subsections in r0.4) |
| Mention syntax: explicit-only (`[[ID]]`, `[[ID\|label]]`, Markdown links), case-sensitive uppercase; §5.2/§9.7 restated. | design §5.2, §9.7 |
| `E-LINK-VERSION-AHEAD` measured against the effective version; unbumped-target match reported as `W-LINK-PENDING` with `fix: gregraph sync --bump`. Resolves the §7.4 spec question (backlog 423-433). | design §7.4, §14 |
| Uncommitted-`v1` grace period: reconcile populates `v1` in place; `effective_version` returns `1`; `initialised` bucket in reconcile reports; degraded mode unchanged. | design §7.2, §7.4, §7.5 |
| `init` writes `AGENTS.md` + `.agents/skills/gregraph/SKILL.md`; `repair agents`; `sync` refreshes them. | design §13.1, §13.19, §3 (layout note) |

`docs/decisions.md` gains `D-AGENT-1` … `D-AGENT-9` (mirroring §1.3 of this
document) — **dependency: that file is not owned by this change; the implementing
milestones must add the entries.**

---

## §9 Architecture & module impact map

Boundaries are non-negotiable (AGENTS.md ground rules; design §16.2): `core`
never prints/imports `cli`; `cli` never touches files; every CLI command maps to
one `operations.py` function.

| Pillar / change | `packages/core/src/gregraph/core/` | `packages/cli/src/gregraph/cli/` | `tests/` |
|---|---|---|---|
| P1 JSON contract | `models.py` (+`Finding.details`) | `main.py` (envelope branch in handlers), `output.py` (`error_envelope`, stderr no-ops under json_mode), all `commands/*.py` (payload emission) | `tests/cli/test_json_contract.py` (new), `tests/core/test_models.py`, `tests/cli/test_output.py` |
| P2 authoring | `operations.py` (`create_document` extension, `body_state`, `update_sections`, `template_sections`), `templates.py` (section assembly helpers), `markdown.py` (reuse `parse_sections`/`heading_matches`), `storage.py` (small `read_text_file` helper) | `commands/sections.py` (new), `commands/new.py`, `commands/edit.py`, `commands/supersede.py`, `commands/cr.py`, `commands/term.py`, `main.py` (flags) | `tests/core/test_operations.py`, `tests/core/test_templates.py`, `tests/cli/test_new.py`, `tests/cli/test_edit.py`, `tests/cli/test_sections.py` (new) |
| P2B grace period | `versioning.py` (`effective_version`, grace predicate), `operations.py` (`_effective_version`, reconcile `_item_bump` → `initialised` bucket, `sync`/`check`/`hook_pre_commit` results), `validation.py` (`W-LINK-PENDING` suppression) | `commands/sync.py`, `commands/check.py`, `commands/hook.py` (payloads) | `tests/core/test_versioning.py`, `tests/core/test_operations.py`, `tests/cli/test_sync.py`, `tests/cli/test_hook.py`, `tests/cli/test_link.py` |
| P3 introspection | `operations.py` (`describe_schema`, `link_candidates`, `template_show` extension), `rules.py` (no change — data already there), `templates.py` | `commands/schema.py` (new), `commands/template.py`, `commands/link.py` (picker logic moves to core) | `tests/cli/test_schema.py` (new), `tests/cli/test_link.py`, `tests/cli/test_template.py`, `tests/core/test_operations.py` |
| P4 mentions & freshness | `markdown.py` (`find_mentions` rewrite, `Mention.via`), `validation.py` (mention checks; ahead rule), `changes.py` (CR mentions), `operations.py` (hook scan; drop `_ahead_false_positives`) | — | `tests/core/test_markdown.py`, `tests/core/test_validation.py`, `tests/core/test_changes.py`, `tests/core/test_operations.py` |
| P5 context packing | `operations.py` (`build_context`, `list_documents` +`include_body`, `show_document` unchanged) | `commands/context.py` (new), `commands/show.py` (multi-ID), `commands/list.py` (`--body`), `main.py` | `tests/cli/test_context.py` (new), `tests/cli/test_show.py`, `tests/cli/test_list.py`, `tests/core/test_operations.py` |
| P6 scaffolding | `agents.py` (new), `operations.py` (`init_repository`, `repair_agents`, `sync` refresh) | `commands/repair.py`, `commands/init.py`, `main.py` (`repair agents` subcommand) | `tests/core/test_agents.py` (new), `tests/cli/test_init.py`, `tests/cli/test_repair.py`, `tests/cli/test_sync.py` |
| Docs (every milestone) | — | — | `docs/design.md`, `docs/cli.md`, `docs/concepts.md`, `docs/decisions.md`, `docs/backlog.md` (close the resolved SPEC-QUESTIONs) |

No new runtime dependencies anywhere; `packages/webui/**` is untouched (the web UI
keeps calling `operations.py` and automatically benefits from core changes).
Packaging: no wheel changes (new modules are plain package modules; no new package
data).

---

## §10 Implementation milestones / phasing

Ordered, each independently testable; each ends with the full quality gate
(`ruff check . && ruff format --check . && mypy --strict -p gregraph && pytest`,
AGENTS.md workflow) plus its milestone acceptance. Test-first: each milestone's
tests are written with (or before) its code.

| # | Milestone | Contents | Acceptance |
|---|---|---|---|
| AG-1 | JSON contract foundation | P1 rules R1–R9: envelope on exit 2/3/4/5, stderr-empty guarantee, `Finding.details`, precedence over `--quiet`, `--edit`×`--json` refusal | `tests/cli/test_json_contract.py` matrix green; all 6 existing JSON commands byte-compatible |
| AG-2 | `--json` on every command | Payload emission for all mutating/lifecycle commands and subcommands (§2.4); notes/findings into payloads | matrix covers every command; `docs/cli.md` updated |
| AG-3 | Introspection | `schema`, `link --candidates` (+ core filter move), `template show --json` extension | `gregraph schema --json` round-trips the rulebook; picker and candidates agree on a sample graph |
| AG-4 | Mentions & freshness fix | Explicit-only mentions; effective-version ahead rule; drop `_ahead_false_positives` | "multi-target" prose validates clean; refreshed-against-unbumped = `W-LINK-PENDING`; `validate`/`check` agree |
| AG-5 | Authoring flags | `--section*`, `--body*`, `--strict` on `new`/`edit`/`supersede`/`cr new`/`term add`; rich `new --json`; `body_state`/`update_sections` | section assembly round-trips; self-describing refusals carry `template_sections`; file-first and CLI-first both produce valid documents |
| AG-6 | `v1` grace period | Reconcile `initialised` bucket; `effective_version` honouring grace; `W-LINK-PENDING` suppression; degraded mode unchanged | first commit of an edited skeleton keeps `version = 1`; links recorded `1` stay fresh |
| AG-7 | Context packing | `context` (bundle + human Markdown), multi-ID `show`, `list --body` | one `context` call returns targets+neighbours+terms+findings; multi-`show` array shape |
| AG-8 | Agent scaffolding | `agents.py`, `init` writes both files, `repair agents`, `sync` refresh, SKILL.md + managed block content (Appendices A/B) | fresh `init` repo contains correct files; existing `AGENTS.md` content preserved; idempotent re-run writes nothing |

Order rationale: AG-1/AG-2 give every later milestone a machine-readable feedback
channel; AG-4 is independent of AG-5/AG-6 but AG-6 completes AG-4's freshness
story; AG-8 last so the generated instructions describe the *final* CLI surface.

Each milestone updates `docs/design.md`/`docs/cli.md`/`docs/concepts.md` as listed
in §8 and closes the corresponding `docs/backlog.md` SPEC-QUESTION entries
(mention syntax 552-559; version-ahead 423-433 + 561-567; skeleton-v1 582-586).

---

## §11 Candidate requirements for `gregraph-requirements` (EARS format)

Style: `docs/design.md` Appendix A. Provisional keys are mapping keys only
(keep a `bootstrap-map.md` `AGENT-nnn → RE-…` until seeding completes, per §19).
Types follow the shipped type set (`goal`, `feature`, `functional-requirement`,
`non-functional-requirement`, `constraint`, `test-case`).

### Goals

| Key | Type | Statement | Refines |
|---|---|---|---|
| AGENT-G1 | goal | The tool shall let a coding agent create, link, validate, and read requirements through the CLI without reading tool documentation, configuration files, or source code. | — |
| AGENT-G2 | goal | Every agent interaction with the tool shall be observable in exactly one parseable output stream. | — |

### Features

| Key | Type | Statement | Refines |
|---|---|---|---|
| AGENT-F1 | feature | A complete machine-readable CLI contract with structured error envelopes. | AGENT-G1, AGENT-G2 |
| AGENT-F2 | feature | Template-aware authoring with an uncommitted first-version grace period. | AGENT-G1 |
| AGENT-F3 | feature | Self-discovery of the repository rulebook (types, kinds, edge rules, templates, CR lifecycle). | AGENT-G1 |
| AGENT-F4 | feature | Explicit prose reference syntax and trustworthy link freshness. | AGENT-G1 |
| AGENT-F5 | feature | Single-call context packing for implementation tasks. | AGENT-G1 |
| AGENT-F6 | feature | Automatic agent instruction files written and refreshed by the tool. | AGENT-G1 |

### Functional requirements

| Key | Type | Title | EARS statement | Rationale | Fit criterion | Refines / Constrains |
|---|---|---|---|---|---|---|
| AGENT-001 | functional-requirement | Universal `--json` | WHEN any command or subcommand is invoked with `--json`, the tool shall write exactly one canonical JSON document to stdout and nothing else. | Agents parse once (D-AGENT-2). | Matrix test over every command: stdout parses as one canonical JSON value. | refines AGENT-F1; constrains AGENT-101 |
| AGENT-002 | functional-requirement | Error envelopes on stdout | WHEN an invocation with `--json` ends with exit 2, 3, 4, or 5, the tool shall write one `{"error": {code, exit_code, message, finding, details}}` envelope to stdout and leave stderr empty. | Single-stream parsing (P1 problem). | For each exit code, a test asserts the envelope shape and empty stderr. | refines AGENT-F1 |
| AGENT-003 | functional-requirement | Refusal findings in envelopes | WHEN a command refuses (exit 4) with `--json`, the envelope shall carry the complete refusal `Finding`, including its `details`, in `error.finding`. | Self-describing failures (§1.2 principle 2). | `link` cycle refusal shows `E-CYCLE` with the cycle path in `details`. | refines AGENT-F1 |
| AGENT-004 | functional-requirement | Machine-readable notices | WHEN a command with `--json` succeeds and would have written stderr warnings or degraded-mode notes in human mode, the payload shall carry them as `notices` and `findings` arrays and stderr shall remain empty. | Warnings must not bypass the parseable stream (R3). | `new` without Git identity emits `W-NO-GIT-IDENTITY` in payload `findings`, stderr empty. | refines AGENT-F1 |
| AGENT-005 | functional-requirement | Result documents on exit 1 | WHEN `validate`, `check`, or `hook pre-commit` is run with `--json` and exits 1, the tool shall emit the command's result-shaped document (not an error envelope). | Exit 1 is a validation *result*, not a protocol failure (R5). | `validate --json` on an invalid repo emits the §14 findings array with exit 1. | refines AGENT-F1 |
| AGENT-006 | functional-requirement | `--json` precedence | WHEN `--json` and `--quiet` are both given, the tool shall still print the JSON document and suppress only human output. | Quiet must not hide the contract (R4). | `new --json -q` prints the payload. | refines AGENT-F1 |
| AGENT-007 | functional-requirement | Deterministic payloads | The tool shall serialise every `--json` payload canonically (`indent=2, ensure_ascii=False, sort_keys=True`, trailing newline), with arrays in documented semantic order. | Identical calls produce identical bytes (design §5.4, BOOT-202). | Byte-compare two identical invocations. | refines AGENT-F1 |
| AGENT-010 | functional-requirement | Rich `new` payload | WHEN `gregraph new … --json` succeeds, the payload shall include `id`, `type`, `kind`, `md_path`, `json_path`, `template{name,version}`, `version`, `body_hash`, `sections[{heading,required,placeholder,renamed_from}]`, the written `body` text, the complete `sidecar` object, `links`, `findings`, and `notices`. | File-first authoring without a template lookup (D-AGENT-3). | Payload's `body` equals the bytes on `md_path`; `sections` equals the template descriptor. | refines AGENT-F2 |
| AGENT-011 | functional-requirement | `v1` grace period on reconcile | WHILE a document at `version == 1` is absent from `HEAD`, WHEN reconcile runs (`sync`, `check`, `hook pre-commit`) and its effective content differs from the stored hashes, the tool shall update `body_hash`, `title`, and `assets` in place at `version = 1` and shall not increment the version. | First real commit must be the first version (P2 problem, backlog 582-586). | Edit a fresh `new` document, commit through the hook: sidecar still says `version: 1` with the new hash. | refines AGENT-F2 |
| AGENT-012 | functional-requirement | Effective version of an uncommitted `v1` | WHEN the effective version of a document in the initial-grace state is computed, the tool shall return `1`. | Links must not record a future version (D-AGENT-3). | `link` into an uncommitted `v1` target records `target_version = 1` and reports fresh after the initial commit. | refines AGENT-F2 |
| AGENT-013 | functional-requirement | Grace ends at first commit | WHEN a document's files are present in `HEAD`, the initial-grace state shall no longer apply and normal bump semantics shall resume. | The grace period is a one-time population window. | After the initial commit, a further edit plus commit yields `version = 2`. | refines AGENT-F2 |
| AGENT-014 | functional-requirement | Degraded mode unchanged | WHERE no Git repository is present, the tool shall keep today's bump-on-`sync` semantics (no grace period). | Without Git, `sync` *is* the versioning act (§3.3). | Degraded-mode sync of an edited `v1` document bumps to `2`. | refines AGENT-F2 |
| AGENT-015 | functional-requirement | `--section` assembly | WHEN `--section "<Heading>=<Content>"` (repeatable) or `--section-file "<Heading>=<PATH|->"` is given to `new`, `supersede`, `cr new`, `term add`, or `edit`, the tool shall match `<Heading>` against the template's `sections` (`heading` and `renamed_from`, exact/trimmed/case-sensitive) and assemble the level-2 sections in canonical template order. | Template-guided CLI authoring (D-AGENT-4). | Assembled body's section headings and order equal the template descriptor's. | refines AGENT-F2 |
| AGENT-016 | functional-requirement | Preserve unmentioned content | WHEN `edit --section` updates a document, the tool shall preserve existing content of unmentioned sections verbatim (extra level-2 sections kept at the end) and shall keep placeholders for omitted optional sections on `new`/`supersede`/`cr new`/`term add`. | Prose ownership; minimal churn. | Round-trip `edit --section` leaves all other section bytes identical. | refines AGENT-F2 |
| AGENT-017 | functional-requirement | Self-describing unknown section | WHEN a `--section`/`--section-file` heading matches no template section, the tool shall refuse with `E-SECTION-UNKNOWN`, write nothing, and include the template's full section specification (`template_sections`) and the given heading in the finding's `details`. | Agent self-correction without a lookup (§1.2 principle 2). | Envelope `details.template_sections` lists every template section. | refines AGENT-F2 |
| AGENT-018 | functional-requirement | Write-time required-section check | WHEN `--section*` is used and a template-required section has no provided entry, or WHEN `--strict` is passed and any required section is empty or placeholder-only in the assembled body, the tool shall refuse with `E-SECTION-REQUIRED-EMPTY` (details: `template_sections`, `missing_required`) and write nothing. | Catch authoring mistakes at write time (D-AGENT-4). | Omitting a required section under `--section` exits 4 with the missing heading named. | refines AGENT-F2 |
| AGENT-019 | functional-requirement | Whole-body flags | WHEN `--body <TEXT>` or `--body-file <PATH|->` is given to `new`, `supersede`, or `edit`, the tool shall use the text as the body (LF-normalised, stored as sent), ensure the canonical `# <title>` H1 from `--title` (replace or prepend, with a notice when it replaced a differing H1), and write through the `update_body` path on `edit` (`base_hash` staleness guard, `E-BODY-STALE`). | Version 1 becomes the real content (backlog 582-586); reuse §21.5 machinery. | `new --body-file` with real content: created sidecar `body_hash` equals the hash of the final file. | refines AGENT-F2 |
| AGENT-020 | functional-requirement | Flag compatibility rules | WHEN mutually exclusive or invalid flag combinations are given (`--body` with `--section`, two stdin consumers, duplicate headings, `--edit` with `--json`), the tool shall refuse with exit 2 and shall not write. | Deterministic CLI contract. | Each combination yields exit 2 and an `E-USAGE` envelope. | refines AGENT-F1, AGENT-F2 |
| AGENT-021 | functional-requirement | `schema` command | WHEN `gregraph schema [--type TYPE] [--json]` is run, the tool shall emit the repository rulebook: id prefix, baseline branch, versioning/graph/assets/cr config, `types` (kind, folder, template, id_prefix, description), the five `kinds`, the nine `edge_rules` (direction, hierarchical, acyclic, kind sets, mutual exclusions, description), active `templates` with their `sections`, and the `cr_lifecycle`. | One-call rulebook (D-AGENT-5). | Payload round-trips every `config.toml` type and every `rules.py` edge type. | refines AGENT-F3 |
| AGENT-022 | functional-requirement | `template show` completeness | WHEN `gregraph template show NAME [--version N] --json` is run, the payload shall include the full descriptor (`sections` with `required`, `placeholder`, `renamed_from`) and the raw skeleton. | Template introspection for agents. | Payload sections equal `template.json` `sections`. | refines AGENT-F3 |
| AGENT-023 | functional-requirement | Link candidates | WHEN `gregraph link --candidates SOURCE [--type EDGE_TYPE] [--json]` is run, the tool shall return the admissible `(type, target, target_title, target_type, target_kind)` candidates using the same filtering as the interactive picker (kind rule, liveness, cycle pre-exclusion). | Non-interactive agents need the picker's knowledge (P3 problem). | Candidate set equals the picker rows for the same source and type. | refines AGENT-F3 |
| AGENT-024 | functional-requirement | Explicit mention syntax | The tool shall recognise a prose ID mention only when written as `[[ID]]`, `[[ID|label]]`, or a Markdown link whose target or link text matches the ID pattern (case-sensitive uppercase) or resolves to a managed `.md` document path; bare ID-shaped tokens in prose shall never be mentions; fenced code, code spans and HTML shall be excluded. | Stop `E-MENTION-UNKNOWN` false positives on hyphenated prose (backlog 552-559). | "multi-target" and "baseline-branch" prose produce no findings; `[[RE-…]]` produces `W-MENTION-UNLINKED`/`E-MENTION-UNKNOWN` as applicable. | refines AGENT-F4 |
| AGENT-025 | functional-requirement | Mention rules apply to CR bodies | WHEN a CR body contains an explicit mention, the tool shall apply `E-MENTION-UNKNOWN` and `W-CR-MENTION-UNSCOPED` to it exactly as to document bodies. | One mention grammar everywhere (design §9.7). | CR body tests mirror document-body mention tests. | refines AGENT-F4 |
| AGENT-026 | functional-requirement | Freshness against effective version | WHEN `validate` checks `target_version` against a target with unbumped modifications and `target_version == target.version + 1`, the tool shall report `W-LINK-PENDING` (fix: `gregraph sync --bump`) instead of `E-LINK-VERSION-AHEAD`; `E-LINK-VERSION-AHEAD` shall be reported only when `target_version` exceeds the target's effective version. | Remove the validate-vs-refresh contradiction (backlog 423-433, 561-567; D-AGENT-7). | `validate` and `check` agree on the same tree; the seeded scenario no longer errors. | refines AGENT-F4 |
| AGENT-027 | functional-requirement | `context` bundle | WHEN `gregraph context <ID…> [--depth N] [--direction both|upstream|downstream] [--include-terms|--no-include-terms] --json` is run, the tool shall return one bundle containing `targets` (full payloads with bodies and sections), `neighbors` up to depth N (default 1) with edge, direction, depth and freshness, `terms` (glossary definitions matched in bundle bodies), and `findings` (freshness states and validation findings affecting the bundle). | One call instead of N (P5 problem; D-AGENT-8). | Bundle for a 3-document subgraph equals the union of the individual `show` payloads plus links, terms and findings. | refines AGENT-F5 |
| AGENT-028 | functional-requirement | Human context output | WHEN `gregraph context` is run without `--json`, the tool shall emit one combined Markdown document on stdout containing the targets' bodies and edges, the neighbours, and a glossary section. | LLM-friendly paste (§6.1). | Output is valid Markdown; no colour codes. | refines AGENT-F5 |
| AGENT-029 | functional-requirement | Multi-ID `show` | WHEN `gregraph show` is given multiple IDs, the tool shall emit a JSON array of the per-document payloads under `--json` and sequential documents in human mode; a single ID keeps today's exact output. | Batch reads without N calls (D-AGENT-8). | Single-ID output byte-identical to 0.1.x; two-ID output is a two-element array. | refines AGENT-F5 |
| AGENT-030 | functional-requirement | `list --body` | WHEN `gregraph list … --body --json` is run, each item shall include its full Markdown `body`; the human table shall be unchanged. | One-call bulk read (D-AGENT-8). | Item `body` equals the file bytes. | refines AGENT-F5 |
| AGENT-031 | functional-requirement | Agent files on init | WHEN `gregraph init` is run, the tool shall write `AGENTS.md` (with the managed gregraph block) and `.agents/skills/gregraph/SKILL.md` at the repository root, preserving all pre-existing `AGENTS.md` content. | The repo teaches the agent (D-AGENT-9). | Fresh `init` yields both files; init over a pre-existing `AGENTS.md` appends only the block. | refines AGENT-F6 |
| AGENT-032 | functional-requirement | Idempotent agent files | WHEN the managed block already exists in `AGENTS.md`, the tool shall replace it in place (content otherwise untouched); WHEN `SKILL.md` already matches, the tool shall not rewrite it. | Idempotency, minimal diffs (hooks.py pattern). | Running `init`/`repair agents` twice changes nothing the second time. | refines AGENT-F6 |
| AGENT-033 | functional-requirement | Agent file refresh | WHEN `gregraph repair agents` runs or `gregraph sync` completes, the tool shall regenerate the managed block and `SKILL.md` so they describe the installed tool version and current configuration, writing only changed files. | Healing after upgrades/config changes (§7.3). | After a config type addition, `sync` refreshes the block to mention the new type's entry point or `repair agents` does. | refines AGENT-F6 |

### Non-functional requirements and constraints

| Key | Type | Title | EARS statement | Rationale | Fit criterion | Refines / Constrains |
|---|---|---|---|---|---|---|
| AGENT-101 | constraint | No new dependencies | The tool shall implement every agent-readiness capability with the existing runtime dependencies (pydantic, jinja2, markdown-it-py + mdit-py-plugins) and shall add no MCP/server/daemon component. | D-AGENT-1; BOOT-201; ground rules. | `pip install ./packages/core ./packages/cli` unchanged; `pipdeptree`/metadata diff shows no new runtime deps. | constrains AGENT-001…AGENT-033 |
| AGENT-102 | non-functional-requirement | Single-parse guarantee | The tool shall guarantee that every `--json` invocation's stdout is exactly one parseable JSON document even when warnings, refusals, or degraded-mode notes occur. | Agents fail loudly on stray output. | Fuzz-ish matrix test: stdout of every command outcome parses with a single `json.loads`. | constrains AGENT-001 |
| AGENT-103 | non-functional-requirement | Performance budget | WHEN a repository has 5,000 documents, `gregraph schema --json` shall complete within 2 seconds and `gregraph context --json` (depth 1, ≤ 10 targets) within 5 seconds on a laptop-class machine. | Context must be cheaper than N `show` calls (BOOT-200 scale). | Timed integration test on a generated 5,000-doc fixture. | constrains AGENT-021, AGENT-027 |
| AGENT-104 | constraint | Plain-text agent files | The agent files (`AGENTS.md`, `.agents/skills/gregraph/SKILL.md`) shall be pure text with no build step and shall never be imported or parsed by the tool. | No tool dependency on its own scaffolding. | Files are written by string templates in `core/agents.py`; no reader exists. | constrains AGENT-031 |
| AGENT-105 | non-functional-requirement | Cross-platform | The tool shall write agent files with LF endings on all platforms and shall normalise CRLF when updating an existing `AGENTS.md`. | Windows matters (AGENTS.md ground rules). | Windows CI leg passes the scaffolding tests. | constrains AGENT-031 |

### Verification (examples)

| Key | Type | Statement | Verifies |
|---|---|---|---|
| AGENT-400 | test-case | Given a fresh repository, when `gregraph new user-story --title "T" --no-input --json` runs, then stdout parses as one JSON document containing `md_path`, `sections` with two required headings, and `body` equal to the file content. | AGENT-001, AGENT-010 |
| AGENT-401 | test-case | Given a document created by `new` and edited by file, when it is committed through the pre-commit hook, then the committed sidecar has `version == 1` and `body_hash` of the edited body, and links recorded `target_version 1` report `fresh`. | AGENT-011, AGENT-012, AGENT-013 |
| AGENT-402 | test-case | Given a document body containing the words "multi-target" and "baseline-branch", when `gregraph validate --json` runs, then no mention finding is reported; when the body also contains `[[RE-XXXXXX]]` naming an unlinked document, then exactly one `W-MENTION-UNLINKED` is reported. | AGENT-024 |
| AGENT-403 | test-case | Given source A (requirement) and live targets B, C, D where C would create a cycle and D is deprecated, when `gregraph link --candidates A --type refines --json` runs, then the candidate list contains exactly the kind-rule-admissible live non-cycle targets and omits C and D. | AGENT-023 |
| AGENT-404 | test-case | Given a 3-document chain A refines B refines C with A edited unbumped, when `gregraph context A C --depth 1 --json` runs, then `targets` has 2 entries with bodies, `neighbors` has 1 entry (B) with `freshness: pending-outdated`, `terms` contains any glossary terms appearing in the bodies, and `findings` carries the pending state. | AGENT-027 |
| AGENT-405 | test-case | Given an `AGENTS.md` with custom content, when `gregraph init` runs in that directory's fresh sub-repository and then `gregraph repair agents` runs twice, then the custom content is preserved, the managed block is present exactly once, and the second repair changes no file. | AGENT-031, AGENT-032, AGENT-033 |

---

## Appendix A — Managed `AGENTS.md` block (draft content)

```markdown
<!-- >>> gregraph agent instructions >>> -->
# GREGraph agent instructions

This directory is a GREGraph requirements repository (managed by the `gregraph`
CLI). Managed directories: `documents/`, `changes/`, `glossary/`, `assets/`.
Configuration: `.gregraph/config.toml`. Templates: `.gregraph/templates/`.
Everything outside your prose edits is tool-owned.

## Golden rules

1. Never create, rename, move, or delete document files; never hand-edit `*.json`
   sidecars, `.gregraph/`, or links inside sidecars. The tool owns all structure.
2. Never add YAML front matter to a `*.md` document body (`E-FRONTMATTER-FORBIDDEN`).
3. For automation, always pass `--no-input --json`. Parse stdout only: with
   `--json`, stdout carries exactly one canonical JSON document, and errors
   (exit 2/3/4/5) arrive as `{"error": {code, exit_code, message, finding,
   details}}` on stdout. Exit codes: 0 ok · 1 validation/blocked · 2 usage ·
   3 environment · 4 refused · 5 internal.
4. Reference other documents in prose only as `[[ID]]`, `[[ID|label]]`, or a
   Markdown link to the relative `.md` path — never as a bare ID (bare ID-shaped
   words are not mentions).
5. Create documents with `gregraph new <type> --title "…" --no-input --json`;
   then either edit the returned `md_path` file directly (see the returned
   `sections` for required headings) or pass content with
   `--section "<Heading>=<Content>"`. Never fill documents by editing sidecars.
6. After editing document bodies, run `gregraph check` before committing; commit
   through the installed pre-commit hook. Refresh suspect links with
   `gregraph link refresh`.
7. Before finishing a task, run `gregraph validate --strict`.

## Agent entry points

- Rulebook (types, kinds, edge rules, templates, CR lifecycle):
  `gregraph schema --json`
- Context for implementation (targets + neighbours + glossary + findings in one
  call): `gregraph context <ID…> --json`
- Admissible link targets: `gregraph link --candidates <SOURCE> --json`
- Full operating instructions: `.agents/skills/gregraph/SKILL.md`

<!-- <<< gregraph agent instructions <<< -->
```

## Appendix B — `.agents/skills/gregraph/SKILL.md` (draft content)

````markdown
---
name: gregraph
description: Operate a GREGraph requirements repository from an agent - create, link, validate and read requirement documents with the gregraph CLI. Use when the repository contains a .gregraph/config.toml directory.
---

# GREGraph

GREGraph manages requirements as a directed acyclic graph of Markdown documents
with JSON sidecars. Humans own prose; the tool owns files, IDs, metadata, links
and versions. This skill tells you how to work in such a repository.

## Golden rules

1. Never create, rename, move or delete document files; never hand-edit `*.json`
   sidecars or anything under `.gregraph/`.
2. Never add YAML front matter to a document body. The first non-blank line must
   be the `# Title`.
3. In automation always pass `--no-input --json` and parse stdout only. With
   `--json`, stdout carries exactly one canonical JSON document; errors
   (exit 2/3/4/5) are `{"error": {code, exit_code, message, finding, details}}`
   on stdout; exit 1 (validate/check/hook) is the command's result document.
   Exit codes: 0 ok, 1 validation/blocked, 2 usage, 3 environment, 4 refused,
   5 internal.
4. Refer to other documents in prose only as `[[ID]]` or `[[ID|label]]`, or as a
   Markdown link to the relative `.md` path. Bare ID-shaped words are not
   mentions. Mention IDs are case-sensitive uppercase.
5. IDs look like `RE-7F3K2Q`: prefix plus 6 Crockford base32 characters.

## Discover the rulebook (once per session)

    gregraph schema --json

returns the configured types (kind, folder, template), the five kinds, all nine
edge types with their kind rules and mutual exclusions, the active templates
with required sections, and the CR lifecycle. For one template:
`gregraph template show <NAME> [--version N] --json`.

## Create and edit documents

File-first (preferred):

    gregraph new <type> --title "..." --no-input --json

The payload contains `md_path`, the rendered `body`, and `sections`
(`heading`, `required`, `placeholder`, `renamed_from`). Edit `md_path` with
your native file-editing tool, filling the required sections. A freshly created
document is in a grace state: until its first commit, edits populate version 1
instead of creating version 2 — the first commit is the first real version.

CLI-first:

    gregraph new <type> --title "..." \
      --section "Statement=WHEN ... THE SYSTEM SHALL ..." \
      --section-file "Rationale=rationale.md" --strict --no-input --json

`edit` works the same way on an existing document
(`--section`, `--section-file "Heading=path|-", --body, --body-file`,
`--strict`). Unknown headings are refused with `E-SECTION-UNKNOWN` and the
refusal's `details.template_sections` lists every valid heading with its
placeholder — self-correct and retry, nothing was written. Required sections
must be filled when `--section`/`--strict` is used (`E-SECTION-REQUIRED-EMPTY`).

Body changes are "modified, unbumped" until the pre-commit hook or
`gregraph sync --bump` records the version bump.

## Traceability

    gregraph link <SOURCE> <TYPE> <TARGET> --json
    gregraph link --candidates <SOURCE> --json        # admissible targets
    gregraph link refresh [--to <ID>] [--all] --json  # confirm after edits

Edge types: refines, derives-from, depends-on, satisfies, verifies, constrains,
supersedes, conflicts-with, relates-to — kind rules are in `schema --json`.
Freshness states: fresh, outdated, stale, pending-outdated.

## Read context before implementing

    gregraph context <ID...> --depth 1 --json

One call returns the requested documents (full bodies), their neighbours with
edge type/direction/freshness, the glossary definitions used in those bodies,
and any validation findings affecting the subgraph. `gregraph show <ID...>
--json` (multiple IDs allowed) and `gregraph list --type <t> --body --json`
are the lighter alternatives.

## Change requests

CRs live outside the graph in `changes/`. `cr new --title "..." --scope
<TARGET>[:<modify|supersede|deprecate>]`, `cr scope add/remove`, `cr set
status=...` (open → accepted/rejected → implemented, reopenable), `cr
reaffirm`, `cr reanalyze`. A document created for a CR uses `new ... --cr <CR>`.

## Commit lifecycle

Commit through the installed pre-commit hook; it bumps versions and blocks
commits that newly outdate links. Preview with `gregraph check`. After your own
substantive edits run `gregraph link refresh --to <ID>`. Merge conflicts:
resolve prose by hand, then `gregraph repair versions`; `gregraph repair
agents` regenerates these instructions.

## Troubleshooting

| Exit | Meaning | Typical fix |
|---|---|---|
| 2 | usage error | fix the flags; the envelope's `details.usage` shows the usage line |
| 3 | no repository / environment | run inside the repository (or pass `--repo`) |
| 4 | refused (E-CYCLE, E-EDGE-RULE, E-SECTION-UNKNOWN, ...) | read `error.finding` and its `details`; the rulebook is in `gregraph schema --json` |
| 5 | internal error | retry once; report with the envelope message |
````

## Appendix C — Worked examples

**Refusal envelope with self-describing details** (exit 4, stdout):

```json
{
  "error": {
    "code": "E-SECTION-UNKNOWN",
    "exit_code": 4,
    "message": "section 'Acceptance Criteria' is not a section of template 'user-story' v1 (exact, case-sensitive; see details.template_sections)",
    "finding": {
      "code": "E-SECTION-UNKNOWN",
      "severity": "E",
      "id": "user-story/v1",
      "message": "section 'Acceptance Criteria' is not a section of template 'user-story' v1 (exact, case-sensitive; see details.template_sections)",
      "details": {
        "given_heading": "Acceptance Criteria",
        "template": { "name": "user-story", "version": 1 },
        "template_sections": [
          { "heading": "Story", "required": true, "placeholder": "As a <role>, I want <capability>, so that <benefit>.", "renamed_from": [] },
          { "heading": "Acceptance criteria", "required": true, "placeholder": "Given … When … Then …", "renamed_from": [] },
          { "heading": "Rationale", "required": false, "placeholder": "", "renamed_from": ["Motivation"] },
          { "heading": "Notes", "required": false, "placeholder": "", "renamed_from": [] }
        ]
      }
    },
    "details": { "given_heading": "Acceptance Criteria" }
  }
}
```

**Grace-period sequence** (Git mode):

1. `gregraph new functional-requirement --title "X" --no-input --json`
   → document `RE-A`, `version: 1`, skeleton hash; `effective_version = 1`.
2. Agent edits `documents/functional-requirements/RE-A.md` natively.
3. `gregraph link RE-B refines RE-A` → records `target_version = 1`
   (grace predicate), not `2`.
4. `gregraph validate` → no `W-LINK-PENDING` for that link (grace target).
5. `git commit` → hook reconcile populates `v1` in place (`initialised = [RE-A]`),
   re-stages the sidecar; commit succeeds; sidecar committed with
   `version: 1` and the real content's `body_hash`.
6. A later edit + commit bumps `RE-A` to `version: 2` normally; the RE-B link
   becomes `W-LINK-OUTDATED` until refreshed — the ordinary review signal.

---

*End of document.*
