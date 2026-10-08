# GREGraph concepts

What GREGraph models and why. This is the human introduction to the domain
model; the normative specification is `docs/design.md`, and `docs/cli.md`
documents the commands. Spec section numbers in parentheses point at the
details.

## The repository

GREGraph manages requirements in a dedicated Git repository. The root holds
`.gregraph/config.toml`; the working data lives in plain Markdown files with
small JSON sidecars:

```
documents/<type-folder>/<ID>.md + <ID>.json   # one document = one graph node
changes/<ID>.md + <ID>.json                   # change requests (not in the graph)
glossary/<slug>.md + <slug>.json              # glossary terms (not in the graph)
assets/<ID>/…                                 # files owned by document <ID>
.gregraph/templates/<name>/<vN>/              # repository-local templates
```

Everything the tool stores is text you can read, diff and merge with Git.
The tool adds a cache under `.gregraph/` and a pre-commit hook; it never
hides state outside the repository. (§3)

Without Git the tool still works (**degraded mode**): draft/active status is
reported as `unknown`, version bumps move to `gregraph sync`, and features
that need Git say so with a single `note:` line. (§12.1)

## Documents, kinds, and types

A **document** is one Markdown file plus one JSON sidecar — the graph node's
identity (ID, UUID, title, type, template pin, version, hashes, links) and
its body. IDs look like `RE-7F3K2Q`: a configured prefix plus Crockford
base32 derived from the document's UUID, so the ID is stable and unique. (§4)

Every document has a **kind** — one of five fixed categories the edge rules
understand:

| Kind | Answers | Examples |
|---|---|---|
| `goal` | Why | goal, epic, context |
| `requirement` | What | feature, user-story, functional/non-functional requirement, constraint |
| `design` | How | design, decision, ui-design |
| `verification` | Evidence | test-case |
| `information` | Context | stakeholder, assumption, reference |

A **type** is the user-facing label (`user-story`, `feature`, …). Types are
defined in `config.toml`, each declaring exactly one kind and a default
template. Types are cheap to add; kinds are the stable vocabulary the tool
reasons about. A document's type never changes in v0.1 — to "retype", you
supersede with a document of the new type. (§5.3)

Each document body follows a **template**: a versioned Markdown skeleton
(sections with placeholder text) plus a JSON descriptor. Documents pin their
template name and version, so evolving a template never invalidates existing
documents by itself. Extra sections are warnings, not errors. (§5.5)

## The graph

Documents are linked by typed edges, stored on the source document's sidecar.
The edge types are fixed in v0.1 (§6.1):

| Type | Direction | Meaning |
|---|---|---|
| `refines` | hierarchical | The same intent, stated more concretely (user-story → feature → epic). |
| `derives-from` | hierarchical | A new requirement that exists *because of* the target, not as a decomposition. |
| `depends-on` | ordered | Cannot be implemented or is meaningless without the target. |
| `satisfies` | design → goal/requirement | A design element realises the target. |
| `verifies` | verification → requirement/design | A test or inspection provides evidence. |
| `constrains` | requirement → … | A cross-cutting constraint (often an NFR) limiting how the target may be realised. |
| `supersedes` | same kind | The source replaces the target. |
| `conflicts-with` | symmetric | The two cannot both be satisfied as written. |
| `relates-to` | symmetric | Weak association; last resort. |

The rule of thumb `gregraph link --help` prints: ask "if the target were
deleted, would the source still make sense as written?" — *no, more
concretely* → `refines`; *no, different requirement caused by it* →
`derives-from`; *yes, but the target must come first* → `depends-on`. Never
model quality attributes as children; use `constrains`. A design never
refines a requirement; it satisfies it.

All directed edges together form one acyclic graph — cycles across edge
types are refused at link time (`E-CYCLE`) and re-checked by `validate`.
There may be several **roots** (no outbound `refines`/`derives-from`): a
product serves a business goal, a compliance goal, and a quality goal at
once; a synthetic super-root would be noise. A node with no edges at all is
an **orphan** (`W-ORPHAN`) — normal for a fresh document, a hint
afterwards. (§6.2–6.5)

Conflicts are recorded, not hidden: a `conflicts-with` edge makes a tension
visible (`W-CONFLICT-OPEN` while both endpoints are live) until humans
resolve it — compromise (supersede both with one document), one wins
(deprecate), amend both and unlink, or split by scope. (§11)

## Versions and link freshness

Requirements documents are mutable — fixing a typo must not require ceremony.
What reviewers need instead is a way to say *"I confirmed this link against
version 3 of that document"*. GREGraph's versioning model (§7) provides
exactly that:

- Each document has an integer `version`, starting at 1. It increments by 1
  whenever the normalised body or any asset changes (detected by stored
  SHA-256 hashes, so it works with and without Git).
- In Git mode the bump happens in the **pre-commit hook**, for staged files:
  uncommitted edits are visible as "modified, unbumped" but do not change
  any version. In degraded mode `gregraph sync` does the bumping.
- Each link records `target_version` — the version of the target it was
  confirmed against. `gregraph link refresh` sets it (to the target's
  *effective* version, so you can edit the target and refresh inbound links
  in one commit).

Link states (§7.4):

| State | Meaning |
|---|---|
| **fresh** | `target_version` equals the target's current version. |
| **outdated** | The target changed after the link was last confirmed — re-read and refresh, or unlink. |
| **stale** | The target is superseded or deprecated; consider re-pointing to the successor. |
| **pending-outdated** | The target has unbumped modifications; this link *will* become outdated at the next commit (`check`/`status` show it in advance). |

