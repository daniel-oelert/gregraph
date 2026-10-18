# GREGraph — Design Document, revision 0.5

**GREGraph** — Git-aware Requirements Engineering Graph. CLI command: `gregraph`.

This revision specifies tool release **0.2.0**. Document revisions (r0.1, r0.2, …) are numbered independently of tool releases. Everywhere else in this document, "v0.1" and "v0.2" refer to **tool releases**.

Document status: design baseline for the first implementation. Date: 2026-09-10, amended 2026-10-18. License: private.

### Revision history

| Revision | Date | Changes |
|---|---|---|
| r0.5 | 2026-10-18 | Typed document identifiers: `<PREFIX>-<ABBREVIATION>-<6-char Crockford body>` with a required, unique per-type abbreviation; fixed `CHG` abbreviation for change requests. Config schema 2 (schema-1 configs are refused with exit 3); hard cutover with no legacy aliases. New codes `E-ID-LEGACY` and `E-TYPE-ABBREVIATION-CHANGED`; `E-ID-DERIVATION` covers prefix and abbreviation. Standalone `scripts/migrate_type_ids.py` migration with preserved versions and recomputed hashes. Sections 1.3, 2, 3, 4, 5.3–5.4, 7.2–7.3, 9.1–9.2, 13 general and 13.24, 14, 15, 16.1, 16.4–16.5, Appendix B.1 and B.3, and 20 amended; decision D-TYPED-IDS in `docs/decisions.md`. |
| r0.4 | 2026-10-16 | Amendment A2 (agent readiness, per `AGENT_READINESS.md`; decisions D-AGENT-1…D-AGENT-9 in `docs/decisions.md`). Universal `--json` contract with error envelopes on stdout (§13 general); template-guided authoring flags and rich `new --json` (§13.2, §13.14, §13.18, §13.20, §13.23); uncommitted-`v1` initial-grace period and the `initialised` reconcile bucket (§7.2, §7.4, §7.5); effective-version link freshness, `E-LINK-VERSION-AHEAD` vs `W-LINK-PENDING` (§7.4, §14); explicit-only prose mention syntax (§4.5, §5.2, §9.7, §14); introspection commands `schema` and `context`, `link --candidates`, richer `template show --json`, `list --body`, multi-ID `show` (§13.3, §13.10, §13.11, §13.17, §13.24, §13.25); agent scaffolding `AGENTS.md` + `.agents/skills/gregraph/SKILL.md` written by `init`, refreshed by `sync` and `repair agents` (§3, §13.1, §13.7, §13.19); finding `details` and authoring refusal codes (§14); layout additions (§16.1); `update_body` reused by CLI `edit` (§21.5). |
| r0.1 | 2026-09-10 | Initial design. |
| r0.3 | 2026-10-14 | Amendment A1 (section 21): optional local web UI as a third, optional distribution (`gregraph-webui`) with a foreground loopback-only `serve` command, a body-write operation with `E-BODY-STALE`, and narrow amendments to sections 1.2, 1.4, 7, 13, 14, 16 and BOOT-205. Baseline sections are otherwise unchanged. |
| r0.2 | 2026-09-10 | Change requests redesigned (section 9): removed from the graph (kind `change` and edge type `affects` deleted); scope entries with fixed base versions; drift detection against the baseline branch; origin tracking for documents introduced by a CR; proposed vs. effective status derived from the baseline branch; `implemented` replaces `done`; both CR workflows documented; CRs optional. Dependent changes in sections 1.3, 2, 5.2–5.4, 6.1–6.3, 7.5–7.6, 8, 11, 12.1, 13, 14, 15, 16, 18, 19, 20 and appendices A–C. |

## 0. How to read this document

This document is the complete specification for GREGraph (this revision specifies tool release 0.2.0). It is written for a coding agent that will build the tool from scratch in Python. Sections 1–15 specify behaviour; sections 16–19 specify engineering, testing, milestones, and the bootstrapping plan; the appendices contain the initial requirement set, default configuration, JSON schemas, and the `AGENTS.md` for the implementation repository.

Where the requirements engineer left a question open and asked for an evaluation, this document evaluates the options and **takes a decision**. Every such decision is marked `[DECISION]` and collected in section 20 so it can be revisited before or during implementation. The agent implements the decisions as written unless told otherwise.

Normative words: **must** (required), **should** (default, deviations need a documented reason), **may** (optional).

Section 21 (Amendment A1, revision 0.3) adds an optional local web UI. It is authoritative for the optional extension and lists every earlier statement it supersedes. It does not change the v0.1 baseline otherwise; sections 0–20 and Appendices A–C remain the historical record.

Revision 0.4 (Amendment A2, agent readiness) amends the sections listed in the revision history **in place** — it adds no new top-level section beyond §13.24/§13.25. `AGENT_READINESS.md` is its source specification; `docs/decisions.md` records the `D-AGENT-1`…`D-AGENT-9` decisions. No new runtime dependencies are introduced and the optional web UI extension is unchanged.

Revision 0.5 (typed identifiers) likewise amends the sections listed in the revision history in place. `docs/decisions.md` records D-TYPED-IDS; `docs/migration-typed-ids.md` is the operator guide for the standalone migration.

---

## 1. Purpose and scope

### 1.1 Problem

Requirements engineers need to organise requirements that are related by refinement, dependency, verification, and conflict; the relationships form a directed acyclic graph, not a tree. Existing wiki- and issue-tracker-based approaches lack atomic requirement objects, requirement-level versioning, and traceability that can be validated. Existing heavyweight tools are over-scaled for small product teams. Docs-as-code approaches fit developer-centric teams but lack tooling for link integrity, change tracking, and templates.

GREGraph is a local, Git-synchronised, Markdown-based requirements management tool that owns all structure (files, identifiers, metadata, links, versions) and lets humans own only the prose.

### 1.2 Design principles

1. **Humans edit Markdown; the tool edits everything else.** Users never create, rename, or delete document files, never edit sidecar JSON, never write links by hand.
2. **The graph is the truth; folders are a convenience.** Directory placement carries no meaning.
3. **Git is the synchronisation and collaboration layer.** The tool never talks to a server. Review happens through the team's own Git workflow; the tool imposes no branching strategy.
4. **Local, single-process, on-demand.** No daemon, no watch mode, no locking. (Amended by section 21: the optional `gregraph serve` is a foreground, loopback-only process; see 21.3.)
5. **Core library first, CLI second.** Every operation is available as a Python API so a future local web UI can reuse it without reimplementation.
6. **Degrade gracefully.** Without Git, everything still works except features that need history (draft/active status derived from the baseline branch).

### 1.3 In scope for v0.1