The hook **blocks** a commit that would newly outdate links (configurable:
`versioning.on_outdated_links = "block" | "warn"`). Links that were already
outdated before the commit are reported but never block — one person's edit
must not freeze everyone else's work. Refreshing a link is deliberately a
review act: the tool cannot enforce that anyone re-read the target; the
process does. `git commit --no-verify` remains the documented escape hatch.

**Supersession** is the semantic replacement of a document (§7.6):
`gregraph supersede OLD` creates NEW, adds `NEW supersedes OLD`, copies
outbound links, and leaves inbound links alone — they turn stale and are
listed with the `link refresh --follow` commands that re-point them along
the `supersedes` chain (you choose when a chain forks). A superseded
document keeps its files and history and can no longer be linked to, except
with `supersedes` itself.

**Template migration** (§7.7): additive template changes migrate in place
(`gregraph migrate` inserts the new sections — a content change, so inbound
links correctly become outdated); breaking changes migrate by supersession
(a new document receives the matched sections, unmatched content is kept
under `## Unmapped content (migration)`).

After a merge conflict in a sidecar, resolve the JSON (or leave the conflict
markers) and run `gregraph repair versions`: the version becomes
`max(both sides) + 1`, hashes are recomputed, and link versions are
clamped. (§7.2, §12.6)

## Status

Document status is **derived**, never stored (the single exception: the
`deprecated` flag) (§8):

| Status | Rule |
|---|---|
| `draft` | Untracked, or content differs from the baseline branch. |
| `active` | Tracked, identical to the baseline branch, not superseded or deprecated. |
| `superseded` | Has an inbound `supersedes` edge. |
| `deprecated` | `deprecated != null` (set with a reason; clear with `undeprecate`). |

Precedence: `deprecated` > `superseded` > `draft` > `active`. The
**baseline branch** (`git.baseline_branch`, default `main`) is what
"accepted" means: merging a draft into it makes it active. There is no
separate `approved` state — acceptance is the merge. Without Git (or without
the baseline branch locally) status degrades to `unknown`.

A **baseline** is a named, accepted state of the repository: an annotated
Git tag `baseline/<name>` with a manifest (ID, version, hash, status per
document) in its message — nothing extra is committed. `gregraph baseline
create` refuses to tag an unhealthy tree. (§12.4)

`gregraph status` heads its report with the repository's WIP state —
`WIP: yes (…)` while any document is a draft, has unbumped modifications, or
any managed file is uncommitted. Nothing blocks on WIP in v0.1; it is the
"are we in a clean state?" signal a UI or CI can display. (§8)

## Change requests

A **change request (CR)** describes a proposed change to a set of existing
documents. CRs are deliberately *outside* the graph — a change record is a
process artefact that refers to versions of the product description, not
part of it (§9.1). They live in `changes/`, share the ID space with
documents, and are optional (`cr.enabled = false` turns the whole feature
off).

A CR carries:

- **Scope** — one entry per affected document: an intent (`modify`,
  `supersede`, `deprecate`) and the `base_version` the CR was analysed
  against (the target's version on the baseline branch at the time the entry
  was added). New documents the CR introduces are recorded in `introduces`
  (via `new … --cr` / `supersede … --cr`), and each such document gets
  `origin_cr` pointing back. (§9.4–9.5)
- **A decision history** — every status change (`open` → `accepted` /
  `rejected` → `implemented`, with reopenings) is appended as a decision
  with who, when, and at which CR version. Content changes after a decision
  raise `W-CR-MODIFIED-AFTER-DECISION`; resolve by reopening and deciding
  again, or `cr reaffirm`. (§9.3)
- **Proposed vs. effective status** — what you set on your branch is the
  *proposal*; what the sidecar on the baseline branch says is *effective*.
  The merge is the decision. Teams that need approval control use branch
  protection on their Git host; `cr.deciders` is advisory only. (§9.3)

Two health checks (§9.6):

- **Drift** — a scope target changed on the baseline branch by something
  other than this CR after it was analysed (`W-CR-BASE-DRIFT`). Re-read the
  target, then `cr reanalyze` to re-base the analysis.
- **Implementation check** — when the proposed status is `implemented`,
  each scope entry is checked against the working tree (was it actually
  modified/superseded/deprecated as declared?). Unmet entries warn
  (`W-CR-IMPLEMENTED-UNCHANGED`).

Neither check says the change is *correct* — verification state is out of
scope for v0.1.

Two workflows, neither enforced (§9.9):

1. **Proposal-first** — merge the CR (effective: `open`), decide on a
   decision branch and merge (the merge is the decision), implement on an
   implementation branch and record `implemented`.
2. **Single-PR** — one branch creates the CR, records `accepted`,
   implements, records `implemented`; the merge makes all decisions
   effective at once.

`gregraph cr show` is the review view: decisions, scope with versions and
drift, introduced documents, and the **impact set** (one level upstream and
unlimited downstream around every scope target) as input for the CR body's
*Impact* section. The tool never writes into the body.

## Glossary

Glossary terms are first-class and outside the graph (§10): a term's value
is consistent vocabulary in prose, not dependency structure. Terms live in
`glossary/<slug>.…`, identified by slug, with optional aliases. They are
versioned like documents and referenced by *mention*:
`gregraph term usage` lists the documents whose bodies use a term or alias;
`term rename` moves the files and lists the mentions but never rewrites
prose — bodies are human-owned.

## Where to go next

- `docs/cli.md` — every command and flag.
- `docs/design.md` — the specification (§7 versioning, §8 status, §9 CRs in
  full detail, §14 finding catalogue).
- `docs/decisions.md` — design decision log and implementation decisions.