- Repository initialisation with shipped, versioned templates copied into the repository.
- Document types (user-definable) grouped by a fixed set of *kinds*; graph nodes as one Markdown + one JSON per document.
- Stable, collision-checked identifiers that carry metadata (the repository prefix and the document type's abbreviation); the random body remains non-semantic.
- Directed acyclic graph with a fixed set of edge types and kind-based rules enforced at link time.
- Document versioning by content hash, bumped at commit time (Git) or on sync (no Git).
- Link freshness tracking (links record the target version they were confirmed against).
- Supersession and soft deprecation.
- Template versioning, deprecation, and document migration.
- Change requests as a first-class entity outside the graph, with scope, drift detection, origin tracking, and a decision lifecycle whose effective state is derived from the baseline branch.
- A first-class glossary outside the graph.
- Assets per document, versioned through their owning document.
- Validation (as command, as pre-commit hook, and CI-friendly with exit codes).
- Status reporting including WIP detection.
- Baselines as annotated Git tags.
- Mermaid graph export.
- Interactive prompts and pickers with full non-interactive flag equivalents.

### 1.4 Out of scope for v0.1 (design must not preclude)

- Web UI beyond the optional local read/edit subset of section 21 (planned for v0.2 for commit workflows and the remaining capabilities; see 21.1 for the exact split).
- Requirement-level history and diff between Git refs.
- Custom Git merge driver for JSON sidecars.
- Import/export (ReqIF, CSV, Jira, Confluence).
- Query language beyond listing filters.
- User-defined edge types.
- Coverage reports.
- Requirement-sentence linting (EARS conformance etc.).
- Plugin architecture (module boundaries are designed for it; nothing is exposed).
- Multiple projects per repository; monorepo placement inside a code repository.
- Languages other than English for shipped templates.

### 1.5 Sizing assumptions

- Up to low thousands of documents per repository (design target: 5,000; must not degrade unusably at 10,000).
- Up to ~20 people committing to one repository.
- Every command may load the full graph (all JSON sidecars) into memory. Markdown bodies are read lazily; a body-hash cache avoids re-hashing unchanged files.

---

## 2. Concepts and vocabulary

| Term | Meaning |
|---|---|
| **Repository** | A Git repository (or plain directory in degraded mode) whose root contains `.gregraph/config.toml`. Dedicated to requirements; nothing else lives in it. |
| **Document** | One Markdown file plus its JSON sidecar. Exactly one graph node per document. |
| **Node** | A document as a vertex of the graph. |
| **Kind** | One of a fixed set of categories the tool understands: `goal`, `requirement`, `design`, `verification`, `information`. Edge rules are written against kinds. |
| **Type** | A user-defined document type (e.g. `feature`, `user-story`, `test-case`). Every type declares exactly one kind, a unique abbreviation and a default template. |
| **Edge / link** | A typed, directed relationship between two nodes, stored in the source node's JSON. |
| **Template** | A versioned Markdown skeleton plus JSON descriptor that defines the sections of a document body. |
| **Version** | Integer counter per document, incremented when the body or assets change (at commit in Git mode). |
| **Baseline branch** | The Git branch that represents accepted requirements. Configurable, default `main`. |
| **Draft** | A document whose content differs from the baseline branch or does not exist there. |
| **Baseline** | An annotated Git tag marking a named state of the baseline branch. |
| **Change request (CR)** | A first-class entity outside the graph describing a proposed change to a set of documents (its *scope*). Shares the ID space with documents and uses the reserved abbreviation `CHG`. |
| **Scope entry** | A CR's reference to an existing document, with an intent (`modify`, `supersede`, `deprecate`) and the *base version* the CR was analysed against. |
| **Drift** | A scope target changed on the baseline branch, by something other than the CR, after the CR recorded its base version. |
| **Proposed / effective status** | A CR's status in the working tree / on the baseline branch. |
| **Glossary term** | A defined term outside the graph; identity is its slug, not an ID. |
| **Asset** | A binary or non-Markdown file (image, PDF, mockup) owned by exactly one document. |

---

## 3. Repository layout

```
<repo>/
├── .gregraph/
│   ├── config.toml                 # repository configuration (section 5.3, appendix B)
│   ├── templates/
│   │   └── <template-name>/
│   │       └── v<N>/
│   │           ├── template.md     # Jinja2 skeleton
│   │           └── template.json   # descriptor (section 5.5)
│   └── cache/                      # gitignored, rebuildable
│       └── index.json
├── documents/
│   └── <folder-per-type>/          # default folder = type name; config may override
│       ├── RE-STORY-7F3K2Q.md
│       └── RE-STORY-7F3K2Q.json
├── changes/
│   ├── RE-CHG-3M9XA1.md
│   └── RE-CHG-3M9XA1.json
├── glossary/
│   ├── knowledge-base.md
│   └── knowledge-base.json
├── assets/
│   └── RE-STORY-7F3K2Q/            # one folder per owning document, created on demand
│       └── upload-flow.png
├── .gitignore                      # contains .gregraph/cache/
├── AGENTS.md                       # agent instructions; delimited managed block (13.1)
├── .agents/
│   └── skills/
│       └── gregraph/
│           └── SKILL.md            # full agent skill, wholly tool-owned (13.1)
└── README.md                       # generated by init; explains the layout for humans
```

Rules:

- The repository root is the nearest ancestor directory of the current working directory that contains `.gregraph/config.toml`. Commands other than `init` exit with code 3 if none is found.
- Folder placement is organisational only. The tool locates documents by scanning `documents/**`, `changes/`, and `glossary/`; it never infers type from folder.
- The tool moves a document's files if its type's folder changes (`gregraph set <ID> type=...` is not allowed in v0.1; type is immutable after creation — see 5.4). Moving files is therefore only done by `migrate` when a breaking migration produces a new document.
- Filenames are `<ID>.md` and `<ID>.json`. No slugs.
- Glossary filenames are `<slug>.md` and `<slug>.json`.
- `.gregraph/cache/` is always gitignored; `init` writes the `.gitignore` entry.
- (r0.4) `AGENTS.md` and `.agents/skills/gregraph/SKILL.md` at the root are the agent instruction files, written by `init` (13.1) and refreshed by `sync` (13.7) and `repair agents` (13.19). `AGENTS.md` is plain Markdown (no front matter) carrying a delimited *managed block*: when the file already exists — GREGraph initialised inside an existing code repository — all existing content is preserved and the block is appended, or replaced in place when a block is already present. `SKILL.md` is wholly owned by the tool and rewritten wholesale when its content differs; it is the one file allowed YAML front matter (document bodies never get front matter, 5.2). Both are static text generated by the tool, never imported or parsed by it.

---

## 4. Identifiers

### 4.1 Format

`<PREFIX>-<ABBREVIATION>-<6 chars Crockford base32>`, e.g. `RE-FEAT-7F3K2Q`.

- `PREFIX` is a constant, non-semantic, repository-wide string configured in `config.toml` (`ids.prefix`), default `RE`. Allowed characters: `[A-Z][A-Z0-9]{0,7}`.
- `ABBREVIATION` is type metadata: the abbreviation configured for the document's type (§5.3), `[A-Z]{3,5}`, unique across the configured types. Change requests always use the fixed, reserved abbreviation `CHG`; no document type may use `CHG`.
- The 6-character body is the Crockford base32 encoding of the first 30 bits of the document's UUIDv4. Alphabet: `0123456789ABCDEFGHJKMNPQRSTVWXYZ` (no I, L, O, U). Always uppercase. The body remains random and non-semantic.
- Space: 2^30 ≈ 1.07 × 10^9 per `(PREFIX, ABBREVIATION)` pair. Expected collisions at 5,000 documents ≈ 0.012, at 10,000 ≈ 0.047.

The prefix and the abbreviation carry metadata; only the six-character body is random. An identifier is therefore *stable and type-tagged*, not purely non-semantic.

### 4.2 Generation

1. Generate UUIDv4.
2. Derive the human ID: configured prefix, the abbreviation of the document's type (or `CHG` for a change request), and the 6-character body.
3. If the ID exists in the loaded index (including deprecated and superseded documents and CRs), discard the UUID and repeat. Repeat at most 100 times, then fail with an internal error.
4. Store both `uuid` and `id` in the sidecar. The `id` is the only identifier used in filenames, links, and CLI; the `uuid` is the tie-breaker if two branches ever produce the same ID (see 4.4).

A document's type is immutable after creation (§5.3), so its abbreviation — and therefore the type segment of its ID — never changes.

### 4.3 Invariants

- IDs are never reused, including after deprecation or supersession. Documents are never hard-deleted by the tool.
- `id` must equal the filename stem.
- `id` must be derivable from `uuid` with the configured prefix and the abbreviation of the document's type (`CHG` for a CR); `validate` checks this (`E-ID-DERIVATION`).
- The prefix is fixed at `init`. Changing it later is a manual, unsupported operation (`validate` reports every document whose prefix mismatches).
- An abbreviation is fixed once any document of that type exists. Changing it is a hard error (`E-TYPE-ABBREVIATION-CHANGED`); if no document of the type exists, it may be changed freely. Abbreviations are unique across types and `CHG` is reserved.
- Only the three-segment form is valid. Two-segment IDs created before config schema 2 are rejected everywhere (`E-ID-LEGACY`); there are no legacy aliases and no dual-format period.

### 4.4 Cross-branch collisions

Random generation makes collisions across branches improbable but not impossible. If a merge produces two documents with the same `id` and different `uuid` values, `validate` reports a fatal error `E-ID-DUPLICATE` listing both UUIDs. Resolution is manual: the user deletes one of the two documents (the tool provides `gregraph repair regenerate-id <path>` — see 13.19 — which regenerates a new UUID/ID for one of them and rewrites inbound links that reference it *from the same branch's history* — inbound links cannot be disambiguated automatically, so the command lists them for manual re-linking).

### 4.5 Parsing and matching

- The canonical form is always required: three segments, uppercase on disk and in prose. Case-insensitive input is normalised to uppercase, so `re-feat-7f3k2q` matches `RE-FEAT-7F3K2Q`.
- The tool accepts the ID with or without the prefix on the command line if unambiguous (`FEAT-7F3K2Q`). It never accepts the old two-segment form (`RE-7F3K2Q`); such an argument is an unknown ID.
- Interactive pickers match on ID substring and title substring, case-insensitive.
- (r0.4) The case-insensitivity above applies to **input arguments only**. Prose mentions (5.2) require the canonical uppercase form: `[[re-feat-7f3k2q]]` in a body is ordinary prose, never a mention. The old two-segment form matches neither documents nor CRs.

---

## 5. Document model

### 5.1 One document = one node

Every document is exactly one Markdown file and one JSON sidecar with the same stem. The Markdown body is the only part a human edits. The JSON is owned entirely by the tool.

### 5.2 Markdown conventions

- Flavour: GitHub-Flavoured Markdown (CommonMark + tables + task lists + fenced code). Parsing via `markdown-it-py` with the GFM plugin set.
- Encoding UTF-8 without BOM, line endings LF. `sync` normalises CRLF → LF and reports it.
- The first non-blank line must be a level-1 ATX heading (`# Title`). It is the canonical title; `sync` copies it into the sidecar's `title`. If it is missing, `validate` reports `E-TITLE-MISSING`.
- No YAML front matter. If a document starts with `---`, `validate` reports `E-FRONTMATTER-FORBIDDEN`.
- Section structure is defined by the template (5.5). Headings at level 2 are template sections. Users may add level-3+ headings freely inside sections. Users may add extra level-2 sections; `validate` reports them as warnings `W-SECTION-UNKNOWN` (not errors), so that templates can be extended organically.
- References in the body (r0.4, explicit syntax only): a prose *mention* is recognised **only** in explicit reference syntax, never as a bare ID-shaped token:
  - a WikiLink `[[ID]]` or `[[ID|label]]`; or
  - a Markdown link `[text](target)` where `target` matches the ID pattern (case-sensitive), **or** `target` is a relative link that, resolved against the document's directory, names a managed `.md` file whose stem matches the ID pattern (e.g. `[RE-STORY-7F3K2Q](../user-stories/RE-STORY-7F3K2Q.md)`), **or** the trimmed link `text` matches the ID pattern.

  Mention IDs are canonical uppercase (4.5); `[[re-story-7f3k2q]]` is prose. Mentions inside fenced code blocks, code spans and HTML are ignored. Asset links (targets landing in `assets/<ID>/`) remain asset references, never mentions (5.7). A mention is **not** a graph edge. `validate` reports `W-MENTION-UNLINKED` when a document body contains an explicit mention of a document ID with no edge in either direction, and `E-MENTION-UNKNOWN` when an explicit mention matches neither a document nor a CR. Document bodies may mention CR IDs freely; CRs are not graph nodes, so no `W-MENTION-UNLINKED` is raised for them. Mentions inside CR bodies follow section 9.7. (Glossary term usage, 10.2, is unaffected: term matching is name/alias based, not ID based.)
- Images: `![alt](../../assets/RE-STORY-7F3K2Q/file.png)`; see 5.7.

### 5.3 Kinds and types

**Kinds** are fixed in code:

| Kind | Meaning | Typical types |
|---|---|---|
| `goal` | Why. Business goals, epics, capabilities, context/premise narratives. Not directly testable. | `goal`, `epic`, `context` |
| `requirement` | What the system must do or be. Testable or at least fit-criterion-bearing. | `feature`, `user-story`, `functional-requirement`, `non-functional-requirement`, `constraint` |
| `design` | How. Architecture decisions, UI/frontend design, mockups, data models. Treated as requirements for traceability purposes. | `design`, `decision`, `ui-design` |
| `verification` | Evidence. Test cases, acceptance test descriptions, inspection procedures. | `test-case` |
| `information` | Supporting material that participates in the graph but is not a requirement: stakeholders, assumptions, external references. | `stakeholder`, `assumption`, `reference` |

Change requests are not documents and have no kind; they live outside the graph (section 9).

**Types** are defined in `config.toml`:

```toml
[types.user-story]
kind = "requirement"
abbreviation = "STORY"      # [A-Z]{3,5}, unique across types; required
template = "user-story"     # default template name; latest non-deprecated version is used
folder = "user-stories"     # optional; default = type name
```

- Type names: `[a-z][a-z0-9-]*`, unique.
- Every type has a required `abbreviation`, matching `[A-Z]{3,5}` and unique across all configured types. `CHG` is reserved for change requests and may not be used by a document type. The abbreviation is the type segment of every ID of that type (§4.1). A missing, malformed, duplicate or reserved abbreviation is a configuration error (exit 3).
- A type's `kind` and `abbreviation` are immutable once any document of that type exists (`validate` enforces `E-TYPE-KIND-CHANGED` and `E-TYPE-ABBREVIATION-CHANGED` if the index cache disagrees with config; the cache stores the kind and abbreviation seen at last run). If no document of the type exists, either may be changed freely.
- Shipped default types are listed in appendix B. `init` writes them into `config.toml`; users edit `config.toml` to add types (this is the one non-Markdown file users edit, and only for configuration).
- A document's `type` is immutable after creation in v0.1. To change type, supersede with a document of the new type.

### 5.4 Sidecar JSON schema (documents)

CR sidecars are specified in section 9.2, glossary sidecars in section 10.2.

```json
{
  "schema": 1,
  "uuid": "6f3c2f1e-8b3e-4a4c-9a3d-2d0f5b7a9c11",
  "id": "RE-STORY-7F3K2Q",
  "type": "user-story",
  "title": "Upload documents to a knowledge base",
  "created": "2026-09-10T14:02:11Z",
  "created_by": { "name": "Jane Doe", "email": "jane@example.org" },
  "template": { "name": "user-story", "version": 2 },
  "version": 3,
  "body_hash": "sha256:9c1d…",
  "assets": [
    { "path": "upload-flow.png", "hash": "sha256:41ab…" }
  ],
  "links": [
    { "type": "refines", "target": "RE-FEAT-2K7QMB", "target_version": 4 },
    { "type": "depends-on", "target": "RE-CON-9PZ0AH", "target_version": 1 }
  ],
  "deprecated": null,
  "tags": [],
  "extra": {},
  "origin_cr": null
}
```

Field rules:

| Field | Mandatory | Owner | Notes |
|---|---|---|---|
| `schema` | yes | tool | Sidecar schema version, currently `1`; independent of `config_schema`. |
| `uuid` | yes | tool | Immutable. |
| `id` | yes | tool | Immutable typed ID (`<PREFIX>-<ABBREVIATION>-<body>`); equals filename stem. |
| `type` | yes | tool | Immutable in v0.1. |
| `title` | yes | tool (from H1) | Synced from the body. |
| `created` | yes | tool | ISO 8601 UTC, second precision, `Z` suffix. |
| `created_by` | no | tool (from Git) | `null` when Git identity unavailable; `new` warns. |
| `template` | yes | tool | Name and version pinned at creation or migration. |
| `version` | yes | tool | Starts at 1. |
| `body_hash` | yes | tool | `sha256:` + hex of the normalised body (7.3). |
| `assets` | yes (may be empty) | tool | Files referenced from the body that exist under `assets/<ID>/`. |
| `links` | yes (may be empty) | tool | Outbound edges only. |
| `deprecated` | yes (nullable) | tool | `null` or `{ "at": ISO, "by": identity|null, "reason": string }`. |
| `tags` | yes (may be empty) | tool via `set` | Lowercase strings `[a-z0-9-]+`. |
| `extra` | yes (may be empty) | tool via `set` | Free string→string map for team-specific metadata (`priority`, `owner`, …). Not validated in v0.1. |
| `origin_cr` | yes (nullable) | tool | ID of the CR that introduced this document (`new --cr`, `supersede --cr`, section 9.5); `null` otherwise. Metadata, not an edge. |

Minimal mandatory set the user cannot remove: `schema, uuid, id, type, title, created, template, version, body_hash, assets, links, deprecated`. `tags`, `extra`, `created_by`, `origin_cr` are present but may be empty/null.

Serialisation: `json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True)` + trailing newline. Deterministic output keeps Git diffs minimal. Links are sorted by `(type, target)`.

### 5.5 Templates

A template is a directory `.gregraph/templates/<name>/v<N>/` containing:

`template.md` — a Jinja2 template. Available variables: `title`, `id`, `type`, `kind`, `created`, `author` (name or empty string), plus `sections` (list, for templates that generate their own headings). Shipped templates write headings literally and use variables only for the H1.

`template.json`:

```json
{
  "schema": 1,
  "name": "user-story",
  "version": 2,
  "description": "User story with Gherkin acceptance criteria",
  "deprecated": false,
  "breaking": false,
  "sections": [
    { "heading": "Story", "required": true,
      "placeholder": "As a <role>, I want <capability>, so that <benefit>." },
    { "heading": "Acceptance criteria", "required": true,
      "placeholder": "Given … When … Then …" },
    { "heading": "Rationale", "required": false, "placeholder": "",
      "renamed_from": ["Motivation"] },
    { "heading": "Notes", "required": false, "placeholder": "" }
  ]
}
```

- `version` is a positive integer; directories must be contiguous from `v1`.
- `deprecated: true` marks a template version that should no longer be used. `new` refuses it unless `--template-version` is given explicitly with `--allow-deprecated`; `validate` warns `W-TEMPLATE-DEPRECATED` for every document pinned to it; `status` counts them.
- `breaking: true` means this version cannot be reached by in-place migration from the previous version; migration must supersede (7.7).
- `renamed_from` lets in-place migration rename a section heading.
- Sections are matched by exact heading text (case-sensitive, after trimming). Required sections must be present. A section is *empty* if its content, after stripping whitespace and HTML comments, is empty or equals the placeholder text.

Template resolution order for `new`: repository templates only. Built-in templates live inside the Python package and are only *copied* into the repository by `init` (and by `gregraph template add <builtin-name>` to add one later). A package upgrade therefore never changes what an existing repository validates against.

A user-level template directory (`~/.config/gregraph/templates/`) is **not** supported in v0.1; templates must be in the repository so that all collaborators share them.

### 5.6 Title handling

- `new` writes `# <title>` as the first line.
- `sync`, the hook, and every read of a document compare H1 to `title` and update the sidecar when they differ. A title change alone changes `body_hash` and therefore bumps `version`.

### 5.7 Assets

- Directory `assets/<ID>/`, created on demand by the tool when the user first references a file, or by the user (this is the one exception to "the tool creates files": users may drop files into `assets/<ID>/`).
- The body references assets with relative paths. The tool resolves any path that, after normalisation, lands inside `assets/<ID>/`. References to other documents' asset folders are errors `E-ASSET-FOREIGN` (assets are single-owner; copy the file).
- On sync/hook, `assets` in the sidecar is recomputed: every referenced file that exists is listed with its SHA-256. Referenced-but-missing → `E-ASSET-MISSING`. Present-but-unreferenced → `W-ASSET-ORPHAN`.
- Asset changes participate in versioning: a document's version bumps if either `body_hash` or any asset hash changes (7.3). This gives assets version tracking through their owning document without separate machinery.
- Allowed extensions are not restricted. Files larger than `assets.max_size_kb` (config, default 5120) produce `W-ASSET-LARGE`.

---

## 6. Graph model

### 6.1 Edge types (fixed in v0.1)

Directed edges are stored on the **source** node. "A refines B" is stored in A's sidecar as `{type: "refines", target: "B"}`. Symmetric edges are stored on the node where they were created; the index treats them as undirected.

| Type | Direction | Kind rules (source → target) | Meaning / use when | Example |
|---|---|---|---|---|
| `refines` | directed, hierarchical | {goal, requirement} → {goal, requirement} | Source states the *same intent* as target, more concretely. Satisfying all refinements should satisfy the target. This is the decomposition edge. | user-story → feature; feature → epic |
| `derives-from` | directed, hierarchical | {requirement, design} → {goal, requirement, design} | Source is a *new* requirement that exists *because of* target but is not a decomposition of it. Use when a design choice or another requirement causes a consequence. | "KB uploads must be virus-scanned" derives-from "Use shared storage" |
| `depends-on` | directed | {goal, requirement, design} → {goal, requirement, design} | Source cannot be implemented or is meaningless unless target is realised. Ordering, not decomposition. | "Attach KB to agent" depends-on "Create agent" |
| `satisfies` | directed | {design} → {goal, requirement} | A design element realises a requirement. | "Ingestion pipeline design" satisfies "Upload documents" |
| `verifies` | directed | {verification} → {requirement, design} | A test or inspection provides evidence for a requirement or design. | test-case → user-story |
| `constrains` | directed | {requirement} → {goal, requirement, design} | Source is a cross-cutting requirement (NFR, constraint) that limits how target may be realised. Use instead of `refines` for quality attributes that apply to many nodes. | "P95 latency < 3 s" constrains "Chat with agent" |
| `supersedes` | directed | same kind → same kind | Source replaces target. Target becomes *superseded*. Multi-target allowed (one edge per target). | new requirement → old requirement |
| `conflicts-with` | symmetric | {goal, requirement, design} ↔ same set | The two cannot both be satisfied as written. Recorded to make conflict visible until resolved (section 11). | NFR "no data leaves EU" ↔ feature "use US-hosted model" |
| `relates-to` | symmetric | any ↔ any | Weak association with no other semantics. Use sparingly; prefer a typed edge. | stakeholder ↔ goal |

Change requests are not graph nodes and have no edges; their relationship to documents is the CR's *scope* (section 9.4).

Guidelines the tool prints in `gregraph link --help`:

- Ask "if the target were deleted, would the source still make sense as written?" If no and the source is a *more concrete version* of the target → `refines`. If no and the source is a *different* requirement caused by it → `derives-from`. If yes but the source can't be built first → `depends-on`.
- Never model quality attributes as children. Use `constrains`.
- A `design` node never `refines` a requirement; it `satisfies` it.
- A `verification` node only ever `verifies`.
- `relates-to` is the last resort.

### 6.2 Acyclicity

- The **directed edge set** `{refines, derives-from, depends-on, satisfies, verifies, constrains, supersedes}` forms a single graph that must be acyclic. Cycles across different edge types are forbidden (e.g. A `refines` B and B `depends-on` A is rejected).
- Symmetric edges never participate in cycle detection.
- Rejection happens at **link time**: `gregraph link` computes whether adding the edge creates a path from target back to source (DFS/BFS from target over outbound directed edges; target reaching source means cycle) and refuses with `E-CYCLE` listing the path. `validate` re-checks the whole graph (Kahn's algorithm) and reports `E-CYCLE` for any cycle found in files edited outside the tool.

### 6.3 Roots, orphans, multiple roots

**[DECISION] Multiple roots are allowed.** Argument: a system always serves several top-level intentions that are not refinements of one another — a business goal ("increase self-service"), a compliance goal ("meet GDPR"), a quality goal ("keep operating cost per conversation under X"). Forcing a single synthetic root ("The product shall be good") adds a node with no content, no owner, and no fit criterion; it only exists to satisfy a data structure. The graph therefore has a *set* of roots. A root is a node with no outbound `refines` or `derives-from` edge. `list --roots` shows them.

- **Orphan**: a node with no edges of any type in either direction, excluding deprecated/superseded nodes. `validate` reports `W-ORPHAN`. Not an error: a freshly created document is an orphan until linked.
- **Dangling**: an edge whose target does not exist. `E-LINK-TARGET-MISSING`.

### 6.4 Edge multiplicity

- At most one edge of a given type between the same ordered pair. Adding a duplicate is a no-op with a notice.
- Different types between the same pair are allowed where rules permit (e.g. `depends-on` and `relates-to`), but `refines` and `derives-from` between the same ordered pair are mutually exclusive (`E-EDGE-EXCLUSIVE`), as are `refines`/`derives-from` in one direction with `depends-on` in the opposite direction (that is a cycle anyway).

### 6.5 Inbound view

The index computes inbound edges for every node. `show` displays both outbound and inbound edges; symmetric edges appear on both nodes.

---

## 7. Versioning and change tracking

### 7.1 Evaluation of the candidate models

Four models were evaluated. Criteria: ease of use for a requirements engineer (E), feasibility of implementation in v0.1 (F), rigor of the change record (R), interaction with templates and links (T).

**Model 1 — Classic mutable documents with hash-based suspect links.**
Links store a hash of the target at link time; a changed target makes inbound links suspect.
E: high (edit in place). F: high. R: medium (the hash says "changed", not "how much" or "which version"). T: template migration in place is trivial. Weakness: a hash is opaque; users cannot say "link confirmed against version 3", only "it changed since I last looked".

**Model 2 — Frozen after merge, links target a lineage.**
Every edit after merge creates a new version node under the same lineage; edges point to the lineage and resolve to the newest active version.
E: low-medium (every typo is a new node; IDs grow a version suffix; "which version did they mean" is ambiguous). F: medium (lineage resolution everywhere). R: highest. T: migration = new version node. Rejected: too much ceremony for a small team, and lineage-resolving links quietly change meaning whenever a target is edited — the opposite of what a reviewer wants.

**Model 3 — Frozen after merge, links target versions, JSON mutable.**
Body freezes on merge; edits require supersession; the tool re-points inbound links on supersede.
E: low (typo → new ID). F: medium. R: high. T: migration = supersede. Rejected for the same ceremony reason; supersession touching many files per edit also creates merge conflicts.

**Model 4 — Mutable documents with integer versions and version-tracked links (the RE's draft).**
The body is mutable. A counter `version` in the sidecar is bumped when the committed content changes. Each link records the `target_version` it was confirmed against. Outdated links are reported; the pre-commit hook blocks a commit that newly outdates links until they are refreshed. The same check runs manually. Supersession remains for semantic replacement and breaking template changes.
E: high (edit in place; the only extra step is refreshing links after substantive edits, which is precisely the review a change should trigger). F: high (hashes + a counter; Git only supplies the trigger). R: high enough (every version is a commit; the version number is human-meaningful: "confirmed against v3"). T: additive template changes migrate in place (bump version); breaking ones supersede.

**[DECISION] Model 4 is adopted**, with these refinements over the draft:

1. **Change detection is hash-based in both modes.** The draft proposed Git-based detection when Git is present. Git only knows what changed since HEAD; it does not know whether the change was already counted. A stored `body_hash` answers "changed since the last bump" uniformly, so the hook and the non-Git `sync` share one code path. Git determines *when* the bump happens (at commit) and supplies draft/active status; it is not needed to detect content change.
2. **Blocking is scoped to links newly outdated by the commit in progress.** Links that were already outdated before this commit (e.g. because a colleague's merge bumped a target) are reported but never block; otherwise one person's edit would block everyone else's unrelated commits.
3. **Blocking is configurable** (`versioning.on_outdated_links = "block" | "warn"`, default `block`). `git commit --no-verify` remains available as the standard escape hatch and is documented, not hidden.
4. **Refresh is a review act.** `gregraph link refresh` is meant to be run by someone who has re-read the link. The tool cannot enforce that; the process does.

### 7.2 Version semantics

- `version` starts at 1 on creation.
- `version` increments by exactly 1 each time the tool records that the *content* (normalised body or any asset) differs from the stored hashes.
- In Git mode the increment happens in the pre-commit hook for staged files (and in `gregraph sync --bump` for explicit use). Uncommitted edits do not bump; they are visible as *pending* (`status` shows "modified, unbumped").
- **Initial-grace period (r0.4, D-AGENT-3).** While an item is at `version == 1` **and** absent from Git `HEAD` (untracked *or* staged-but-uncommitted), reconcile treats an effective content change as *populating the initial version*, not as a change: the recomputed `body_hash`, title (from H1, 5.6) and assets are updated **in place**, the version stays `1`, and the reconcile report classifies the item in the `initialised` bucket (7.5). The state ends when the item first appears in `HEAD`; from then on normal semantics apply (a further content change is an unbumped modification until the next bump). This applies to documents, CRs and glossary terms alike, so the first hook commit of a template-filled document is its real `v1`, and links recorded against the uncommitted `v1` stay fresh (7.4).
- In degraded mode (no Git) `gregraph sync` performs the bump. **Degraded mode has no grace period**: there is no commit step, so `sync` *is* the versioning act and bumps exactly as before.
- Versions are never decremented. After a merge conflict in a sidecar, the user resolves the text conflict and runs `gregraph repair versions`, which sets `version = max(versions seen in conflict markers) + 1` and recomputes hashes. v0.1 ships a small parser for the standard conflict-marker layout to extract both `version` values.
- **Identifier-migration exception (r0.5).** The standalone schema-1 → schema-2 migration (`scripts/migrate_type_ids.py`, `docs/migration-typed-ids.md`) rewrites identifier text in bodies, sidecars, filenames and config. It is an identifier rewrite, not a semantic content change: it preserves every `version`, every link `target_version` and every CR `base_version`, and recomputes `body_hash`/`scope_hash` because the text changed. This is the only case where a stored hash changes without a version bump, and it is performed only by that script, never by `sync`, the hook or any `gregraph` command.

### 7.3 Content hash

`body_hash = "sha256:" + sha256(normalised_body)` where normalisation is: decode UTF-8, convert CRLF/CR to LF, strip trailing whitespace on every line, collapse three or more consecutive blank lines to two, ensure exactly one trailing newline. The H1 line is included (title changes count). The identifier migration (7.2) recomputes this hash after rewriting ID text without bumping `version`.

Asset hashes are SHA-256 of raw bytes. A document's *effective content* changed iff `body_hash` differs or the sorted list of `(path, hash)` differs.

### 7.4 Link freshness

Each link records `target_version`. Definitions:

- **Fresh**: `target_version == target.version` and target is neither deprecated nor superseded. For a target in the initial-grace state (7.2) the effective version is `1`, so a link recorded against the uncommitted `v1` is fresh — before and after the initial commit.
- **Outdated**: `target_version < target.version`. The target's content changed after the link was last confirmed.
- **Stale**: target is deprecated or superseded (regardless of version).
- **Pending-outdated** (Git mode only): the target has unbumped modifications and the link was confirmed against the target's *effective* version (`target_version == target.version + 1`); on the next commit the link will become outdated. `check` and `status` show this; it is what allows a user to see impact *before* committing. `validate` reports it as `W-LINK-PENDING` with the fix `gregraph sync --bump` (or, in hook context, the note that the commit in progress resolves it). `W-LINK-PENDING` is **suppressed** while the target is in the initial-grace state (7.2): a draft being populated is not a pending-outdated state.

`target_version` is measured against the target's **effective** version (r0.4, D-AGENT-7), not the stored one: `target_version == effective_version` on a target with unbumped modifications is the `W-LINK-PENDING` state above — a warning, never an error. Only `target_version > effective_version` is `E-LINK-VERSION-AHEAD` (a real merge mishap; `repair versions` fixes it by clamping). For an uncommitted `v1` item in the initial-grace state the effective version is `1` (7.2).

**Effective version rule for refresh.** `gregraph link refresh` sets `target_version` to the target's *effective* version: `target.version + 1` if the target currently has unbumped modifications, otherwise `target.version`. This lets a user edit A and refresh B→A in the same commit without the hook immediately re-flagging the link.

### 7.5 The reconcile operation (shared by hook, `sync`, `check`)

`reconcile(scope, mode)` where `scope` is a set of documents (staged files for the hook, all documents for `sync`/`check`) and `mode` ∈ {`bump`, `report`}:

1. For each document in scope: normalise, hash body, hash assets, sync title from H1. For each CR in scope: normalise, hash body and scope (section 9.2), sync title; CRs have no assets.
2. If effective content changed: an item in the initial-grace state (7.2) is **populated in place** at `version 1` — store the new hashes, title and assets, write the sidecar, do not increment — and the report classifies it as `initialised` (r0.4). Otherwise, if `mode == bump`: `version += 1`, store new hashes, write sidecar. In Git mode the hook additionally runs `git add` on the rewritten sidecar so it is part of the same commit (for both buckets).
3. Compute the link freshness table for the whole graph using effective versions (7.4).
4. Run validation (section 14).
5. Return a report: initialised items (uncommitted `v1` documents, CRs and terms populated in place, r0.4), bumped documents, newly outdated links (those whose target is in the bumped set and `target_version < new version`), previously outdated links, stale links, pending-outdated links, validation findings.

Hook behaviour (`gregraph hook pre-commit`):

- Scope = staged `.md` files under `documents/`, `changes/`, `glossary/` plus documents whose staged assets changed. Also any document whose sidecar is staged (to catch tool-made changes).
- `mode = bump`.
- Exit non-zero (abort commit) if: any validation *error*; or newly outdated links exist and policy is `block`. Print the full report with the exact `gregraph link refresh …` commands that would resolve it.
- Warnings never abort.

`gregraph sync`: scope = all; `mode = bump` in degraded mode, `report` in Git mode unless `--bump` is given. Also normalises line endings and rewrites sidecars whose serialisation is not canonical.

`gregraph check`: scope = all working-tree changes (staged or not); `mode = report`; exits non-zero under the same conditions as the hook. This is "what would the hook say".

### 7.6 Supersession

`gregraph supersede <OLD-ID> [--title T] [--type TYPE] [--copy-body] [--copy-links]`:

1. Creates a new document (default: same type, latest template; `--type` may pick another type of the **same kind**).
2. `--copy-body` (default on when the template is the same; off otherwise) copies the old body, replacing the H1 with the new title.
3. Adds edge `NEW supersedes OLD`.
4. `--copy-links` (default on) copies all of OLD's outbound edges (except `supersedes`) to NEW with the same `target_version` values; cycle and rule checks run for each.
5. OLD's inbound edges are left untouched; they become *stale* and are listed. `gregraph link refresh <src> <OLD>` on a stale link whose target is superseded offers (interactive) or performs (`--follow`) re-pointing to the successor, following a `supersedes` chain to its end. If the chain forks (OLD superseded by two documents, i.e. a split), the user must choose.
6. Multiple targets: `gregraph supersede A B --title "…"` creates one document superseding both (used for conflict compromise, section 11).
7. `--cr CR` records the new document as introduced by that CR (section 9.5). If OLD is not in the CR's scope, the tool prints a notice suggesting `gregraph cr scope add CR OLD --intent supersede`; it does not change the scope itself, because scope is part of what was decided.

A superseded document keeps its files, remains readable, and can no longer be linked as a target of any *new* directed edge except `supersedes` (`E-TARGET-SUPERSEDED`).

### 7.7 Template migration

Each document pins `template.name` and `template.version`. Validation always uses the pinned version, so a template change never invalidates existing documents by itself.

`gregraph migrate [<ID>… | --all | --template NAME] [--to VERSION] [--dry-run]`:

- Determines, for each selected document, the target template version (`--to`, default: latest non-deprecated).
- **In-place migration** is possible iff every version step from the pinned version to the target has `breaking: false`. Steps: for each section in the target that is missing in the body, insert `## <heading>` with the placeholder at the template's position (after the nearest preceding known section); apply `renamed_from`; sections present in the body but absent in the target are left in place (they become `W-SECTION-UNKNOWN`). Update `template.version`; content changed → the next commit bumps `version` as usual (in-place migration is a content change; inbound links become outdated, correctly signalling "re-check").
- **Superseding migration** is used when any step is breaking, or when `--supersede` is given. The tool creates a new document with the target template, copies sections whose headings match (after `renamed_from`), appends unmatched content under `## Unmapped content (migration)`, supersedes the old one (7.6), copies links, and prints what needs manual attention. The user edits the new draft, then commits.
- `--dry-run` prints the plan without writing.

Deprecating a template version: the user sets `"deprecated": true` in the template's `template.json` (configuration editing by humans is allowed). `validate` then reports `W-TEMPLATE-DEPRECATED` per document; `status` shows the count; `gregraph migrate --template NAME --dry-run` shows what would happen. This gives "automatically determine which documents need updating".

Template editing: users may edit `.gregraph/templates/<name>/v<N>/` files directly *only* to set `deprecated` and `description`. New versions are created with `gregraph template bump <name> [--breaking]`, which copies `v<N>` to `v<N+1>`, opens nothing, and lets the user edit the new version's files. `validate` checks that no shipped-to-repo template version that has documents pinned to it has changed its `sections` since the cache last saw it (`E-TEMPLATE-MUTATED`); the fix is to create a new version instead.

---

## 8. Status model

Status is **derived**, never stored, except for one flag (`deprecated`).

| Status | Rule | Available without Git |
|---|---|---|
| `draft` | File is untracked, or its content (body or sidecar) differs from the baseline branch. Computed via `git diff --quiet <baseline> -- <path>` and `git ls-files --error-unmatch`. | no → reported as `unknown` |
| `active` | Tracked, identical to baseline branch, not superseded, not deprecated. | no → `unknown` |
| `superseded` | Has at least one inbound `supersedes` edge. | yes |
| `deprecated` | `deprecated != null`. | yes |

Precedence: `deprecated` > `superseded` > `draft` > `active`.

These statuses apply to documents and glossary terms. Change requests have their own status model (section 9.3).

The baseline branch is `git.baseline_branch` in config, default `main`. If the branch does not exist locally, status degrades to `unknown` with a warning. The tool compares against the *local* baseline branch; fetching is the user's job.

Acceptance is implicit: merging into the baseline branch makes a document `active`. No `approved` state exists.

Deprecation without replacement: `gregraph deprecate <ID> --reason "…"` sets the flag. `gregraph undeprecate <ID>` clears it. Deprecated documents cannot be targets of new directed edges except `supersedes` (`E-TARGET-DEPRECATED`); existing inbound links become *stale*.

**WIP state.** The repository is in WIP state if any document is `draft`, any document has unbumped modifications, or any file under the managed directories is uncommitted. `gregraph status` prints a header line `WIP: yes (3 drafts, 1 modified)` or `WIP: no`, and exits 0 regardless. Nothing blocks on WIP in v0.1; the web UI will use the same API to display it.

---

## 9. Change requests

### 9.1 Position and rationale

A change request (CR) is a first-class entity **outside the graph**, like the glossary. It describes a proposed change to a set of existing documents (its *scope*), records the version each of those documents had when the change was analysed, tracks the new documents it introduced, and carries a decision history.

**[DECISION] Revised in r0.2.** In r0.1 CRs were graph nodes of kind `change` with `affects` edges. Review found five defects:

1. Implementing an accepted CR bumped the affected documents, which newly outdated the CR's own `affects` links, so the pre-commit hook blocked the very commit that implemented the CR.
2. Refreshing those links overwrote the versions the CR had been analysed against, which is the one fact a CR needs to keep.
3. Documents created because of a CR could not point back to it, since CRs were never link targets.
4. A CR carried both a derived document status (`draft`/`active`) and a stored CR status, and the CR status was set by command rather than by merge, unlike everything else.
5. The graph needed CR-specific exceptions in edge rules, orphan detection, export and freshness reporting.

Separating CRs from the graph mirrors configuration-management practice (ISO 10007, EIA-649, the problem and change management of the V-Modell XT): a change record is a process artefact that refers to specific versions of the product description rather than being part of it.

Change requests share the identifier space with documents but use the fixed, reserved abbreviation `CHG` (§4.1): `<PREFIX>-CHG-<6-char body>`, e.g. `RE-CHG-3M9XA1`.

CRs are optional. With `cr.enabled = false`, the `cr` commands and every `--cr` flag refuse with `E-CR-DISABLED`; existing CR files are still validated.

### 9.2 Files and sidecar

CRs live in `changes/<ID>.md` and `changes/<ID>.json`; the directory is fixed. IDs come from the same generator and the same ID space as documents (section 4), with the fixed `CHG` abbreviation. The body is created from the template named in `cr.template` (default `change-request`); the template version is pinned and the body is validated against it exactly like a document body (section 5.5). The H1 rule (5.6) applies. CRs have no assets in v0.1.

```json
{
  "schema": 1,
  "uuid": "0b9e7c1a-3d2f-4e8b-9a61-5c4d2e1f0a77",
  "id": "RE-CHG-3M9XA1",
  "title": "Raise knowledge-base upload limit to 200 MB",
  "created": "2026-09-10T09:00:00Z",
  "created_by": { "name": "Jane Doe", "email": "jane@example.org" },
  "template": { "name": "change-request", "version": 1 },
  "version": 2,
  "body_hash": "sha256:…",
  "scope_hash": "sha256:…",
  "scope": [
    { "id": "RE-STORY-7F3K2Q", "intent": "modify", "base_version": 3 },
    { "id": "RE-CON-9PZ0AH", "intent": "supersede", "base_version": 1 }
  ],
  "introduces": ["RE-FEAT-Q4M2ZT"],
  "status": "accepted",
  "decisions": [
    { "status": "open", "at": "2026-09-10T09:00:00Z", "by": { "name": "Jane Doe", "email": "jane@example.org" }, "at_version": 1 },
    { "status": "accepted", "at": "2026-09-12T15:30:00Z", "by": { "name": "Max Mustermann", "email": "max@example.org" }, "at_version": 2 }
  ],
  "branch": null,
  "external_ref": null,
  "tags": [],
  "extra": {}
}
```

**Content and versioning.** A CR's content is its normalised body **plus its scope**. `scope_hash` is `sha256:` + hex of the canonical JSON of `scope` (sorted by `id`). The CR's `version` is bumped by the same reconcile pass as documents (7.5) whenever `body_hash` or `scope_hash` changes. Excluded from content: `status`, `decisions`, `introduces`, `branch`, `external_ref`, `tags`, `extra`. Status and decisions must be excluded because recording a decision would otherwise change the content the decision refers to. `introduces` must be excluded because implementing a CR would otherwise invalidate its own acceptance.

The identifier migration (7.2) preserves a CR's `version` and every scope entry's `base_version`; it recomputes `body_hash` and `scope_hash` because the rewritten IDs are part of both.

All fields shown are mandatory; lists may be empty; `created_by`, `branch`, `external_ref` are nullable. `scope` is sorted by `id`, `introduces` is sorted. Serialisation is canonical (5.4).

### 9.3 Status, decisions, and effective status

Statuses: `open`, `accepted`, `rejected`, `implemented`. `implemented` replaces r0.1's `done` so as not to imply verification.

| From | Allowed transitions |
|---|---|
| (created) | `open` |
| `open` | `accepted`, `rejected` |
| `accepted` | `implemented`, `open` (reopen) |
| `rejected` | `open` (reopen) |
| `implemented` | `open` (reopen, e.g. after a revert) |

Every transition is made with `gregraph cr set CR status=<s>` and appends a decision `{status, at, by, at_version}`. `at_version` is the CR's *effective* version (rule of 7.4: `version + 1` if content changes are pending). Creation appends the initial `open` decision with `at_version = 1`. `E-CR-STATUS` is reported when `status` differs from the last decision or the decision sequence contains an invalid transition.

**Proposed vs. effective status.** The status in the working tree is the *proposed* status. The *effective* status is the status in the CR's sidecar on the baseline branch (`git show <baseline>:changes/<ID>.json`), or `none` if the CR does not exist there. Output shows both when they differ, e.g. `accepted (proposed; effective: open)`. This is information, not a warning: on any feature branch every new decision is proposed until merged, so a warning would be permanent noise. Without Git, effective status equals proposed status.

The authority of a decision is therefore the authority of the merge into the baseline branch, consistent with "acceptance by merge" for documents (section 8). The tool implements no access control; teams that need it use branch protection and required reviews on their Git host. Optionally, `cr.deciders` lists e-mail addresses; when non-empty, `validate` reports `W-CR-DECIDER-UNKNOWN` for every decision other than the initial `open` whose `by` is null or not in the list. This is advisory only, because Git identities are self-declared.

**Modified after decision.** If the last decision is not `open` and the CR's effective version is greater than that decision's `at_version`, `validate` reports `W-CR-MODIFIED-AFTER-DECISION`. Because scope is content, this also fires when scope entries are added, removed, or re-analysed after a decision. That is intentional: the decision was taken on a different scope. Resolution: reopen (`cr set status=open`) and decide again, or `gregraph cr reaffirm CR`, which appends a decision with the current status at the current effective version. Policy `versioning.on_cr_modified` (`warn` by default, or `block`) controls whether the hook aborts.

### 9.4 Scope

A scope entry `{id, intent, base_version}` states that the CR changes an existing document:

- `modify`: the document's body or assets will be edited;
- `supersede`: the document will be superseded (including a compromise or a superseding migration);
- `deprecate`: the document will be deprecated without replacement.

Rules:

- Entries are managed only by the tool: `cr new --scope TARGET[:INTENT]…`, `cr scope add CR TARGET [--intent I]` (default `modify`), `cr scope remove CR TARGET`.
- At the time of adding, the target must be an existing document (not a CR, not a glossary term), must be neither superseded nor deprecated in the working tree, and may appear at most once per CR. Violations are refused with `E-CR-SCOPE-TARGET`. `validate` reports the same code for scope entries naming a non-existent ID, a non-document, or a duplicate. (It does not re-check liveness, since a `supersede` or `deprecate` intent legitimately makes the target non-live.)
- **Base version.** In Git mode, `base_version` is the target's version **on the baseline branch** at the time the entry is added, not the working-tree version, which may already contain this CR's own edits. If the target does not exist on the baseline branch, the command refuses (`E-CR-SCOPE-TARGET`) and points to `--cr`: a document that does not exist on the baseline is new work and belongs in `introduces`. In degraded mode, `base_version` is the target's effective working-tree version.
- `base_version` is never updated implicitly. `gregraph cr reanalyze CR [TARGET…]` sets it to the current baseline version (degraded mode: effective working-tree version) for the given entries, or for all entries. Reanalysis changes the scope and therefore the CR's content; for a decided CR it triggers `W-CR-MODIFIED-AFTER-DECISION`, and the decision has to be reaffirmed. This is the intended ceremony: a new basis for analysis needs a new or confirmed decision.
- Scope entries are **not edges**. They are excluded from cycle detection, kind rules, link freshness, inbound views, orphan detection, and graph export, and they never cause the pre-commit hook to block.

### 9.5 Origin tracking

`gregraph new … --cr CR` and `gregraph supersede … --cr CR` record which CR introduced a new document:

- the new document's sidecar gets `origin_cr = CR`;
- the CR's `introduces` list gets the new ID.

The CR's proposed status must be `open` or `accepted`; otherwise the command refuses with `E-CR-CLOSED`. `origin_cr` is metadata, not an edge. `validate` reports `E-CR-ORIGIN-MISSING` when `origin_cr` names a non-existent CR, and `E-CR-ORIGIN-MISMATCH` when `origin_cr` and `introduces` disagree in either direction.

### 9.6 Drift and implementation checks

**Drift** means a scope target was changed on the baseline branch, by something other than this CR, after the CR was analysed. It is evaluated only in Git mode and only while the CR's **effective** status is `open` or `accepted`. The tool loads the baseline-branch view of all sidecars once per invocation, and only when a CR check needs it (`files_at`, section 12.1). It reports `W-CR-BASE-DRIFT` for a scope entry if either:

- the target's version on the baseline branch is greater than `base_version`; or
- the target is superseded or deprecated on the baseline branch. Supersession and deprecation do not bump the target's version, so the version comparison alone would miss them.

The check distinguishes the CR's own changes from other people's: on the CR's branch, its own edits are not on the baseline branch yet; after merge, the CR's effective status should be `implemented`, at which point drift is no longer evaluated. Known false positive: if an implementation is merged while the CR's effective status is still `accepted` (status update forgotten, or deferred to a later PR), it is reported as drift. The finding's message names this case and suggests `cr set status=implemented`. To resolve genuine drift, re-read the changed targets, then run `gregraph cr reanalyze`.

**Implementation check.** When the proposed status is `implemented`, each scope entry is evaluated against the **working tree**:

- `modify` requires the target's effective version to be greater than `base_version`;
- `supersede` requires an inbound `supersedes` edge;
- `deprecate` requires the deprecation flag.

Unmet entries produce `W-CR-IMPLEMENTED-UNCHANGED`. Evaluating against the working tree makes the check work both on the implementing branch before merge and on the baseline branch after it.

Neither check establishes that a change is *correct*. Verification state is out of scope for v0.1.

### 9.7 Mentions in CR bodies

CR bodies follow the same mention grammar as document bodies (5.2, explicit syntax only): a mention is `[[ID]]`, `[[ID|label]]`, or a Markdown link whose target or text resolves to an ID or a managed `.md` path; bare ID-shaped tokens are never mentions. Unknown IDs produce `E-MENTION-UNKNOWN`. An explicitly mentioned document ID that is in neither `scope` nor `introduces` produces `W-CR-MENTION-UNSCOPED`, a hint that the CR may change something it does not declare. Mentions of other CRs are not checked.

### 9.8 Impact view

`gregraph cr show CR` prints:

- proposed and effective status, and the decision history;
- each scope entry with its intent, base version, baseline version, working-tree version, live state, and drift;
- each introduced document with its status;
- the impact set: for every scope target, one level upstream and unlimited depth downstream as in `show` (13.11), de-duplicated.

The impact set is meant as input for the template's *Impact* section. The tool never writes into the body.

### 9.9 Workflows

The tool supports two workflows and enforces neither.

*Proposal-first* (formal change control):

1. Create the CR on a branch and merge it. Effective status: `open`.
2. On a decision branch, run `cr set status=accepted` (or `rejected`), have it reviewed, and merge. The merge is the decision.
3. On an implementation branch, edit the scope targets, create documents with `--cr`, run `cr set status=implemented`, and merge.

*Single-PR* (small teams): one branch creates the CR, declares its scope, records `accepted`, implements the change, and records `implemented`. The merge of that branch is the decision, and all decisions become effective at once.

Rejection is a merged `rejected` decision. `branch` and `external_ref` (an issue key or PR URL) are free text set via `cr set`; they bridge to whatever tooling the team already uses.

### 9.10 Known limitations

- No access control; `cr.deciders` is advisory.
- No verification state: `implemented` means "changed as declared", not "verified".
- Scope targets must be live when added; there is no `undeprecate` intent.
- CRs do not appear in graph exports (an overlay is planned).
- Effective status and drift depend on the local baseline branch being current. Fetching is the user's job.

---

## 10. Glossary

### 10.1 Discussion

Three options for terms:

1. **Terms as `information` nodes.** Consistent with everything else; linkable via `relates-to`. But a glossary of 200 terms becomes 400 files, every requirement that uses a term would need a `relates-to` edge to be honest about it, and nobody will maintain that. Terms are referenced by *mention*, not by dependency; the graph models dependency.
2. **One glossary document.** One node, terms as headings. Terms are not individually addressable, can't be renamed safely, and the single file becomes a merge-conflict magnet.
3. **First-class entity outside the graph.** Terms are their own thing with their own commands and validation, identified by slug, mentioned in bodies by name.

**[DECISION] Option 3.** A glossary is a first-class, non-graph entity. The value of a glossary in requirements engineering is consistent vocabulary, which is a property of prose, not of the dependency structure. Keeping terms out of the graph keeps the graph honest and keeps the glossary cheap to maintain.

### 10.2 Model

- Directory `glossary/`, one `<slug>.md` + `<slug>.json` per term. Created via `gregraph term add "<Term>" [--alias …]`. Slug = lowercase, non-alphanumerics → `-`, collapsed, trimmed.
- Sidecar:

```json
{ "schema": 1, "term": "Knowledge base", "slug": "knowledge-base",
  "aliases": ["KB"], "created": "…", "created_by": {...},
  "version": 2, "body_hash": "sha256:…", "deprecated": null }
```

- Body: `# Knowledge base` then free Markdown (shipped template `term`: sections *Definition* (required), *Notes*).
- Versioned like documents (hash + bump in the same reconcile pass). No links, no `template` pinning beyond the shipped `term` template (pinned anyway for uniformity).
- Validation: slug uniqueness; alias uniqueness across terms and against term names (`E-TERM-ALIAS-CLASH`); H1 must equal `term`.
- `gregraph term usage <slug>` lists documents whose bodies mention the term or an alias (case-insensitive, word-boundary match). Informational; no edges are created.
- `gregraph term rename <slug> "<New term>"` renames files and updates the sidecar; it does **not** rewrite mentions in bodies (prose is human-owned) but lists them.
- Future (web UI): hover definitions and unknown-term detection; the model supports it.

---

## 11. Conflicting requirements

### 11.1 Recording

A conflict is recorded with a symmetric `conflicts-with` edge. Recording a conflict is a normal, healthy state during analysis; it is better than a hidden contradiction. Therefore:

- `validate` reports `W-CONFLICT-OPEN` for every `conflicts-with` edge whose both endpoints are neither deprecated nor superseded. It is a warning.
- Config `graph.open_conflicts = "warn" | "block"` (default `warn`) lets a team make the hook refuse commits with open conflicts on the baseline branch. When `block`, the hook blocks only if the current branch is the baseline branch (so conflicts can be committed on feature branches while being analysed).
- `status` counts open conflicts.

Because edges have no attributes in v0.1, the *description* of the conflict goes into the body of one or both documents (the shipped `requirement`-kind templates have a *Notes* section) or, preferably, into a CR whose scope contains both.

### 11.2 Resolution patterns

The tool supports four resolution patterns; the CR body records which was applied and why.

1. **Compromise (both superseded by one).** `gregraph supersede A B --title "…"` creates C with `C supersedes A` and `C supersedes B`. Both endpoints of the conflict are now superseded, so `W-CONFLICT-OPEN` disappears automatically. Inbound links to A and B become stale and are re-pointed to C with `link refresh --follow`. Outbound links of both are copied to C (duplicates collapsed) and shown for review.
2. **One wins.** `gregraph deprecate B --reason "Resolved in favour of A, see RE-…"`. B's endpoint is deprecated; the conflict closes. Inbound links to B become stale; the reviewer decides whether they move to A or are removed.
3. **Both amended in place.** Edit A and B so they no longer conflict; then `gregraph unlink A conflicts-with B`. The version bumps on A and B outdate their inbound links, which is the correct signal. The rationale lives in the CR.
4. **Split by scope.** The conflict only exists under a shared condition (e.g. both apply to "all agents"). Create two narrower requirements that each `refines` a common parent and `constrains` different targets; supersede the originals with the respective narrower versions. This is pattern 1 applied twice with different scopes.

The conflict edge is *not* removed automatically in patterns 1 and 2; it remains on the superseded/deprecated documents as history. `unlink` is only needed in pattern 3.

### 11.3 Conflict discovery

v0.1 does not detect conflicts; humans record them. The `constrains` edge type helps make cross-cutting tensions visible: `gregraph show <ID>` lists every requirement constraining a node, which is where conflicts usually hide.

---

## 12. Git integration

### 12.1 Adapter

All Git access shells out to the `git` executable via `subprocess.run` with explicit argument lists, `cwd` = repository root, `LC_ALL=C`, and a 30-second timeout. No Git library dependency. The adapter (`gregraph.core.git.GitAdapter`) exposes:

- `is_repo() -> bool`, `root() -> Path`
- `identity() -> Identity | None` (from `git config user.name/email`)
- `current_branch() -> str | None`
- `branch_exists(name) -> bool`
- `staged_paths() -> list[Path]`, `changed_paths() -> list[Path]` (staged + unstaged), `untracked_paths() -> list[Path]`
- `differs_from_ref(path, ref) -> bool`, `is_tracked(path) -> bool`
- `file_at(ref, path) -> bytes | None` (`git show <ref>:<path>`), `files_at(ref, prefix) -> dict[Path, bytes]` (`git ls-tree -r` plus a single `git cat-file --batch` process; loads the baseline-branch view of all sidecars for CR checks, section 9.6)
- `stage(paths)`
- `tag_annotated(name, message)`, `tags(prefix) -> list[str]`
- `head_sha() -> str | None`

If `git` is not on `PATH` or the root is not a repository, the adapter is replaced by `NullGitAdapter` and the workspace is in **degraded mode**. Every command works in degraded mode; features that need Git print a single line `note: not a git repository — <feature> unavailable` once per invocation.

### 12.2 Identity

`created_by` and decision `by` come from Git identity. If unavailable, they are `null` and the command prints `warning: git user.name/user.email not configured; authorship will be empty`.

### 12.3 Hooks

`gregraph hooks install` writes `.git/hooks/pre-commit` (creating it, or appending a clearly delimited block if a hook exists) that runs `gregraph hook pre-commit`. `hooks uninstall` removes the block. The hook script locates `gregraph` via `python -m gregraph` using the interpreter recorded at install time, falling back to `gregraph` on `PATH`. `hooks status` reports whether the hook is installed and up to date.

### 12.4 Baselines

**[DECISION] A baseline is an annotated Git tag `baseline/<name>`** whose message contains a generated manifest (ID, version, body_hash, status per document, plus the config's ID prefix and the tool version). No file is committed; Git is the store. `gregraph baseline create <name> [-m "…"]` refuses if the working tree has uncommitted changes under managed directories or if `validate` reports errors. `gregraph baseline list` lists tags. Comparing baselines is out of scope for v0.1 (the manifest format is fixed now so that v0.2 can diff them).

### 12.5 Branching strategy

No assumptions beyond the existence of a baseline branch name. Teams may use trunk-based development, feature branches per CR, or release branches. The tool derives everything from "does this file differ from `<baseline_branch>`".

### 12.6 Merge conflicts

No merge driver in v0.1. Guidance printed by `gregraph repair --help`:

- Body conflicts: resolve as prose.
- Sidecar conflicts: resolve the JSON to any syntactically valid state (or leave conflict markers), then run `gregraph repair versions` which recomputes `version` (7.2), `body_hash`, `assets`, and clamps `target_version` values.
- Link conflicts (both sides added links): keep both; `repair versions` de-duplicates.

---

## 13. CLI specification

General:

- `gregraph <command> [subcommand] [args] [options]`. Implemented with `argparse` subparsers.
- Global options: `--repo PATH` (override root discovery), `--no-input` (never prompt; missing required inputs are errors), `--json` (machine-readable output; **every** command and subcommand accepts it — the lifecycle exception is `serve`, which accepts and ignores it, 21.3), `-q/--quiet`, `-v/--verbose`, `--version`.
- Interactivity: when a required argument is missing and stdin is a TTY and `--no-input` is absent, the command prompts. Every prompt has a flag equivalent. Pickers show a filtered numbered list (ID, type, title, status) and accept a number, an exact ID, or a refined filter string; `q` cancels.
- Exit codes: `0` success; `1` validation errors or blocked (hook/check); `2` usage error; `3` no repository found / environment error; `4` operation refused (cycle, rule violation, refusal to overwrite); `5` internal error.
- Config schema (r0.5): every command except `init` requires `config_schema = 2`. A schema-1 config is an environment error (exit 3) whose message names `scripts/migrate_type_ids.py`; the tool does not read, rewrite or partially support schema-1 repositories.
- Output: plain text, one finding per line, prefixed by code (`E-…`, `W-…`) and the affected ID/path. Colours only when stdout is a TTY and `NO_COLOR` is unset. No third-party terminal library.
- **`--json` contract (r0.4, D-AGENT-2).** With `--json` a command writes **exactly one canonical JSON document** (5.4 serialisation) to stdout and terminates; nothing else is written to stdout, and **stderr is empty** for exit codes 0–4 (and for 5 unless the `GREGRAPH_DEBUG=1` debugging escape hatch sends the traceback to stderr). Warnings and degraded-mode notes that human mode writes to stderr travel inside the payload as `notices: [string]`; non-fatal findings as `findings: [Finding]` (14). `--json` takes precedence over `--quiet`: `--json --quiet` still prints the JSON document; `--quiet` suppresses human output only. `--edit` (spawn `$VISUAL`/`$EDITOR`) and `--json` are mutually exclusive — an interactive editor cannot be part of a machine-readable call (usage error, exit 2). `--help`/`-h`/`--version` remain plain text (exit 0); `gregraph` with no command prints help and exits 2, which under `--json` becomes an `E-USAGE` envelope with the help text in `details.usage`.
- **Error envelope (r0.4).** Exit-1 documents are **result-shaped**, not error envelopes (exit 1 means the operation ran and reports findings): `validate --json` is the §14 findings array; `check --json` and `hook pre-commit --json` their check payloads (13.8). Exit 2/3/4/5 produce one **error envelope** on stdout, `{"error": {code, exit_code, message, finding, details}}`, where `code` is `E-USAGE` (exit 2; `details` carries the argparse usage string when available), `E-NO-REPOSITORY` when root discovery fails or `E-ENV` otherwise (exit 3), the refusal's finding code such as `E-CYCLE` or `E-SECTION-UNKNOWN` (exit 4; `finding` is the complete `Finding` including `details`, `details` mirrors `finding.details`), or `E-INTERNAL` (exit 5). Human mode is unchanged (plain text on stderr).

### 13.1 `init`
`gregraph init [PATH] [--prefix RE] [--baseline-branch main] [--templates all|minimal] [--no-git]`
Creates the layout (section 3), copies built-in templates (all by default) into `.gregraph/templates/<name>/v1/`, writes `config.toml` with the default types, `.gitignore`, and `README.md`. If Git is present and PATH is not a repository, runs `git init` unless `--no-git`. Installs hooks unless `--no-git`. Refuses if `.gregraph/` exists.

(r0.4, D-AGENT-9) `init` also writes the agent files of section 3: `AGENTS.md` — existing content preserved, the managed block appended, or replaced in place when a block already exists — and `.agents/skills/gregraph/SKILL.md`, wholly owned and rewritten only when its content differs. Both paths are printed in human mode (`agents files written: AGENTS.md, .agents/skills/gregraph/SKILL.md`) and reported as `agents_files` in the `init --json` payload.

### 13.2 `new`
`gregraph new [TYPE] [--title T] [--template NAME] [--template-version N] [--allow-deprecated] [--tag t]… [--link TYPE:TARGET]… [--cr CR] [--section "<Heading>=<Content>"]… [--section-file "<Heading>=<PATH|->"]… [--body TEXT | --body-file PATH|-] [--strict] [--edit]`
Creates a document: generates ID, renders template, writes both files, creates initial links (each checked), prints the ID and path. `--edit` opens `$VISUAL`/`$EDITOR` on the Markdown file afterwards (never combined with `--json`). `--cr CR` records the new document as introduced by that CR (section 9.5). Prompts for type (picker over types), title, and optional initial links when interactive.

**Template-guided authoring (r0.4, D-AGENT-4).** `--section`/`--section-file` assemble the body from per-section content (both repeatable; `-` reads stdin); `--body`/`--body-file` replace the whole body; `--strict` refuses when a required section is empty or placeholder-only after assembly. Precedence: whole-body > per-section assembly > template skeleton. `<Heading>` is matched against the pinned template's sections — exact, trimmed, case-sensitive, matching `heading` first and then any `renamed_from` alias (5.5). The assembled body lists the level-2 sections in canonical template order with the H1 first; unmentioned sections are emitted with their template placeholder text, so `v1` hashes the real content (7.2 initial grace then keeps the first commit at `version 1`). The tool owns the H1 (5.6): a differing level-1 heading in `--body` input is replaced by `# <title>` (with a notice), a missing one is prepended. Conflicting combinations (`--body` with `--section`, `--body` with `--body-file`, the same heading twice, two stdin consumers) are usage errors (exit 2); nothing is written on refusal. Unknown headings refuse `E-SECTION-UNKNOWN`; a required section without an entry under `--section*` (or empty-or-placeholder under `--strict`) refuses `E-SECTION-REQUIRED-EMPTY` — both self-describing, with the template's full section specification in the finding's `details` (14). Without the content flags, behaviour is unchanged (placeholders allowed at creation).

**Rich `new --json` payload (r0.4, D-AGENT-3).** `new --json` returns one object: `{id, uuid, type, kind, md_path, json_path, template{name, version}, version, body_hash, sections[{heading, required, placeholder, renamed_from}], body (the body exactly as written on disk), sidecar (the parsed on-disk sidecar object), links, findings, notices}` — the file-first workflow: an agent can edit `md_path` directly, guided by `sections`, without reading the template. `body_hash` doubles as the `base_hash` of a subsequent `edit`/`update_body` call (21.5).

### 13.3 `link`
`gregraph link [SOURCE] [TYPE] [TARGET]`
Adds an edge. Interactive flow: pick source (all nodes), pick type (filtered to types whose source-kind rule the source satisfies), pick target (filtered to nodes whose kind satisfies the rule and which are not deprecated/superseded, excluding those that would create a cycle — computed up front). Records `target_version` = target's effective version. Refusals: `E-CYCLE`, `E-EDGE-RULE`, `E-TARGET-SUPERSEDED`, `E-TARGET-DEPRECATED`, `E-EDGE-EXCLUSIVE`. Duplicate → notice, exit 0. `link --help` prints the edge guidelines (6.1).

(r0.4, D-AGENT-5) `link --candidates <SOURCE_ID> [--type EDGE_TYPE] [--json]` answers "what may I link from here" without linking: it runs the interactive picker's filtering (kind rule, target liveness, cycle pre-exclusion) and returns `{source, source_kind, allowed_edge_types, candidates: [{type, target, target_title, target_type, target_kind}]}`, sorted by `(type, target)`; `allowed_edge_types` is `[]` when the source kind permits no edge type. Mutually exclusive with the positional `TARGET` (and with a positional type when no `--type` is given). Unknown edge type is a usage error; unknown source refuses `E-ID-UNKNOWN`.

### 13.4 `unlink`
`gregraph unlink SOURCE TYPE TARGET` — removes the edge; symmetric edges are found on either endpoint.

### 13.5 `link refresh`
`gregraph link refresh [SOURCE TYPE TARGET | --from ID | --to ID | --all] [--follow] [--dry-run]`
Sets `target_version` to the target's effective version for the selected links. `--to ID` selects all inbound links of ID (the common case after editing ID). For stale links (target superseded): with `--follow`, re-point to the successor; interactive otherwise; if the successor chain forks, prompt or fail with `E-SUPERSEDE-FORK` under `--no-input`. For deprecated targets, refresh refuses (`E-TARGET-DEPRECATED`) and suggests `unlink` or re-linking elsewhere.

### 13.6 `set`
`gregraph set ID key=value…`
Allowed keys: `tags` (`tags=a,b` replaces; `tags+=x` adds; `tags-=x` removes), `extra.<name>=value` (`extra.<name>=` removes). Everything else is refused with a pointer to the right command (`title` → edit the H1; `type` → supersede; `status` → `cr set`).

### 13.7 `sync`
`gregraph sync [--bump]` — reconcile all (7.5); normalise; rewrite non-canonical sidecars; rebuild cache. Bumps only in degraded mode or with `--bump`. The report carries the `initialised` bucket of 7.5: uncommitted `v1` documents, CRs and terms populated in place during the initial-grace period. As its last step `sync` refreshes the agent files (r0.4, D-AGENT-9): `AGENTS.md` and `.agents/skills/gregraph/SKILL.md` are rewritten only when their content differs (13.1), so normal workflow heals drift after a tool upgrade or config change; `sync --json` lists what it wrote under `agents_files_changed`.

### 13.8 `check`
`gregraph check` — hook simulation over all working-tree changes; exit 1 if the hook would block.

### 13.9 `validate`
`gregraph validate [--strict] [--only-errors]` — full validation (section 14). `--strict` treats warnings as errors for the exit code. Intended for CI.

### 13.10 `list`
`gregraph list [--type T]… [--kind K]… [--status S]… [--tag t]… [--roots] [--orphans] [--outdated] [--stale] [--deprecated-templates] [--sort id|title|created|version] [--body]`
Tabular output: ID, type, status, version, title. `--json` emits the sidecars plus derived fields. (r0.4, D-AGENT-8) `--body` adds each item's full Markdown body to the `--json` payload (additive `body` key); in human mode the table is unchanged and `--body` is ignored.

### 13.11 `show`
`gregraph show ID… [--body] [--depth N]` — sidecar fields, derived status, outbound and inbound edges with freshness, 1 level upstream (nodes this document links to via hierarchical edges) and unlimited-depth downstream tree (nodes that link to this one, transitively, over directed edges; depth-limited output with `--depth N`, default unlimited), assets, template info. `--body` also prints the Markdown. If ID refers to a CR, `show` delegates to `cr show`.

(r0.4, D-AGENT-8) `show` accepts **multiple IDs**. One ID keeps today's output byte-for-byte. Multiple IDs: human mode prints the documents sequentially, separated by a blank line and `---`; `--json` emits a **JSON array** of the per-document payloads (a CR ID yields its `cr show` payload as an entry). Duplicate IDs are de-duplicated preserving first-seen order; any unknown ID aborts with `E-ID-UNKNOWN` before any output (all-or-nothing).

### 13.12 `status`
`gregraph status` — WIP header; counts of documents by status; drafts (with path); modified-unbumped documents; outdated/stale/pending-outdated links; open conflicts; documents on deprecated template versions; CRs by effective status, CRs with pending decisions (proposed ≠ effective), CRs with drift; hook installed?; degraded mode? Uncommitted, modified `v1` documents with inbound links are additionally listed under a *pending initial version* note (r0.4, AGENT_READINESS §3.3 — no new status is invented); `--json` carries them under `pending_initial_version` when the list is non-empty.

### 13.13 `graph`
`gregraph graph [--root ID]… [--depth N] [--types t,…] [--edges e,…] [--include-superseded] [--direction TD|LR] [-o FILE]`
Emits a Mermaid `flowchart` (section 15). Default scope: all non-superseded, non-deprecated nodes; all directed edges plus `conflicts-with`.

### 13.14 `supersede`
See 7.6. `gregraph supersede OLD… [--title T] [--type TYPE] [--copy-body/--no-copy-body] [--copy-links/--no-copy-links] [--cr CR] [--section "<Heading>=<Content>"]… [--section-file "<Heading>=<PATH|->"]… [--body TEXT | --body-file PATH|-] [--strict] [--edit]`.
(r0.4, D-AGENT-4) The authoring flags of 13.2 apply to the new document: per-section assembly (unmentioned sections keep their template placeholder text, as on `new`), whole-body replacement (so the created `v1` hashes the real content), and `--strict`. Refusals and flag-combination rules as in 13.2; nothing is written when the creation refuses.

### 13.15 `deprecate` / `undeprecate`
`gregraph deprecate ID --reason "…"`, `gregraph undeprecate ID`.

### 13.16 `migrate`
See 7.7.

### 13.17 `template`
- `gregraph template list` — names, versions, deprecated flags, document counts per version.
- `gregraph template add BUILTIN` — copy a built-in template into the repository as `v1` (or next version if the name exists).
- `gregraph template bump NAME [--breaking]` — copy latest version to next version.
- `gregraph template show NAME [--version N]` — print descriptor and skeleton. (r0.4, D-AGENT-5) `template show --json` includes the resolved `sections` (`{heading, required, placeholder, renamed_from}`, in descriptor order) and the repository-relative `path` of the version's `template.md`, alongside the existing descriptor fields.

### 13.18 `cr`
All `cr` commands refuse with `E-CR-DISABLED` when `cr.enabled = false`. Interactive pickers: a CR picker over all CRs; a target picker over live documents not already in scope.

- `gregraph cr new [--title T] [--scope TARGET[:INTENT]]… [--external-ref R] [--section "<Heading>=<Content>"]… [--section-file "<Heading>=<PATH|->"]… [--strict] [--edit]` creates a CR in status `open` from the `cr.template` template. (r0.4, D-AGENT-4) The authoring flags of 13.2 apply (no whole-body pair; per-section assembly only, unmentioned sections keep their placeholders).
- `gregraph cr scope add CR TARGET [--intent modify|supersede|deprecate]` and `gregraph cr scope remove CR TARGET` (section 9.4).
- `gregraph cr set CR key=value…`. Keys: `status` (transitions in 9.3), `branch`, `external_ref`, `tags` (same syntax as `set`), `extra.<name>`.
- `gregraph cr reaffirm CR` (9.3).
- `gregraph cr reanalyze CR [TARGET…]` (9.4).
- `gregraph cr list [--status S]… [--effective] [--pending] [--drift]`. `--status` filters on proposed status, or on effective status with `--effective`. `--pending` lists CRs whose proposed and effective status differ; `--drift` lists CRs with drift.
- `gregraph cr show CR` (9.8).

### 13.19 `repair`
- `gregraph repair versions` — see 7.2/12.6.
- `gregraph repair regenerate-id PATH` — see 4.4.
- `gregraph repair cache` — delete and rebuild the cache.
- (r0.4, D-AGENT-9) `gregraph repair agents` — rewrite the agent files of section 3 idempotently: the `AGENTS.md` managed block is replaced in place (existing content otherwise untouched) and `SKILL.md` is rewritten only when its content differs. Refuses nothing except a missing repository (exit 3). `--json` payload: `{agents_files, changed, findings, notices}`.

### 13.20 `term`
`term add "Term" [--alias A]… [--section "<Heading>=<Content>"]… [--section-file "<Heading>=<PATH|->"]… [--strict] [--edit]`, `term list`, `term show SLUG`, `term usage SLUG`, `term rename SLUG "New term"`, `term deprecate SLUG --reason "…"`. (r0.4, D-AGENT-4) `term add` supports the per-section authoring flags of 13.2 (no whole-body pair) and `--strict`.

### 13.21 `baseline`
`baseline create NAME [-m MSG]`, `baseline list`.

### 13.22 `hooks`
`hooks install`, `hooks uninstall`, `hooks status`; `hook pre-commit` is the internal entry point invoked by the Git hook (hidden from `--help`).

### 13.23 `edit`
`gregraph edit ID [--section "<Heading>=<Content>"]… [--section-file "<Heading>=<PATH|->"]… [--body TEXT | --body-file PATH|-] [--strict]`
Without content flags: opens the Markdown in `$VISUAL`/`$EDITOR`. Convenience only (and, per the general contract, never combined with `--json`).

(r0.4, D-AGENT-4) With content flags the edit is performed by the tool instead of an editor: `--body`/`--body-file` replace the whole body through the `update_body` path (21.5, `base_hash` computed from the on-disk body immediately before writing — `E-BODY-STALE` on mismatch); `--section`/`--section-file` assemble per-section content through `update_sections`, preserving unmentioned sections verbatim (extra level-2 sections not in the template stay at the end, 5.2/D12); `--strict` refuses when a required section is empty or placeholder-only after assembly. `edit` has no `--title` flag: on `--body`/`--body-file` a level-1 `# Heading` in the supplied text is the title authority — the sidecar `title` is synchronised to it (`update_body` step 5 of 21.5; AGENT_READINESS §3.4 rule 8) — while supplied text without a level-1 heading gets the existing document title prepended as `# <title>` (the tool owns the H1, 13.2). On `--section`/`--section-file` the required-section check runs on the assembled body: unmentioned required sections that are already filled on disk are preserved verbatim (AGENT-016), and only required sections that are empty or placeholder-only after assembly trigger `E-SECTION-REQUIRED-EMPTY`. Heading matching, precedence, stdin rules and refusals as in 13.2; nothing is written on refusal. `edit --json` without any content flag is a usage error (exit 2) — an interactive editor cannot be part of a machine-readable call.

### 13.24 `schema`
`gregraph schema [--type TYPE] [--json]` (r0.4, D-AGENT-5; amended r0.5) — the repository rulebook in one call, so agents never read `config.toml` or template files: the payload's `schema` (the config schema, currently `2`), config policies (`id_prefix`, `baseline_branch`, `versioning`, `graph`, `assets`, `cr`), the configured `types` (kind, `abbreviation`, folder, template, informational id prefix, template description), `cr_abbreviation` (`CHG`), the five kinds, the nine edge rules (direction, hierarchical, acyclic, source/target kind sets, `same_kind_only`, mutual exclusions, and the 6.1 guidance as each rule's description), the active `templates` (latest non-deprecated version, all version numbers, `sections` with `required`/`placeholder`/`renamed_from`), and the `cr_lifecycle` (statuses, transitions, scope intents). `--type TYPE` filters `types` to that type and `templates` to those its entries reference (plus the CR template when CRs are enabled); the global sections (`kinds`, `edge_rules`, `cr_lifecycle`, policies) stay. Unknown `--type` refuses `E-TYPE-UNKNOWN`. Human mode prints aligned tables mirroring the payload.

### 13.25 `context`
`gregraph context <ID…> [--depth N] [--direction both|upstream|downstream] [--include-terms|--no-include-terms] [--json]` (r0.4, D-AGENT-8) — one call packing the reading context for the requested documents and CRs (mixed allowed; an unknown ID refuses `E-ID-UNKNOWN` naming the offender; `--depth` defaults to 1, `N ≥ 0`):

- `targets`: the full `show`/`cr show` payloads, each with `body` and parsed `sections`;
- `neighbors`: BFS over graph edges (outbound, inbound, symmetric resolved to the other endpoint) starting at all targets, up to `--depth N`, filtered by `--direction`; each entry carries the connecting edge (`via`), its direction, the BFS depth, and the 7.4 freshness state of that edge. Superseded/deprecated neighbours are included (they matter for reading context); orphans and unrelated documents are not;
- `terms`: every glossary term (or alias) appearing in any target or neighbour body (10.2 word-boundary matching), each once with its full body. Terms are included by default; `--no-include-terms` omits the scan;
- `findings`: the freshness states of all edges among bundle documents with a non-fresh state, plus the `validate` findings whose subject is one of the bundle IDs, de-duplicated.

Human mode prints one combined, LLM-friendly Markdown document: each target as `# <ID> — <title>` with status and body plus its edges, neighbours at their depth, then a `## Glossary` section with the term bodies; `---` separators; no colour codes.

---

## 14. Validation catalogue

Severity **E** = error (exit 1; blocks hook), **W** = warning.

| Code | Sev | Rule |
|---|---|---|
| `E-SIDECAR-MISSING` | E | `.md` without `.json` in a managed directory. |
| `E-BODY-MISSING` | E | `.json` without `.md`. |
| `E-SIDECAR-INVALID` | E | JSON unparsable or fails schema. |
| `E-ID-FILENAME` | E | `id` ≠ filename stem. |
| `E-ID-DERIVATION` | E | `id` not derivable from `uuid` with the configured prefix and the abbreviation of the document's type (`CHG` for a CR). |
| `E-ID-LEGACY` | E | (r0.5) A document or change-request sidecar/filename still uses a two-segment ID. Old IDs are invalid; run `scripts/migrate_type_ids.py` before upgrading. Stale references elsewhere surface as the normal link/mention/scope errors. |
| `E-ID-DUPLICATE` | E | Two documents with the same `id`. |
| `E-UUID-DUPLICATE` | E | Two documents with the same `uuid`. |
| `E-TYPE-UNKNOWN` | E | `type` not in config. |
| `E-TYPE-KIND-CHANGED` | E | Type's kind changed while documents exist. |
| `E-TYPE-ABBREVIATION-CHANGED` | E | (r0.5) Type's abbreviation changed while documents of that type exist. |
| `E-TITLE-MISSING` | E | No H1 as first non-blank line. |
| `E-FRONTMATTER-FORBIDDEN` | E | Body starts with `---`. |
| `E-TEMPLATE-UNKNOWN` | E | Pinned template name/version not in repository. |
| `E-TEMPLATE-MUTATED` | E | A pinned template version's sections changed since last seen. |
| `E-SECTION-REQUIRED-MISSING` | E | Required section heading absent. |
| `E-SECTION-REQUIRED-EMPTY` | E | Required section empty or placeholder only. (r0.4) Also raised at *authoring* time — with `--section*` when a required section has no provided entry, or with `--strict` when any required section is empty-or-placeholder after assembly (13.2, 13.23); that refusal carries `details.template_sections` and `missing_required`. |
| `W-SECTION-UNKNOWN` | W | Level-2 heading not in template. |
| `W-SECTION-ORDER` | W | Template sections present but out of template order. |
| `E-LINK-TARGET-MISSING` | E | Edge target does not exist. |
| `E-LINK-TYPE-UNKNOWN` | E | Edge type not in the fixed set. |
| `E-EDGE-RULE` | E | Kind rule violated. |
| `E-EDGE-EXCLUSIVE` | E | Mutually exclusive edge pair. |
| `E-CYCLE` | E | Directed cycle. |
| `E-LINK-VERSION-AHEAD` | E | (r0.4) `target_version` exceeds the target's **effective** version (7.4) — a real merge mishap; a link matching an unbumped target is `W-LINK-PENDING`, not this error. |
| `W-LINK-OUTDATED` | W | `target_version < target.version`. |
| `W-LINK-STALE` | W | Target superseded or deprecated. |
| `W-LINK-PENDING` | W | (r0.4) Target has unbumped modifications (Git mode) and `target_version ==` the target's effective version; fix `gregraph sync --bump`. Suppressed while the target is in the initial-grace state (7.2). |
| `W-ORPHAN` | W | Node with no edges (6.3). |
| `W-MENTION-UNLINKED` | W | Document body contains an **explicit** mention (5.2) of a document ID with no edge either way (CR IDs exempt). Bare ID-shaped tokens are not mentions. |
| `E-MENTION-UNKNOWN` | E | Body contains an **explicit** mention (5.2) of an ID that is neither a document nor a CR. |
| `E-ASSET-MISSING` | E | Referenced asset absent. |
| `E-ASSET-FOREIGN` | E | Reference to another document's asset folder. |
| `W-ASSET-ORPHAN` | W | File in `assets/<ID>/` not referenced. |
| `W-ASSET-LARGE` | W | Asset over configured size. |
| `E-ASSET-OWNERLESS` | E | `assets/<X>/` where `X` is not a document ID. |
| `W-TEMPLATE-DEPRECATED` | W | Document pinned to a deprecated template version. |
| `W-CONFLICT-OPEN` | W | `conflicts-with` between two live nodes. |
| `E-TARGET-SUPERSEDED` / `E-TARGET-DEPRECATED` | E | Refusal codes at link time (also reported by validate if found in files). |
| `E-SECTION-UNKNOWN` | E | (r0.4, refusal only) A `--section`/`--section-file` heading matches no section of the pinned template (13.2, 13.14, 13.18, 13.20, 13.23); never emitted by `validate`. Self-describing: `details` carries `template` (name, version), the full `template_sections` specification and the `given_heading`. |
| `E-CR-DISABLED` | E | CR command or `--cr` flag used while `cr.enabled = false` (refusal). |
| `E-CR-STATUS` | E | `status` differs from the last decision, or the decision sequence contains an invalid transition. |
| `E-CR-SCOPE-TARGET` | E | Scope entry names a non-existent ID, a non-document, or a duplicate; at add time also a non-live target or one missing from the baseline branch (refusal). |
| `E-CR-CLOSED` | E | `--cr` used with a CR whose proposed status is `rejected` or `implemented` (refusal). |
| `E-CR-ORIGIN-MISSING` | E | `origin_cr` names a non-existent CR. |
| `E-CR-ORIGIN-MISMATCH` | E | `origin_cr` and the CR's `introduces` disagree. |
| `W-CR-MODIFIED-AFTER-DECISION` | W | See 9.3. |
| `W-CR-DECIDER-UNKNOWN` | W | See 9.3. |
| `W-CR-BASE-DRIFT` | W | See 9.6. |
| `W-CR-IMPLEMENTED-UNCHANGED` | W | See 9.6. |
| `W-CR-MENTION-UNSCOPED` | W | (r0.4) An **explicit** mention (5.2) in a CR body of a document ID in neither `scope` nor `introduces` (9.7). |
| `E-TERM-SLUG` | E | Glossary slug/filename mismatch or H1 ≠ term. |
| `E-TERM-ALIAS-CLASH` | E | Alias collides. |
| `W-LINE-ENDINGS` | W | CRLF found (sync fixes). |
| `W-SIDECAR-NONCANONICAL` | W | Serialisation differs from canonical (sync fixes). |
| `W-NO-GIT-IDENTITY` | W | Git identity unset. |
| `W-PREFIX-MISMATCH` | W | Document prefix ≠ configured prefix. |

`validate --json` emits `[{code, severity, id|path, message, fix?, details?}]` where `fix` is a suggested command when one exists. (r0.4) Every `Finding` carries an optional machine-readable `details` object — serialised whenever present, omitted when absent, in `validate --json`, every success payload and every error envelope alike (13 general). The §14 rows above name the `details` contents where one exists (e.g. `template_sections` for authoring refusals, a cycle path for `E-CYCLE`).

---

## 15. Mermaid export

- Output: a fenced ` ```mermaid ` block containing `flowchart TD` (or `LR`).
- Node id in Mermaid: the document ID with `-` removed (Mermaid dislikes hyphens in some contexts): `RESTORY7F3K2Q`. Label: `RE-STORY-7F3K2Q<br/>Title truncated to 40 chars`, with Mermaid-escaping of quotes.
- Node shape by kind: goal `([…])` stadium; requirement `[…]` rectangle; design `[[…]]` subroutine; verification `{{…}}` hexagon; information `>…]` flag.
- Edge style by type: `refines` solid arrow `-->`; `derives-from` dotted `-.->`; `depends-on` thick `==>`; `satisfies`, `verifies`, `constrains` solid with label `-- verifies -->`; `supersedes` dotted with label; `conflicts-with` and `relates-to` undirected `---` with label (conflicts drawn in red via `linkStyle`).
- Deprecated/superseded nodes (when included) get a `classDef` with dashed border.
- `--root ID --depth N` limits to the downstream subgraph of the given roots (nodes that reach the root via directed edges), depth-limited.
- Mermaid has practical limits around a few hundred nodes; the command warns above 300 nodes and suggests `--root`/`--types`.

---

## 16. Architecture and code layout

### 16.1 Package layout

The repository holds two distributions (§16.4) under `packages/`. Both install into the shared import package `gregraph`.

```
pyproject.toml                     # tooling only (no [project]): dev dependency group, ruff/mypy/pytest config
scripts/
└── migrate_type_ids.py            # standalone schema-1 → schema-2 ID migration (does not import gregraph)
packages/
├── core/                          # distribution gregraph-core (pyproject.toml, hatchling)
│   └── src/gregraph/
│       ├── __init__.py            # __version__; pkgutil.extend_path (shared namespace, §16.4)
│       ├── core/
│       │   ├── __init__.py
│       │   ├── workspace.py       # Workspace: root discovery, config, index, git adapter, entry point for all operations
│       │   ├── config.py          # config.toml model (pydantic), defaults, type definitions
│       │   ├── ids.py             # UUID → typed ID, prefix/abbreviation rules, parsing
│       │   ├── models.py          # pydantic models: Document, Link, ChangeRequest, ScopeEntry, Decision, Term, TemplateDescriptor, Identity, Finding
│       │   ├── storage.py         # file I/O: paths, canonical JSON, reading/writing documents, terms, cache
│       │   ├── markdown.py        # body normalisation, H1 extraction, section parsing, mention detection, asset refs (markdown-it-py)
│       │   ├── hashing.py         # body/asset hashing
│       │   ├── templates.py       # template loading, rendering (jinja2), version resolution, migration planning
│       │   ├── graph.py           # in-memory graph: nodes, edges, inbound index, cycle check, reachability, kind rules
│       │   ├── rules.py           # edge-type table and kind rules (data, not logic)
│       │   ├── status.py          # derived status, WIP
│       │   ├── versioning.py      # reconcile(), freshness computation, effective versions
│       │   ├── changes.py         # change requests: scope, base versions, drift, origin, effective status
│       │   ├── validation.py      # findings catalogue and checks
│       │   ├── operations.py      # use-cases: create_document, link, unlink, refresh, supersede, deprecate, migrate, cr_*, term_*, baseline
│       │   ├── git.py             # GitAdapter / NullGitAdapter
│       │   ├── mermaid.py         # export
│       │   ├── hooks.py           # hook script generation, install/uninstall
│       │   └── agents.py          # AGENTS.md managed block + SKILL.md text, idempotent write/refresh (13.1, 13.19)
│       └── builtin_templates/     # shipped templates, copied by init (package data)
│           └── <name>/v1/template.md, template.json
└── cli/                           # distribution gregraph-cli (pyproject.toml, hatchling)
    └── src/gregraph/              # no __init__.py here: gregraph is shared with gregraph-core
        ├── __main__.py            # python -m gregraph → cli.main
        └── cli/
            ├── __init__.py
            ├── main.py            # argparse tree, exit-code mapping
            ├── commands/          # one module per top-level command; thin: parse → call core → format
            │                      #   includes schema.py (13.24), context.py (13.25), and sections.py —
            │                      #   the shared --section/--section-file/--body/--strict parser (13.2)
            ├── prompts.py         # TTY prompts, pickers (stdlib only)
            └── output.py          # text/JSON formatters, colour handling
```

Tests live in the root `tests/` tree, mirroring `packages/core/src/gregraph/core/` (`tests/core/`) and `packages/cli/src/gregraph/cli/` (`tests/cli/`).

The two wheels install no overlapping files: `gregraph/__init__.py` is provided only by `gregraph-core`, and `gregraph-cli` contributes `gregraph/__main__.py` and `gregraph/cli/` only.

### 16.2 Boundaries and rules

- `core` never imports from `cli`. `core` never prints; it returns results and `Finding` objects. `cli` never touches files directly.
- `operations.py` is the API surface for the future web UI. Every CLI command corresponds to one function in `operations.py` taking plain arguments and returning a result dataclass; interactive selection happens in `cli` *before* calling the operation.
- `Workspace` is constructed once per process; it lazily loads the index (all sidecars) and the cache. All operations take a `Workspace`.
- No global mutable state. No singletons.
- `rules.py` holds the edge/kind table as data so that a later plugin system can extend it without touching logic.
- Findings are data (`code, severity, subject, message, fix`), never exceptions. Exceptions are reserved for refusals (`OperationRefused` with a finding) and internal errors.
- All paths are `pathlib.Path`, repository-relative in models, absolute only inside `storage.py`.
- Typed throughout; `mypy --strict` must pass.

### 16.3 Dependencies

Runtime: `pydantic>=2`, `jinja2>=3`, `markdown-it-py>=3` (with `mdit-py-plugins` for GFM tables/tasklists). `tomllib` from the standard library (Python 3.11+); config writing uses a minimal internal TOML emitter for the known schema (no `tomli-w` dependency) — or `tomli-w` if the emitter proves fiddly; the agent may choose and must document it in `AGENTS.md`.

Deliberately not used: Rich/Typer/Click (argparse suffices and keeps the dependency footprint small), GitPython/pygit2 (shell-out), networkx (the graph operations needed — DFS reachability, Kahn's algorithm, inbound index — are ~100 lines and avoid a large dependency).

Development: `pytest`, `pytest-cov`, `hypothesis`, `ruff`, `mypy`, `pre-commit`, `hatchling` (for the tool's own repo; the root `dev` dependency group, §16.4). Packaging does not change the runtime footprint: `gregraph-cli` adds only `gregraph-core`.

### 16.4 Packaging

The product ships as two distributions built from `packages/` and released in lockstep (same version number at every release; currently `0.2.0`). The original single-distribution packaging (`gregraph` with one `pyproject.toml` at the root) is superseded; the reason is recorded in `docs/decisions.md` (D-PACKAGE-SPLIT).

| Distribution | Source | Provides | Runtime dependencies |
|---|---|---|---|
| `gregraph-core` | `packages/core` | `gregraph.core`, `gregraph.__version__`, `builtin_templates/**` (package data) | `pydantic>=2`, `jinja2>=3`, `markdown-it-py>=3`, `mdit-py-plugins` |
| `gregraph-cli` | `packages/cli` | `gregraph.cli`, `python -m gregraph`, console script `gregraph = "gregraph.cli.main:main"` | `gregraph-core==<same version>` |

- Both distributions use `[build-system] requires = ["hatchling"]` and a `src/` layout. `requires-python = ">=3.12"`.
- Shared namespace: `packages/core/src/gregraph/__init__.py` defines `__version__` and calls `pkgutil.extend_path(__path__, __name__)`, so `gregraph.cli` from `gregraph-cli` is found beside `gregraph.core`. The `gregraph` package thus stays importable as `from gregraph import __version__` in both installs. `packages/cli/src/gregraph/` has no `__init__.py`.
- Lockstep: `gregraph-cli` pins `gregraph-core==X.Y.Z` to the same release. Version bumps change both `pyproject.toml` files together, and `__version__` in `gregraph-core` matches.
- Installation:
  - Published (intended usage; not yet on an index): `pip install gregraph-cli` or `pipx install gregraph-cli`, providing the `gregraph` command and `python -m gregraph`. `pip install gregraph-core` gives the library only (`gregraph.core`, `gregraph.__version__`) with no CLI.
  - Local regular install from a checkout, for either path: `python -m pip install ./packages/core ./packages/cli`.
  - Developer install (pip 25.1 or later is needed for `--group`): `python -m pip install --upgrade pip`, then `python -m pip install --group dev -e packages/core -e packages/cli`.
- Build both wheels from the developer environment (it provides hatchling): `python -m pip wheel --no-build-isolation --no-deps ./packages/core ./packages/cli -w dist`.
- The root `pyproject.toml` is tooling-only. It has no `[project]` table, so there is no root distribution and no root installation (`pip install .` at the root is unsupported). It carries the `dev` dependency group (`pytest`, `pytest-cov`, `hypothesis`, `ruff`, `mypy`, `pre-commit`, `hatchling`), the ruff, mypy and pytest configuration, and `mypy_path` covering both source roots, so the quality gate runs as `mypy --strict -p gregraph`.
- Quality gate (before every commit): `ruff check . && ruff format --check . && mypy --strict -p gregraph && pytest`.
- Package data: `packages/core` must include `builtin_templates/**`.
- Semantic versioning. `0.1.0` was the first release; `0.2.0` introduces typed identifiers and config schema 2. The migration script under `scripts/` is repository tooling, not a distribution and not installed as a console script.

### 16.5 Cache

`.gregraph/cache/index.json`: `{ "schema": 1, "tool_version": "…", "files": { "<relpath>": { "mtime_ns": …, "size": …, "body_hash": "…" } }, "types_seen": { "<type>": "<kind>" }, "abbreviations_seen": { "<type>": "<abbreviation>" }, "templates_seen": { "<name>/v<N>": "<sections-hash>" } }`. Used to skip re-hashing unchanged Markdown and to detect type-kind/abbreviation and template mutations. Absence or corruption → rebuild silently.

### 16.6 Performance notes

- Loading 5,000 sidecars: read + `json.loads` + pydantic validation; target < 1.5 s on a laptop SSD. Bodies are read only when hashing is needed and the cache misses.
- Cycle check at link time: single DFS, O(V+E).
- `validate`: one pass over the graph; O(V+E) plus body parsing for changed files.

---

## 17. Testing and quality

- `pytest` with fixtures: `tmp_repo` (initialised GREGraph repo in `tmp_path`, with and without `git init`), `identity` (configures Git user), `sample_graph` (a dozen documents across kinds with edges).
- Hook tests actually run `git commit` in the temp repo and assert exit codes and sidecar changes.
- Property-based tests (`hypothesis`) for: ID derivation round-trip and alphabet; body normalisation idempotence; DAG invariant (random edge insertion sequences never produce a cycle when the tool accepts them; the tool rejects exactly the insertions that would); canonical JSON idempotence; link-freshness table invariants (`target_version ≤ target.version` after any sequence of operations).
- Golden tests for templates (rendered skeleton equals fixture) and Mermaid output.
- Every validation code has at least one test that triggers it.
- Coverage target: 90% for `core`, 75% overall.
- `ruff check` and `ruff format --check` clean; `mypy --strict` clean.
- CI: GitHub Actions matrix on Linux/macOS/Windows for Python 3.12 and 3.13 (Windows matters for path handling and CRLF).

---

## 18. Milestones

Each milestone ends with tests green and a tagged commit.

**M1 — Skeleton and models.** Package, `pyproject`, CI, `Workspace`, config model, ids, models, canonical storage, markdown parsing, hashing, built-in templates copied, `init`, `new`, `show`, `list`, `edit`. Acceptance: `gregraph init && gregraph new user-story --title X --no-input` produces a valid pair of files.

**M2 — Graph.** `rules`, `graph`, `link`, `unlink`, cycle rejection, kind rules, pickers, `validate` with the structural and link-integrity subset, `graph` Mermaid export. Acceptance: property tests for DAG pass; Mermaid renders on mermaid.live.

**M3 — Versioning and Git.** `GitAdapter`, `NullGitAdapter`, `status` (derived statuses, WIP), reconcile, `sync`, `check`, hooks install and pre-commit, link freshness, `link refresh`, effective versions, `repair versions`. Acceptance: hook blocks a commit that newly outdates links; refresh + commit succeeds; degraded mode bumps on `sync`.

**M4 — Lifecycle.** `supersede` (incl. multi-target), `deprecate`/`undeprecate`, stale handling, `template list/add/bump`, template deprecation, `migrate` (in-place and superseding), `baseline`. Acceptance: migration scenarios in tests (additive, renamed, breaking).

**M5 — CRs, glossary, assets, polish.** `cr *` with scope, base versions, drift detection, origin tracking, proposed/effective status and modified-after-decision, `term *`, asset validation and versioning, remaining validation codes, `--json` everywhere, docs (`README.md`, `docs/cli.md`, `docs/concepts.md`), release `0.1.0`.

**M6 — Bootstrap.** Use the released tool on the GREGraph requirements repository (section 19). Fix anything that the dogfooding exposes; release `0.1.1`.

---

## 19. Bootstrapping plan

Two repositories:

1. **`gregraph`** — the tool's source. Contains `AGENTS.md` (appendix C), the code, tests, docs, and a copy of this design document at `docs/design.md` for reference.
2. **`gregraph-requirements`** — a GREGraph repository managing the tool's own requirements. Created *after* M5 with `gregraph init --prefix RE`.

Seeding the requirements repository (M6):

1. `gregraph init`.
2. For each item in appendix A, `gregraph new <type> --title "…" --no-input`, paste the EARS text into the *Statement* section, then `gregraph link` according to the *Refines/Constrains* columns. The provisional `BOOT-nnn` identifiers in appendix A are mapping keys only; the agent keeps a `bootstrap-map.md` in the requirements repo mapping `BOOT-nnn → RE-…` until the seeding is complete, then deletes it.
3. Commit through the hook; create `baseline/0.1.0`.
4. From then on, every change to the tool starts with a CR in the requirements repo.

Appendix A is deliberately kept in plain Markdown so that an agent can read it without the tool.

---

## 20. Decision log (revisit before implementation if desired)

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

Known open items for v0.2: web UI (read/edit/commit), history/diff between refs and baselines, merge driver, exports, query language, sentence linting, user-defined edge types, per-type typed `extra` fields, CR overlay in graph export, CR verification state, `undeprecate` scope intent.

---

## 21. Amendment A1 — Optional local web UI (r0.3)

**Status.** Accepted extension, authorised by the project owner on 2026-10-14. It is not a new milestone and carries no milestone tag. It is the authority for the optional `gregraph-webui` distribution and supersedes only the statements listed in 21.10. Its rationale is recorded as D-WEBUI in `docs/decisions.md`. Everything not mentioned here keeps its v0.1 meaning.

### 21.1 Scope

**In scope (optional extension):** a browser UI served by a foreground, loopback-only process (`gregraph serve`) that uses the core API to:

- browse documents and filter them by type, status and text (title or ID);
- create a document from a type and title (same defaults as `new`);
- view a document's fields, status, and edges with freshness;
- view the raw Markdown body and edit it;
- set tags (`set tags` semantics of 13.6);
- add and remove links (`link`/`unlink`), with every rule of section 6 enforced by core;
- show derived status, WIP, and validation findings, with clickable subjects;
- show a clickable graph view of the first 300 nodes, with a truncation notice.

**Out of scope (still deferred):** Git commit, branch or push from the UI; asset upload or any access to arbitrary files; editing change requests, glossary terms, sidecar JSON or configuration; rendering Markdown as HTML; remote or multi-user deployment; authentication beyond the per-application token of 21.4; a daemon or service installation.

### 21.2 Distributions and installation

- A third distribution, `gregraph-webui`, is built from `packages/webui` (hatchling, `src/` layout, `requires-python >=3.12`), version **0.2.0**, released in lockstep with `gregraph-core` and `gregraph-cli`.
- Its runtime dependencies are `gregraph-core==<same version>`, `gregraph-cli==<same version>`, `fastapi` and `uvicorn` (minimum versions pinned in `packages/webui/pyproject.toml`). It is the only distribution that depends on FastAPI or uvicorn.
- `gregraph-core` and `gregraph-cli` keep their runtime dependencies unchanged (16.3, BOOT-201). Without `gregraph-webui`, nothing about them changes.
- It contributes files only under `gregraph/webui/` (the shared `gregraph` namespace of 16.4 applies). The compiled frontend is shipped inside the wheel under `gregraph/webui/static/`. Installing it needs no Node.js.
- Installation:
  - from a checkout: `python -m pip install ./packages/core ./packages/cli ./packages/webui`;
  - published (intended usage, not yet on an index): `pip install gregraph-webui`, which pulls in `gregraph-core` and `gregraph-cli` and therefore also provides the `gregraph` command.
- The integration is discovered through the entry-point group `gregraph.serve`, name `webui`. The CLI reads entry-point *names* with `importlib.metadata` to decide whether `serve` exists. It imports the webui module only after `serve` has been selected, so `--help` and every other command never import FastAPI, uvicorn or any `gregraph.webui` module.

### 21.3 The `serve` command

```
gregraph [global options] serve [--host HOST] [--port PORT]
```

- `serve` is a **lifecycle command**. It starts the local integration and performs no repository operation itself. Its HTTP handlers call the functions of `operations.py`, one per user action (21.6).
- `--host` defaults to `127.0.0.1`. The accepted values are exactly `127.0.0.1`, `localhost` and `::1`. Any other value is a usage error (exit 2) and no socket is opened. There is no option to bind to all interfaces.
- `--port` defaults to `8765` and must be an integer from 1 to 65535; otherwise a usage error (exit 2). Both options are validated by the argument parser, before the web UI is loaded.
- Repository discovery follows the global rules (`--repo`, upward search). No repository → exit 3.
- A bind failure, for example a port already in use, is an environment error (exit 3). The CLI probes the address before starting the server.
- On start, `serve` prints the banner `GREGraph UI: http://127.0.0.1:8765/` (IPv6 as `http://[::1]:8765/`) followed by `Press Ctrl-C to stop.`. The URL carries no token. `serve` does **not** open a browser; the user opens the URL manually. `serve` does not generate, print or import any token; the application owns its token (21.4).
- The process runs in the foreground until interrupted. Ctrl-C shuts down gracefully and exits 0. There is no daemonisation, no watch mode, and no background service.
- When the distribution is absent, `serve` is not a registered command: invoking it is a usage error (exit 2), a hint names `gregraph-webui`, and `--help` does not list it.
- Global options apply as before; `--repo` is the only global option that changes `serve` behaviour. `--json` and `--no-input` are accepted and ignored.

### 21.4 Local-service security model

- **Loopback only.** The server binds to the requested loopback address (21.3), makes no outbound network calls, and is not a remote service.
- **Guards on every HTTP request.** The static page, the static assets and every `/api/` route pass the same three checks before routing. A refusal is HTTP 403 with the code `E-REQUEST-REFUSED`.
  - **Host.** Exactly one `Host` header. Its host part must be exactly `127.0.0.1`, `localhost` (case-insensitive) or `::1` in brackets; other loopback addresses such as `127.0.0.2` are refused. A header without a port means the HTTP default, port 80. When the application is created with a bound port, as `serve` does, the header's effective port (its explicit port, or 80 when there is none) must equal the bound port. A server bound to port 80 therefore accepts the bare `127.0.0.1` and `localhost` that browsers send, and a server bound to any other port, such as the default 8765, accepts only a header that names that port. When the application is created without a port (programmatic use, tests), any valid port from 1 to 65535 is accepted. This is DNS-rebinding protection.
  - **Origin.** If an `Origin` header is present it must be exactly one value, and it must equal `http://` followed by the request's own `Host` header value (the origin of the request itself). Comparison is case-insensitive. Anything else is refused as a cross-origin request.
  - **Fetch-Site.** If `Sec-Fetch-Site` is present it must be exactly one value, either `same-origin` or `none`. An absent header is allowed.
- **Application token (mutations only).** `create_app` (in `packages/webui`) generates a random token (`secrets.token_urlsafe(32)`) per application instance. It is held in memory only and is never persisted, logged, printed or placed in a URL. The `serve` command neither generates nor imports a token. `GET /api/session` needs no token and returns the token as `csrf_token`. A mutating request (`POST`, `PUT`, `PATCH`, `DELETE`) must carry exactly one `X-GREGraph-Token` header whose value matches (constant-time comparison); otherwise it is refused with HTTP 403 and `E-TOKEN-INVALID`. The token check runs after the three guards above.
- **Mutation framing.** A mutating request must have media type `application/json` (else 415, `E-CONTENT-TYPE`), must not carry a `Content-Encoding` header (else 415, `E-CONTENT-ENCODING`), and its body must not exceed 1 MiB (else 413, `E-BODY-TOO-LARGE`).
- **What the token defends against.** The token and the Origin and Fetch-Site guards defend against web pages that a browser loads from other origins, including cross-site request forgery and DNS rebinding. They do **not** defend against local operating-system users or processes that run as the same user, that can connect to loopback, or that can read process memory. Such processes can already read and change the repository directly. The token is therefore a browser-origin guard, not authentication, and it is not a control against other local users or programs.
- **Response headers.** Every response carries a Content-Security-Policy that allows only same-origin scripts and styles, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and `X-Frame-Options: DENY`. `/api/` responses also carry `Cache-Control: no-store`.
- **Output.** Markdown is returned and displayed as text. The server never renders Markdown to HTML.

### 21.5 Body writes: `update_body`

Section 7 gains one rule for editing prose. Content changes made through the UI follow the same versioning as any other edit (7.2): saving does not bump the version; the pre-commit hook or `sync --bump` does.

(r0.4) Since Amendment A2, `update_body` is no longer web-UI-only: CLI `edit` with `--body`/`--body-file` writes through the same operation (13.23), and the `--section` assembly path writes through `update_sections`, which reuses the same write rule (13.2). The base-hash staleness guard, atomic body write and title sync below apply identically to both callers.

Core operation, one function in `operations.py` with keyword arguments and a result dataclass:

`update_body(workspace, *, doc_id, text, base_hash) -> BodyUpdateResult`

1. `base_hash` is the normalised body hash (7.3) of the Markdown file **as it currently is on disk**, as the editor read it. It is not the sidecar's `body_hash`, which lags behind unbumped edits. The web API returns this value in `body_hash` of the document detail, next to `body_text`.
2. **Refusals (nothing is written):**
   - unknown, malformed, change-request and glossary IDs → `E-ID-UNKNOWN`;
   - `E-PATH-UNSAFE` (step 6), checked before anything is read or written;
   - `E-BODY-MISSING` (14, existing code) when the Markdown file does not exist. The file is **not** recreated;
   - `E-BODY-STALE` (21.8) when the normalised hash of the file on disk differs from `base_hash`.
3. **Structural problems are reported, not refused.** If the first non-blank line is not a level-1 heading, the text is saved and the result carries `E-TITLE-MISSING`; if the text starts with `---`, the text is saved and the result carries `E-FRONTMATTER-FORBIDDEN`. These findings are the same as `validate` reports. When the text has no level-1 heading, the sidecar title keeps its previous value.
4. **Text is stored as sent**, except that CRLF and bare CR line endings are converted to LF. Nothing else is altered: hard line breaks, blank lines, trailing whitespace and the presence or absence of a final newline are preserved. The normalisation of 7.3 is used only to compute hashes; it is never written back to the file. The file is read as UTF-8 with any byte-order mark removed, and its line endings are read as LF; the body file is rewritten only when the new LF text differs from that LF text. The sidecar title may change independently (step 5). The result's `changed` flag is true whenever the body file or the sidecar title changed, so an unchanged body with a title that differs from its heading still reports a change.
5. **Title sync.** When the text has a level-1 heading, the sidecar `title` is synchronised to it (5.6). No other sidecar field changes: `version`, `body_hash`, `assets`, `links`, `tags`, `deprecated` and `origin_cr` are untouched. A saved change is therefore visible as "modified, unbumped" in `status` until the hook or `sync --bump` runs. Git workflows are unchanged.
6. **Path safety.** Both the Markdown file and its sidecar are resolved with `managed_path` before any read or write. Each path component below the repository root, including the file and every folder above it, must be a real file or directory: a symbolic link, or on Windows a junction, is refused, and so is a relative path that would leave the repository. The refusal is `E-PATH-UNSAFE` (21.8), with the offending repository-relative path as subject. Nothing is written in that case.
7. **Write order and atomicity.**
   - The **body** is written by the storage helper `write_body_atomic`. It creates a temporary file `<filename>.<32 hex digits>.tmp` in the same directory (for example `RE-STORY-7F3K2Q.md.<hex>.tmp`), opened exclusively, so that no managed scan of `.md` or `.json` files sees it. It writes the LF-only UTF-8 bytes, flushes and syncs them to disk, copies the target's permission bits onto it, and then replaces the Markdown file with `os.replace`. If any step fails, the temporary file is removed and the original file keeps its previous bytes. Access-control lists and extended attributes are **not** preserved; only the mode bits are.
   - The **sidecar title** update, when needed, is a separate canonical rewrite. It is **not** atomic, and it is not atomic with the body write. A crash between the two writes can leave the title out of sync until the next sync or save corrects it (5.6). A crash during the sidecar write itself can leave a truncated sidecar, which `validate` reports as `E-SIDECAR-INVALID` and which must then be repaired by hand.
8. The result carries the new normalised body hash, which the client uses as the `base_hash` of its next save; the `changed` flag; and the findings of step 3. `update_body` does not recompute asset references; reconcile (7.5) does.

**Concurrency.** Operations issued by the web process are serialised by an in-process lock. Writes from outside the process (another terminal running the CLI, a Git operation, an editor) are not locked. The stale check of step 2 and the writes of step 7 are not one atomic compare-and-swap against external processes, and the body and sidecar writes are not atomic with each other. External races therefore remain possible. This is an accepted residual risk, not a resolved one. `base_hash` is a best-effort guard against them, not a guarantee. Local, single-process operation (1.2 principle 4) is the assumption.

### 21.6 Web UI behaviour

The first version offers the following, and nothing else. The interface has three tabs: **Documents**, **Graph** and **Validation**. A header shows the repository name and, when Git is unavailable, a "No Git" badge.

- **Documents tab, status cards.** Above the list: a Git-aware or degraded badge, the count of findings, one count per derived status as core reports it, and three lists of clickable IDs: pending (unbumped changes), outdated links and stale links. Each entry is a backend link label of the form `SOURCE TYPE TARGET`. Clicking a well-formed entry opens its source document. A label that cannot be parsed is shown as plain text and is not clickable.
- **Documents tab, list and filters.** Rows show ID, type, derived status, version and title, and open the document when clicked. Filters are a text search (`q`, case-insensitive, matched against the title or the ID), a type select, and a status select with `draft`, `active`, `superseded` and `deprecated`. There are no kind or tag filters.
- **Create.** A dialog takes a type (the change-request type is not offered), a title and optional tags. The server creates the document the same way `gregraph new` does, with the type's default template, and a new document is an orphan until linked (6.3).
- **Document detail.** Shows the sidecar fields, the derived status, and the tags. Tags are edited as a complete list and replace the stored list (`PATCH …/meta`). Outbound and inbound links are listed with their freshness.
- **Raw Markdown.** The body is shown as plain text in an editor. Saving sends the text and the `base_hash` the editor read. A successful save reports that the change is pending until `gregraph sync` or the pre-commit hook records the new version. Structural findings of step 3 are shown after a save. On `E-BODY-STALE` (HTTP 409) the draft is kept, nothing is overwritten, and the user must reload the document before saving again.
- **Links.** The user picks a link type from the session's link types and a target from a select that lists every other document; the select does not filter by kind, cycles or liveness. Submitting sends the link to core, which validates kind rules, cycles and liveness. Refusals (`E-CYCLE`, `E-EDGE-RULE`, `E-EDGE-EXCLUSIVE`, `E-TARGET-SUPERSEDED`, `E-TARGET-DEPRECATED` and others) are shown with their finding text. Each outbound link has its own remove action.
- **Graph tab.** Draws the nodes and edges returned by the graph endpoint: the **first 300 nodes** in ascending ID order, with the edges between them. When the repository has more nodes, the view shows the notice "Graph truncated: showing N of M nodes (limit 300)". There is no root or type filter for the graph in this version. Clicking a node opens its document.
- **Validation tab.** Shows the error and warning counts and the list of findings with code, severity, message and subject. When there are none, the tab says that the repository is valid.
- Commit, asset, change-request and glossary editing are not part of this extension (21.1).

### 21.7 Build, bundle and CI

- Frontend source: `packages/webui/frontend` (React 19, TypeScript, Tailwind CSS 4, Vite 7, Vitest 4). Its `package-lock.json` is committed. `package.json` requires Node.js 22.12 or later (Node 22 LTS or Node 24 recommended).
- The compiled output is **checked into the repository** at `packages/webui/src/gregraph/webui/static/` (`index.html` and `assets/`). The wheel ships it as package data. A pip install never needs Node.js.
- `npm run build` runs the TypeScript check and then `vite build`, which writes into the checked-in static directory.
- The CI workflow (`.github/workflows/ci.yml`) has a `frontend` job on `ubuntu-latest` with Node 22 and Node 24. On both it runs `npm ci`, `npm run test` and `npm run typecheck`. On Node 22 only, it also runs `npm run build` and the **bundle drift check**: `git diff --exit-code` on the static directory, and a failure if any untracked file appears there. A frontend source change therefore cannot be merged without its rebuilt bundle.
- The Python job installs `packages/webui` in editable mode and runs the whole test suite, including the web tests.

### 21.8 Error codes

| Code | Sev | Rule | Web API status |
|---|---|---|---|
| `E-BODY-STALE` | E | `update_body` refused because the body on disk no longer matches `base_hash`. Refusal only (like `E-CR-DISABLED`). Nothing is written. | 409 |
| `E-PATH-UNSAFE` | E | `update_body` refused because a path component below the repository root is a symbolic link or junction, or a path would leave the repository. Refusal only. Nothing is written. | 400 |
| `E-BODY-MISSING` | E | Existing §14 code, used as a refusal by `update_body` when the Markdown file is missing. The file is not recreated. Nothing is written. | 409 |

`E-BODY-STALE` and `E-PATH-UNSAFE` extend the catalogue of 14. Other refusals raised by core are mapped to 409, except `E-ID-UNKNOWN` (404). Each new code has tests in `tests/core/`: `E-BODY-STALE` for the refusal and an unchanged file; `E-PATH-UNSAFE` for a symlinked body, a symlinked sidecar, a symlinked folder and a path that would leave the root, each leaving every file untouched.

### 21.9 Testing requirements

- Verification gates. Before every commit, the required gate runs: `ruff check . && ruff format --check . && mypy --strict -p gregraph && pytest`. CI also runs the explicit form `mypy --strict -p gregraph -p gregraph.cli -p gregraph.webui`. The explicit form names the optional CLI and web UI packages, which `-p gregraph` alone does not reach through the shared namespace. It needs all three distributions installed. The required gate stays as written.
- Packaging. `python tests/packaging_check.py` (run by the CI packaging job) builds the three wheels and checks them: no shared archive member; each wheel holds only its share of the `gregraph` namespace; the web UI wheel declares the `gregraph.serve` entry point and contains the static bundle, and every asset the page references resolves inside it. In clean virtual environments it checks: core alone imports `gregraph.core` and ships the 14 built-in templates, with no CLI; core and CLI report the release version, and `serve` is absent; all three expose `gregraph serve --help` without importing the web UI package or FastAPI, and an installed server answers `/` and every asset it references; with the web UI wheel installed without its dependencies, `gregraph --help` still runs and `gregraph serve` exits 3 naming `gregraph-webui`.
- Every rule of 21.3–21.5 that can be checked without a browser has a test: argument validation (host and port), no-repository exit, the Host, Origin and Fetch-Site guards on the static page and on the API, token rejection on mutations, `GET /api/session` without a token, mutation framing (media type, encoding, size), `update_body` success, byte-exact storage (hard breaks, blank lines, final newline), structural findings reported on save, `E-BODY-STALE`, `E-BODY-MISSING` without file recreation, `E-PATH-UNSAFE`, the atomic body replacement with mode bits preserved, and `version`/`body_hash` unchanged after a save.
- `--help` must not import any `gregraph.webui` module (a test checks `sys.modules`).
- Frontend unit tests (Vitest) run in `npm run test`; the TypeScript check runs in `npm run typecheck`. The CI job of 21.7 runs both.
- The coverage targets of section 17 apply to the core changes of this amendment. The webui package is held to the same ruff, mypy and pytest gate as the other distributions.

### 21.10 Superseded and amended statements

| Location | Earlier statement | Effect of this amendment |
|---|---|---|
| §1.2 principle 4 | No daemon, no watch mode, no locking | `serve` is an optional foreground loopback process. No daemon, no watch mode. Locking is in-process serialisation only; external races remain (21.5). |
| §1.4, first bullet | Web UI out of scope, planned for v0.2 | The read/edit subset of 21.1 is in scope as an optional extension. Commit UI, asset upload, CR and glossary editing and Markdown rendering stay out of scope. |
| §7 | Body edits | New body write rule `update_body` (21.5). Sections 7.2–7.5 are unchanged. |
| §13 (general) | Every CLI command corresponds to one `operations.py` function | `serve` is exempt as a lifecycle command (21.3). Every other command keeps the rule. |
| §21.3 (new) | — | The `serve` command; it lives in section 21, not in the §13 command list (r0.4 note: §13.24/§13.25 are `schema`/`context`, added by Amendment A2). |
| §14 | Validation and refusal catalogue | Adds the refusal codes `E-BODY-STALE` and `E-PATH-UNSAFE` (21.8). |
| §16.1 | Two-distribution layout | Adds `packages/webui` and `gregraph/webui/` (21.2). |
| §16.2 | Boundaries and rules | The webui layer calls `operations.py` only; it does not read or write repository files itself (only the static bundle is read, from the package). |
| §16.3 | Dependencies | Core and CLI unchanged. `gregraph-webui` alone adds `fastapi` and `uvicorn` (21.2). |
| §16.4 | Two distributions, released in lockstep | Three distributions; the third is optional and lockstep-versioned (21.2). |
| Appendix A, BOOT-205 | No network service | Read as "no outbound or remote service". The optional loopback listener of 21.3–21.4 is an explicit exception. |
| §20 closing note | Open item "web UI (read/edit/commit)" | The read/edit part is done in the optional extension. Commit workflows and the items of 21.1 remain open (`docs/backlog.md`). |
| Appendix C | Copy of `AGENTS.md` | Historical copy. The repository's `AGENTS.md` is authoritative for layout and dependencies. |

---

## Appendix A — Initial requirements for GREGraph (agent-readable, not in tool format)

Format per item: provisional key; type; kind; statement in EARS form; refines/constrains targets by provisional key. All are to be entered into the requirements repository during M6.

### Goals

| Key | Type | Statement | Refines |
|---|---|---|---|
| BOOT-001 | goal | The tool shall let a requirements engineer manage requirements as a directed acyclic graph of atomic Markdown documents, synchronised only through Git. | — |
| BOOT-002 | goal | The tool shall ensure that humans edit only Markdown prose and configuration, while all structure (files, identifiers, metadata, links, versions) is owned by the tool. | — |
| BOOT-003 | goal | The tool shall make every change to a requirement visible to the owners of dependent requirements. | — |
| BOOT-004 | goal | The tool shall be usable by a team of up to 20 engineers on repositories of several thousand documents without a server. | — |

### Features

| Key | Type | Statement | Refines |
|---|---|---|---|
| BOOT-010 | feature | Repository initialisation with shipped templates. | BOOT-001, BOOT-002 |
| BOOT-011 | feature | Document creation from versioned templates with stable identifiers. | BOOT-002 |
| BOOT-012 | feature | Typed, rule-checked, acyclic linking. | BOOT-001 |
| BOOT-013 | feature | Content versioning and link freshness. | BOOT-003 |
| BOOT-014 | feature | Supersession, deprecation, and template migration. | BOOT-001, BOOT-003 |
| BOOT-015 | feature | Change requests outside the graph with scope, drift detection, origin tracking, and decision tracking. | BOOT-003 |
| BOOT-016 | feature | Glossary outside the graph. | BOOT-002 |
| BOOT-017 | feature | Validation as command, hook, and CI check. | BOOT-002, BOOT-003 |
| BOOT-018 | feature | Status and WIP reporting derived from Git. | BOOT-003 |
| BOOT-019 | feature | Mermaid graph export. | BOOT-001 |
| BOOT-020 | feature | Assets owned and versioned by documents. | BOOT-002 |

### Requirements (selection; the agent expands from sections 4–15)

| Key | Type | Statement | Refines / Constrains |
|---|---|---|---|
| BOOT-100 | functional-requirement | WHEN `gregraph init` is run in a directory without `.gregraph/`, the tool shall create the repository layout, copy all built-in templates as version 1, write the default configuration, and install the pre-commit hook if Git is available. | refines BOOT-010 |
| BOOT-101 | functional-requirement | WHEN a document is created, the tool shall generate a UUIDv4, derive a 6-character Crockford base32 identifier from its first 30 bits, prefix it with the configured prefix, and regenerate on collision with any existing identifier. | refines BOOT-011 |
| BOOT-102 | functional-requirement | The tool shall never reuse an identifier, including identifiers of deprecated or superseded documents. | refines BOOT-011 |
| BOOT-103 | functional-requirement | The tool shall store every document as one Markdown file and one JSON sidecar with the identifier as filename stem. | refines BOOT-011 |
| BOOT-104 | functional-requirement | WHEN a link is requested that would create a directed cycle over the directed edge types, the tool shall refuse the link and print the cycle path. | refines BOOT-012 |
| BOOT-105 | functional-requirement | WHEN a link is requested whose source or target kind violates the edge type's kind rule, the tool shall refuse the link and name the rule. | refines BOOT-012 |
| BOOT-106 | functional-requirement | The tool shall store directed edges on the source document only and compute inbound edges from an index. | refines BOOT-012 |
| BOOT-107 | functional-requirement | WHEN the pre-commit hook runs, the tool shall increment the version of every staged document whose normalised body hash or asset hashes differ from the stored hashes, and stage the rewritten sidecar. | refines BOOT-013 |
| BOOT-108 | functional-requirement | WHEN a commit would newly outdate at least one link and the policy is `block`, the pre-commit hook shall abort the commit and list the exact refresh commands. | refines BOOT-013 |
| BOOT-109 | functional-requirement | WHERE no Git repository is present, `gregraph sync` shall perform the version increments that the hook would perform. | refines BOOT-013 |
| BOOT-110 | functional-requirement | `gregraph check` shall report what the pre-commit hook would report for all working-tree changes without modifying files. | refines BOOT-013, BOOT-017 |
| BOOT-111 | functional-requirement | WHEN a link's target is superseded, `gregraph link refresh --follow` shall re-point the link to the end of the supersession chain, or fail if the chain forks. | refines BOOT-014 |
| BOOT-112 | functional-requirement | WHEN `gregraph supersede` is given multiple targets, the tool shall create one document with one `supersedes` edge per target. | refines BOOT-014 |
| BOOT-113 | functional-requirement | The tool shall validate each document against the template version pinned in its sidecar. | refines BOOT-014, BOOT-017 |
| BOOT-114 | functional-requirement | WHEN a template version is marked deprecated, `gregraph validate` shall warn for every document pinned to it. | refines BOOT-014 |
| BOOT-115 | functional-requirement | WHEN a change request's version exceeds the version recorded by its last non-open decision, `gregraph validate` shall warn that the change request was modified after decision. | refines BOOT-015 |
| BOOT-116 | functional-requirement | WHEN a scope entry is added to a change request, the tool shall record the target's version on the baseline branch (without Git: the working-tree version) as base version and shall change it only through `gregraph cr reanalyze`. | refines BOOT-015 |
| BOOT-117 | functional-requirement | The tool shall manage glossary terms as slug-identified Markdown files outside the graph and report documents that mention a term. | refines BOOT-016 |
| BOOT-118 | functional-requirement | `gregraph validate --strict` shall exit non-zero if any warning or error is found. | refines BOOT-017 |
| BOOT-119 | functional-requirement | `gregraph status` shall report whether the repository is in WIP state and list drafts and unbumped modifications. | refines BOOT-018 |
| BOOT-120 | functional-requirement | The tool shall derive `draft` and `active` status by comparing files with the configured baseline branch and report `unknown` without Git. | refines BOOT-018 |
| BOOT-121 | functional-requirement | `gregraph graph` shall emit a Mermaid flowchart with node shapes by kind and edge styles by type. | refines BOOT-019 |
| BOOT-122 | functional-requirement | The tool shall recompute a document's asset list and hashes on reconcile and treat any asset change as a content change. | refines BOOT-020 |
| BOOT-123 | functional-requirement | WHEN a required argument is missing and stdin is a terminal, the tool shall prompt with a filtered picker; WHERE `--no-input` is given, the tool shall fail instead. | refines BOOT-011, BOOT-012 |
| BOOT-124 | functional-requirement | WHEN a body mentions an identifier that has no edge in either direction, the tool shall warn. | refines BOOT-012 |
| BOOT-125 | functional-requirement | WHILE a change request's effective status is `open` or `accepted`, IF a scope target's version on the baseline branch exceeds its base version, or the target is superseded or deprecated on the baseline branch, THEN `gregraph validate` shall warn of drift. | refines BOOT-015, BOOT-003 |
| BOOT-126 | functional-requirement | WHEN a document is created or superseded with `--cr`, the tool shall record the change request in the new document's `origin_cr` and add the document's ID to the change request's `introduces` list. | refines BOOT-015 |
| BOOT-127 | functional-requirement | The tool shall derive a change request's effective status from its sidecar on the baseline branch and show the working-tree status as proposed when the two differ. | refines BOOT-015, BOOT-018 |
| BOOT-128 | functional-requirement | The pre-commit hook shall not abort a commit because of drift or because documents in a change request's scope changed. | refines BOOT-015 |
| BOOT-200 | non-functional-requirement | The tool shall load a repository of 5,000 documents and complete `gregraph validate` within 5 seconds on a laptop-class machine. | constrains BOOT-004 |
| BOOT-201 | non-functional-requirement | The tool shall run with only `pydantic`, `jinja2`, and `markdown-it-py` as runtime dependencies. | constrains BOOT-001 |
| BOOT-202 | non-functional-requirement | The tool shall produce byte-identical sidecars for identical logical content (canonical serialisation). | constrains BOOT-002 |
| BOOT-203 | non-functional-requirement | The core library shall expose every operation as a function without console I/O so that a web UI can reuse it. | constrains BOOT-001 |
| BOOT-204 | non-functional-requirement | The tool shall run on Linux, macOS, and Windows with Python 3.12 or later. | constrains BOOT-004 |
| BOOT-205 | constraint | The tool shall not communicate with any network service. (Amended by section 21: the optional `gregraph serve` listens on loopback only and makes no outbound connections; see 21.3–21.4.) | constrains BOOT-001 |

### Verification (examples; the agent derives one test-case document per functional requirement)

| Key | Type | Statement | Verifies |
|---|---|---|---|
| BOOT-300 | test-case | Given a repository with A refines B, when linking B depends-on A, then the tool exits 4 and prints the cycle A→B→A. | BOOT-104 |
| BOOT-301 | test-case | Given a document with an inbound link at version 1, when its body is edited and committed, then the commit is aborted and the refresh command is printed; after `gregraph link refresh --to <ID>` the commit succeeds and the link records version 2. | BOOT-107, BOOT-108 |
| BOOT-302 | test-case | Given an accepted CR on branch `cr/a` with scope entry X at base version 2, when another branch changes X and is merged into `main`, then `gregraph validate` on `cr/a` reports `W-CR-BASE-DRIFT` for X; after `gregraph cr reanalyze` it reports `W-CR-MODIFIED-AFTER-DECISION` until `gregraph cr reaffirm` is run. | BOOT-125, BOOT-115, BOOT-116 |
| BOOT-303 | test-case | Given an accepted CR whose scope contains X, when X is edited and committed on the CR's branch, then the hook output contains no finding about the CR and the commit is not aborted because of it. | BOOT-128 |

---

## Appendix B — Default configuration and shipped templates

### B.1 `config.toml` written by `init`

```toml
[gregraph]
config_schema = 2
tool_version = "0.2.0"

[ids]
prefix = "RE"

[git]
baseline_branch = "main"

[versioning]
on_outdated_links = "block"   # block | warn
on_cr_modified = "warn"       # block | warn

[graph]
open_conflicts = "warn"       # warn | block (block applies only on the baseline branch)

[assets]
max_size_kb = 5120

[types.context]
kind = "goal"
abbreviation = "CTX"
template = "context"

[types.goal]
kind = "goal"
abbreviation = "GOAL"
template = "goal"

[types.epic]
kind = "goal"
abbreviation = "EPIC"
template = "epic"

[types.feature]
kind = "requirement"
abbreviation = "FEAT"
template = "feature"

[types.user-story]
kind = "requirement"
abbreviation = "STORY"
template = "user-story"

[types.functional-requirement]
kind = "requirement"
abbreviation = "FUNC"
template = "requirement-ears"

[types.non-functional-requirement]
kind = "requirement"
abbreviation = "NFR"
template = "requirement-ears"

[types.constraint]
kind = "requirement"
abbreviation = "CON"
template = "constraint"

[types.design]
kind = "design"
abbreviation = "DSGN"
template = "design"

[types.decision]
kind = "design"
abbreviation = "DEC"
template = "decision"

[types.test-case]
kind = "verification"
abbreviation = "TEST"
template = "test-case"

[types.stakeholder]
kind = "information"
abbreviation = "STKH"
template = "stakeholder"

[types.assumption]
kind = "information"
abbreviation = "ASM"
template = "assumption"

[cr]
enabled = true
template = "change-request"
deciders = []                 # optional list of e-mail addresses; empty = no check
# CRs always use the fixed, reserved abbreviation CHG; it is not configurable.
```

CRs always live in `<root>/changes/`; the directory is not configurable.

### B.2 Shipped templates (all `v1`)

| Name | Sections (required in bold) |
|---|---|
| `context` | **Context**, **Rationale**, Assumptions, Out of scope |
| `goal` | **Goal**, **Rationale**, Success indicators, Notes |
| `epic` | **Hypothesis** (placeholder: "For <users> who <need>, <epic> will <outcome>. We will know this is true when <indicator>."), **Rationale**, Scope, Notes |
| `feature` | **Description**, **Benefit**, Scope, Notes |
| `user-story` | **Story** ("As a <role>, I want <capability>, so that <benefit>."), **Acceptance criteria** ("Given … When … Then …"), Rationale, Notes |
| `requirement-ears` | **Statement** (placeholder lists the five EARS patterns), **Rationale**, Fit criterion, Notes |
| `constraint` | **Constraint**, **Source**, Rationale, Notes |
| `design` | **Description**, **Decision drivers**, Alternatives considered, Consequences, Notes |
| `decision` | **Context**, **Decision**, **Consequences**, Alternatives considered |
| `test-case` | **Objective**, **Preconditions**, **Steps**, **Expected result**, Notes |
| `stakeholder` | **Role**, **Interests**, Contact, Notes |
| `assumption` | **Assumption**, **Impact if false**, Validation plan, Notes |
| `change-request` | **Motivation**, **Proposed change**, **Impact**, Resolution, Notes (used by `cr new`; not a document type) |
| `term` | **Definition**, Notes |

Each `template.md` begins with `# {{ title }}` followed by the sections as `## Heading` with the placeholder text on the next line (placeholders in *italics*).

### B.3 Sidecar JSON schema (pydantic, summarised)

```python
class Identity(BaseModel):
    name: str
    email: str


class Link(BaseModel):
    type: Literal[
        "refines",
        "derives-from",
        "depends-on",
        "satisfies",
        "verifies",
        "constrains",
        "supersedes",
        "conflicts-with",
        "relates-to",
    ]
    target: str  # typed ID: <PREFIX>-<ABBREVIATION>-<body>
    target_version: int  # >= 1


class AssetRef(BaseModel):
    path: str  # relative to assets/<ID>/
    hash: str  # "sha256:..."


class Deprecation(BaseModel):
    at: datetime
    by: Identity | None
    reason: str


class Decision(BaseModel):
    status: Literal["open", "accepted", "rejected", "implemented"]
    at: datetime
    by: Identity | None
    at_version: int


class ScopeEntry(BaseModel):
    id: str
    intent: Literal["modify", "supersede", "deprecate"]
    base_version: int  # >= 1


class TemplateRef(BaseModel):
    name: str
    version: int


class Document(BaseModel):
    schema_: int = Field(alias="schema")
    uuid: UUID
    id: str
    type: str
    title: str
    created: datetime
    created_by: Identity | None
    template: TemplateRef
    version: int
    body_hash: str
    assets: list[AssetRef]
    links: list[Link]
    deprecated: Deprecation | None
    tags: list[str]
    extra: dict[str, str]
    origin_cr: str | None


class Term(BaseModel):
    schema_: int = Field(alias="schema")
    term: str
    slug: str
    aliases: list[str]
    created: datetime
    created_by: Identity | None
    template: TemplateRef
    version: int
    body_hash: str
    deprecated: Deprecation | None


class ChangeRequest(BaseModel):
    schema_: int = Field(alias="schema")
    uuid: UUID
    id: str
    title: str
    created: datetime
    created_by: Identity | None
    template: TemplateRef
    version: int
    body_hash: str
    scope_hash: str
    scope: list[ScopeEntry]
    introduces: list[str]
    status: Literal["open", "accepted", "rejected", "implemented"]
    decisions: list[Decision]
    branch: str | None
    external_ref: str | None
    tags: list[str]
    extra: dict[str, str]
```

---

## Appendix C — `AGENTS.md` for the `gregraph` repository

```markdown
# AGENTS.md — GREGraph

## What this is
GREGraph is a local, Git-aware requirements management CLI. The full specification is
`docs/design.md`. Read it before writing code. When the spec and this file disagree,
the spec wins; open an issue noting the discrepancy.

## Ground rules
- Python >= 3.12. Runtime deps: pydantic, jinja2, markdown-it-py (+ mdit-py-plugins). Nothing else
  without a note in docs/decisions.md explaining why.
- `core` never prints and never imports `cli`. `cli` never touches the filesystem directly.
- Every CLI command maps to one function in `packages/core/src/gregraph/core/operations.py`.
- Findings are data (`Finding`), not exceptions. Refusals raise `OperationRefused(finding)`.
- All Git access goes through `packages/core/src/gregraph/core/git.py` via subprocess. No Git libraries.
- Canonical JSON: `indent=2, ensure_ascii=False, sort_keys=True`, trailing newline, links sorted.
- Paths in models are repository-relative `pathlib.Path`; only `storage.py` makes them absolute.

## Workflow
- Test first: write the failing test, then the code. Every validation code in spec §14 has a test.
- Run `ruff check . && ruff format --check . && mypy --strict -p gregraph && pytest` before every commit.
- One commit per coherent change; commit message subject <= 72 chars, body explains why.
  Reference the spec section touched, e.g. "graph: reject cross-type cycles (spec §6.2)".
- Milestones are in spec §18. Finish and tag a milestone before starting the next.
- Do not add features not in the spec. Record ideas in docs/backlog.md instead.
- Windows matters: use `pathlib`, never string paths; normalise line endings on read.

## Layout
See spec §16.1 and §16.4. Two distributions live under `packages/` (`gregraph-core`,
`gregraph-cli`) sharing the `gregraph` import package; the root `pyproject.toml` is
tooling-only. Tests live in `tests/` mirroring `packages/core/src/gregraph/core/` (`tests/core/`)
and `packages/cli/src/gregraph/cli/` (`tests/cli/`); CLI tests invoke
`gregraph.cli.main.main([...])` and use the `tmp_repo` fixture. Dev setup is in README.md.

## Definition of done for v0.1
All milestones M1–M5 tagged, CI green on Linux/macOS/Windows, coverage >= 90% for core,
`docs/cli.md` and `docs/concepts.md` written, both distributions installed
(`python -m pip install ./packages/core ./packages/cli`; published `pip`/`pipx install gregraph-cli`) verified,
and the tool has been used to initialise the `gregraph-requirements` repository (M6).
```
