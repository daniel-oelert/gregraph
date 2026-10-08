# GREGraph v0.1.0 — Implementation Plan

Derived from `GREGraph-design-r0.2.md` (tool release 0.1.0). The plan splits the work into
**22 subtasks** (S0–S22) grouped in **9 waves**. Subtasks within a wave are parallel-safe
unless marked *(serial)*; waves run in order. Each subtask is a self-contained handoff brief
for one subagent.

## How to use this plan

1. Start a subagent with the subtask's **Handoff brief** (copy verbatim, fill nothing else in).
2. The subagent reads the referenced spec sections in `docs/design.md` (copy of the design
   document, created in S0) and implements exactly what they specify — the spec wins over
   everything else. Deviations/ambiguities go to `docs/backlog.md`, never into silent
   behaviour changes.
3. When the subtask's acceptance tests pass and the quality gate is green, mark it done and
   proceed. Do not start a dependent subtask before its dependencies are green.
4. Apply milestone tags (§18 of the spec) when the milestone's acceptance criterion passes;
   mapping at the end of this plan.

## Global ground rules (every subtask)

- Python ≥ 3.12. Runtime deps only: `pydantic>=2`, `jinja2>=3`, `markdown-it-py>=3` +
  `mdit-py-plugins` (D11, §16.3). Dev deps: pytest, pytest-cov, hypothesis, ruff, mypy.
- Architecture boundaries (§16.2): `core` never imports `cli`, never prints — returns data and
  `Finding` objects; `cli` never touches files; every CLI command maps to one function in
  `gregraph/core/operations.py`; refusals raise `OperationRefused(finding)`; no global state.
- Git access only via `gregraph/core/git.py` subprocess adapter (§12.1).
- Canonical JSON (§5.4): `indent=2, ensure_ascii=False, sort_keys=True`, trailing newline,
  `links` sorted by `(type, target)`, CR `scope` sorted by `id`, `introduces` sorted.
- Paths in models: repository-relative `pathlib.Path`; only `storage.py` makes them absolute.
- Test-first (appendix C): failing test → code. Every validation code in spec §14 gets at
  least one test.
- Quality gate, run before a subtask is considered done:
  `ruff check . && ruff format --check . && mypy --strict gregraph && pytest`
- Coverage targets (§17): ≥ 90 % for `gregraph/core`, ≥ 75 % overall (enforced at S21).

## Dependency overview

```
Wave 0:  S0 scaffold
Wave 1:  S1 ids/models/rules     S2 hashing/markdown     S3 config/storage
Wave 2:  S4 builtin templates    S5 templates engine     S6 workspace/graph
Wave 3:  S7 git/hooks            S8 status
Wave 4:  S9 versioning/reconcile
Wave 5:  S10 validate-structural (serial) → S11 validate-relational
Wave 6:  S12 doc lifecycle ops   S13 change requests     S14 glossary
         S15 migrate/template/baseline/repair            S16 mermaid
         (S12 first; S13–S16 fill operations.py by function partition — see Risks)
Wave 7:  S17 cli framework + init/new/show/list/edit
         (then parallel) S18 cli middle commands          S19 cli lifecycle/cr/term/hooks
Wave 8:  S20 docs                S21 release quality gate
Wave 9:  S22 bootstrap (M6 dogfooding)
```

---

## Wave 0

### S0 — Repository scaffolding and tooling

- **Goal:** A clean, installable package skeleton with all module stubs, design doc in place,
  CI and quality tooling configured, shared test fixtures ready.
- **Spec refs:** §16 (all), appendix C (`AGENTS.md` verbatim), §17 (fixtures, CI matrix).
- **Depends on:** —
- **Deliverables:**
  - `pyproject.toml`: hatchling build; project `gregraph` version `0.1.0`; `requires-python
    ">=3.12"`; runtime deps as above; optional dev extra; package data `builtin_templates/**`;
    `[project.scripts] gregraph = "gregraph.cli.main:main"`.
  - Package skeleton exactly as §16.1 (`gregraph/{__init__,__main__}.py`,
    `cli/{main,prompts,output}.py`, `cli/commands/`, `core/` modules incl. `git.py` stub with
    `GitAdapter`/`NullGitAdapter` signatures from §12.1, `builtin_templates/`).
  - `AGENTS.md` (appendix C verbatim), `docs/design.md` (copy of the design document),
    `docs/decisions.md` and `docs/backlog.md` (empty, with one-line purpose headers).
  - `tests/conftest.py` with `tmp_repo` (initialised gregraph repo in `tmp_path`, parameterised
    with/without `git init`) and `identity` (sets `user.name`/`user.email`) fixtures.
  - `ruff` and `mypy --strict` config, `pytest` config, `.gitignore` (incl. `*.egg-info`,
    `dist/`, `__pycache__/`), `.github/workflows/ci.yml` matrix Linux/macOS/Windows × 3.12/3.13
    running the quality gate.
- **Tests & acceptance:** `pip install -e ".[dev]"` succeeds; `python -m gregraph --version`
  prints `0.1.0` (from `__version__`); `gregraph` console script exists; gate green (zero or
  trivial import tests).
- **Handoff brief:** "Read §16 of docs/design.md (or the design doc in the workspace root
  before S0 lands) and appendix C. Create the gregraph repository scaffold: pyproject.toml
  (hatchling), the complete package skeleton of §16.1 with empty stub modules documenting each
  module's spec sections, AGENTS.md verbatim from appendix C, docs/design.md copy,
  tests/conftest.py with tmp_repo/identity fixtures, lint/type/test/CI configuration. Run the
  quality gate. Do not implement behaviour."

---

## Wave 1 (parallel)

### S1 — Identifiers, models, rules table

- **Goal:** The pure data layer: ID generation/parsing, all pydantic models, the edge/kind
  rule table as data.
- **Spec refs:** §4 (all), §5.4, §5.5 (descriptor), §6.1–6.4, §9.2, §10.2, appendix B.3.
- **Depends on:** S0.
- **Deliverables:**
  - `core/ids.py`: UUIDv4 → ID (first 30 bits, Crockford base32 `0123456789ABCDEFGHJKMNPQRSTVWXYZ`,
    uppercase, 6 chars, prefix per config, pattern `[A-Z][A-Z0-9]{0,7}`); collision retry
    against a caller-supplied existing-ID set, max 100 attempts; case-insensitive parsing and
    normalisation (with/without prefix when unambiguous); `id` ↔ `uuid` derivation check.
  - `core/models.py`: `Identity, Link, AssetRef, Deprecation, Decision, ScopeEntry,
    TemplateRef, Document, Term, ChangeRequest` exactly per appendix B.3 (field `schema`
    aliased), plus `TemplateDescriptor` (§5.5) and `Finding` (`code, severity, subject: id|path,
    message, fix?`, §14 JSON shape).
  - `core/rules.py`: edge-type table as data — for each of the 9 types: direction
    (directed/symmetric), allowed source kinds, allowed target kinds; kind set; mutual-exclusion
    pairs (`refines`/`derives-from` on one ordered pair, §6.4); directed-edge set used for cycle
    detection (§6.2).
- **Tests & acceptance:** hypothesis — ID derivation round-trip over the alphabet, alphabet
  exclusions (no I/L/O/U), parsing normalisation; collision retry works and fails after 100
  attempts; model JSON round-trips; mandatory-field set of §5.4 enforced; rules table complete
  and self-consistent (every edge type present; symmetric types not in the directed set).
- **Handoff brief:** "Implement gregraph/core/{ids,models,rules}.py per spec §4, §5.4, §5.5,
  §6.1–6.4, §9.2, §10.2, appendix B.3. Pure data/logic only — no I/O, no printing. Test-first
  with pytest+hypothesis as specified. Gate green."

### S2 — Hashing and Markdown handling

- **Goal:** Body normalisation, content hashing, H1/section/mention/asset-reference parsing.
- **Spec refs:** §5.2, §5.6, §5.7, §7.3.
- **Depends on:** S0.
- **Deliverables:**
  - `core/hashing.py`: `normalise_body` (UTF-8, CRLF/CR→LF, strip trailing whitespace per
    line, collapse ≥3 consecutive blank lines to 2, exactly one trailing newline, H1 included);
    `body_hash = "sha256:" + hex`; raw-byte SHA-256 for assets; effective-content comparison
    (body hash or sorted `(path, hash)` list differ).
  - `core/markdown.py` (markdown-it-py + GFM plugins): H1 extraction (first non-blank line
    must be `# Title`); front-matter detection (body starts with `---`); level-2 section
    parsing (exact heading text after trim, case-sensitive; *empty* = whitespace/HTML comments
    only or equal to placeholder); `renamed_from` matching helper; mention detection (bare IDs
    matching the ID pattern and Markdown links to IDs); image/asset reference extraction with
    resolution into `assets/<ID>/` and foreign-folder detection (§5.7).
- **Tests & acceptance:** hypothesis — normalisation idempotence; CRLF fixture; title
  extraction edge cases (blank lines before H1, missing H1, `---` start); section parsing
  (required empty vs placeholder-only vs unknown); mentions (CR IDs flagged as document-mention
  exempt by caller — function returns raw matches); asset refs (own folder ok, foreign folder
  identified, nested `../` normalisation).
- **Handoff brief:** "Implement gregraph/core/{hashing,markdown}.py per spec §5.2, §5.6, §5.7,
  §7.3. Pure functions, no I/O. markdown-it-py with mdit-py-plugins for GFM. Test-first."

### S3 — Config, storage, cache

- **Goal:** Config model and TOML I/O; file layout and canonical serialisation; sidecar
  read/write; the rebuildable index cache.
- **Spec refs:** §3, §5.3 (types in config), §5.4 (serialisation), appendix B.1, §16.5.
- **Depends on:** S0 (uses S1 models when available; may start with appendix B.3 contracts).
- **Deliverables:**
  - `core/config.py`: pydantic config model per appendix B.1 (`gregraph, ids, git, versioning,
    graph, assets, types, cr`); defaults; type-name validation `[a-z][a-z0-9-]*`; folder default
    = type name; TOML read (stdlib `tomllib`) and write — **choose** a minimal internal TOML
    emitter or `tomli-w` and record the choice + rationale in `docs/decisions.md` (§16.3).
  - `core/storage.py`: path rules of §3 (root layout, `documents/**`, `changes/`, `glossary/`,
    `assets/<ID>/`, `<ID>.md`/`<ID>.json`, glossary `<slug>.*`); canonical JSON writer per
    global rules (links sorted, etc.); read/write for document, CR, term sidecars and bodies;
    cache `.gregraph/cache/index.json` per §16.5 (`files` mtime/size/body_hash, `types_seen`,
    `templates_seen`), silent rebuild on absence/corruption.
- **Tests & acceptance:** canonical JSON byte-stability (same logical content → identical
  bytes; idempotent rewrite); model↔file round-trip; cache rebuild on corrupted file; config
  defaults match appendix B.1; unknown type-name shapes rejected.
- **Handoff brief:** "Implement gregraph/core/{config,storage}.py per spec §3, §5.3, §5.4,
  §16.5, appendix B.1. Decide TOML writing approach and document it in docs/decisions.md.
  Test-first; canonical JSON idempotence tests are mandatory."

---

## Wave 2

### S4 — Built-in template data *(parallel with S5's interface known from spec)*

- **Goal:** All 14 shipped templates as package data.
- **Spec refs:** appendix B.2, §5.5 (`template.md`/`template.json` shapes).
- **Depends on:** S1 (descriptor schema).
- **Deliverables:** `gregraph/builtin_templates/<name>/v1/{template.md,template.json}` for
  `context, goal, epic, feature, user-story, requirement-ears, constraint, design, decision,
  test-case, stakeholder, assumption, change-request, term`. `template.md` starts with
  `# {{ title }}` then `## Heading` + placeholder text in *italics*; descriptors carry
  `schema, name, version=1, description, deprecated=false, breaking=false, sections[]` with
  required flags and placeholders per appendix B.2.
- **Tests & acceptance:** golden tests — every template loads, renders with dummy variables,
  and its section headings/required flags match the appendix B.2 table exactly.
- **Handoff brief:** "Create the 14 built-in templates under gregraph/builtin_templates/ per
  appendix B.2 and the template.json schema of §5.5. Golden tests comparing rendered skeletons
  and section tables. No engine code."

### S5 — Template engine *(serial with S4's files for golden output)*

- **Goal:** Template loading, rendering, version resolution, deprecation behaviour, migration
  planning.
- **Spec refs:** §5.5, §7.7, §5.3 (type→template), §16.1 (`templates.py`).
- **Depends on:** S1, S2, S4.
- **Deliverables:** `core/templates.py`: load from `.gregraph/templates/<name>/v<N>/`; version
  contiguity check (dirs contiguous from `v1`); resolution = latest non-deprecated; Jinja2
  render with `title, id, type, kind, created, author, sections`; `new` refusal rules for
  deprecated versions (needs `--template-version` + `--allow-deprecated`); sections-hash helper
  for `E-TEMPLATE-MUTATED` cache detection; **migration planner** (pure function): in-place
  plan (per-step `breaking: false` required, insert missing sections at template position,
  apply `renamed_from`, leave unknown sections → `W-SECTION-UNKNOWN`) vs superseding plan
  (copy matching sections, unmatched under `## Unmapped content (migration)`).
- **Tests & acceptance:** golden renders; latest-non-deprecated resolution; deprecated refusal
  matrix; migration plans for three fixtures: additive (in-place), renamed (in-place with
  `renamed_from`), breaking (superseding). Planner is pure — writing is S15's job.
- **Handoff brief:** "Implement gregraph/core/templates.py per §5.5 and §7.7 (planning only;
  no file mutation beyond loading). Jinja2 rendering, version resolution, deprecation rules,
  sections hashing for cache. Test-first."

### S6 — Workspace and graph engine

- **Goal:** Root discovery, full index loading, in-memory graph with all graph algorithms.
- **Spec refs:** §3 (root rule), §6.1–6.5, §1.5 (sizing), §16.1.
- **Depends on:** S1, S3 (git stub from S0).
- **Deliverables:**
  - `core/workspace.py`: find root = nearest ancestor with `.gregraph/config.toml`; `Workspace`
    holding config, lazily loaded index (all sidecars in memory), cache, git adapter
    (`NullGitAdapter` until S7); the single entry point object for all operations.
  - `core/graph.py`: build graph from index; outbound edges from sidecars; computed inbound
    index; kind-rule enforcement (`E-EDGE-RULE`); mutual exclusion (`E-EDGE-EXCLUSIVE`);
    multiplicity (duplicate → no-op notice); cycle detection: link-time DFS from target with
    path reconstruction (`E-CYCLE` + path), whole-graph Kahn at validate; reachability helpers
    (1 level upstream over hierarchical edges; unlimited downstream over directed edges);
    roots (no outbound `refines`/`derives-from`, D1); orphans (no edges either way, excluding
    deprecated/superseded).
- **Tests & acceptance:** `sample_graph` fixture (~12 documents across all kinds with a
  realistic edge mix); hypothesis — random edge insertion sequences: tool accepts exactly the
  acyclic insertions and never accepts a cycle; exclusivity and rule violations classified
  correctly; roots/orphans match §6.3; 5 000-node synthetic index loads and cycle-checks within
  the §1.5/§17 budget (informal perf smoke test).
- **Handoff brief:** "Implement gregraph/core/{workspace,graph}.py per §3, §6, §16.1. Include
  the sample_graph fixture in tests/conftest.py. Hypothesis DAG invariant tests are mandatory."

---

## Wave 3

### S7 — Git adapter and hooks

- **Goal:** All Git access behind `GitAdapter`/`NullGitAdapter`; hook installation and the
  pre-commit script generator.
- **Spec refs:** §12.1, §12.2, §12.3, §12.5, §8 note on baseline branch, §16.1.
- **Depends on:** S0, S6 (workspace root).
- **Deliverables:**
  - `core/git.py`: full API of §12.1 — `is_repo, root, identity, current_branch,
    branch_exists, staged_paths, changed_paths, untracked_paths, differs_from_ref, is_tracked,
    file_at, files_at (ls-tree + one `cat-file --batch` process), stage, tag_annotated, tags,
    head_sha` — via `subprocess.run` with explicit arg lists, `cwd` = repo root, `LC_ALL=C`,
    30 s timeout; `NullGitAdapter` making degraded mode a first-class path; per-invocation
    single `note: not a git repository — <feature> unavailable` suppression helper (§12.1).
  - `core/hooks.py`: pre-commit script generation (`python -m gregraph` with the interpreter
    recorded at install time, falling back to `gregraph` on PATH); `install` (create or append
    a clearly delimited block), `uninstall`, `status` (installed? up to date?).
  - Identity handling: `created_by`/`by` from Git identity, `null` + warning when unset (§12.2).
- **Tests & acceptance:** real-`git` tests in `tmp_repo` for every adapter method;
  `files_at` returns baseline view of all sidecars; identity missing → `None` + warning;
  hook install/uninstall/status round-trip incl. appending to a pre-existing hook; Windows-safe
  paths.
- **Handoff brief:** "Implement gregraph/core/{git,hooks}.py per §12. Subprocess only, no Git
  libraries. Tests use real git in tmp fixtures. Do not implement the pre-commit *operation*
  itself (that is S9/S18) — only the adapter and hook script/install machinery."

### S8 — Derived status and WIP

- **Goal:** The §8 status model and WIP aggregation.
- **Spec refs:** §8 (all), §11.1 (`status` counts open conflicts).
- **Depends on:** S6, S7.
- **Deliverables:** `core/status.py`: per-document/term status derivation (`draft` via
  `git diff --quiet <baseline> -- <path>` + `git ls-files --error-unmatch`; `active`;
  `superseded` = inbound `supersedes`; `deprecated` = flag; precedence
  `deprecated > superseded > draft > active`; `unknown` without Git or when the baseline branch
  is missing, with a warning); WIP aggregate (any draft, any unbumped modification, any
  uncommitted file under managed directories) with the counts used by `status` output.
- **Tests & acceptance:** git fixtures producing each status and each precedence combination;
  degraded mode → `unknown`; missing baseline branch → `unknown` + warning; WIP counts correct.
- **Handoff brief:** "Implement gregraph/core/status.py per §8. Derived only — the sole stored
  flag is deprecated. Tests with real git fixtures for draft/active; degraded cases too."

---

## Wave 4

### S9 — Versioning and reconcile

- **Goal:** The heart of change tracking: reconcile, freshness, effective versions, repair.
- **Spec refs:** §7.1–7.5 (all), §7.2 repair rules, §12.6 guidance data.
- **Depends on:** S2, S6, S7 (S5 for CR template pinning used by reconcile of CRs).
- **Deliverables:** `core/versioning.py`:
  - `reconcile(scope, mode)` per §7.5 covering documents **and** CRs (normalise, hash body,
    hash assets, sync title from H1; CRs also `scope_hash` per §9.2 — coordinate the hashing
    helper with S13's spec contract; CRs have no assets): `bump` mode increments `version`
    exactly once per content change and writes sidecars (hook mode also stages them);
    `report` mode never writes.
  - Freshness table over the whole graph using **effective versions** (§7.4): fresh / outdated /
    stale / pending-outdated; report structure of §7.5 step 5 (bumped, newly outdated, previously
    outdated, stale, pending, validation findings placeholder).
  - Effective-version rule (`target.version + 1` if unbumped modifications, else `target.version`).
  - `repair versions` logic: conflict-marker parser for the standard `<<<<<<<` layout, extract
    both `version` values, set `version = max(seen) + 1`, recompute hashes, clamp
    `target_version ≤ target.version`, de-duplicate links.
  - Change detection is hash-based in both modes (D2 refinement 1).
- **Tests & acceptance:** bump-once semantics; newly-vs-previously outdated distinction (the
  blocking scope of D2 refinement 2 — blocking is decided by the caller/hook, this module
  classifies); effective version with unbumped target; hypothesis — `target_version ≤
  target.version` invariant after any accepted operation sequence; repair versions on a
  synthesised conflicted sidecar.
- **Handoff brief:** "Implement gregraph/core/versioning.py per §7. Compare content by stored
  hashes, not by Git (D2). Classify link freshness including pending-outdated and the
  newly-outdated set. Include the conflict-marker repair parser. Hypothesis freshness
  invariants mandatory."

---

## Wave 5 *(serial: both subtasks extend `validation.py`)*

### S10 — Validation: structural and document-side codes *(first)*

- **Goal:** `validation.py` skeleton + all codes that concern files, IDs, types, templates,
  sections, serialisation hygiene.
- **Spec refs:** §14 (code catalogue + `--json` shape), §4.3–4.4, §5.2–5.5.
- **Depends on:** S2, S3, S5, S6, S9.
- **Deliverables:** `core/validation.py`: findings registry/collector; per-code checks for
  `E-SIDECAR-MISSING, E-BODY-MISSING, E-SIDECAR-INVALID, E-ID-FILENAME, E-ID-DERIVATION,
  E-ID-DUPLICATE, E-UUID-DUPLICATE, E-TYPE-UNKNOWN, E-TYPE-KIND-CHANGED, E-TITLE-MISSING,
  E-FRONTMATTER-FORBIDDEN, E-TEMPLATE-UNKNOWN, E-TEMPLATE-MUTATED, E-SECTION-REQUIRED-MISSING,
  E-SECTION-REQUIRED-EMPTY, W-SECTION-UNKNOWN, W-SECTION-ORDER, W-TEMPLATE-DEPRECATED,
  W-LINE-ENDINGS, W-SIDECAR-NONCANONICAL, W-NO-GIT-IDENTITY, W-PREFIX-MISMATCH`; `--json`
  emission shape `[{code, severity, id|path, message, fix?}]` with suggested commands where
  they exist.
- **Tests & acceptance:** at least one test per listed code; `--strict` semantics live in the
  CLI, but a severity aggregation helper is provided here.
- **Handoff brief:** "Create gregraph/core/validation.py and implement the structural
  document-side codes of §14 (list in the plan). Findings are data. One test per code. Leave
  a clear extension structure for the relational codes (S11)."

### S11 — Validation: relational, asset, and misc codes *(after S10)*

- **Goal:** Complete the §14 catalogue except CR/term codes (those land in S13/S14).
- **Spec refs:** §14, §5.7, §6, §7.4, §11.1.
- **Depends on:** S10 (and its wave dependencies).
- **Deliverables:** same module — checks for `E-LINK-TARGET-MISSING, E-LINK-TYPE-UNKNOWN,
  E-EDGE-RULE, E-EDGE-EXCLUSIVE, E-CYCLE, E-LINK-VERSION-AHEAD, W-LINK-OUTDATED, W-LINK-STALE,
  W-LINK-PENDING, W-ORPHAN, W-MENTION-UNLINKED, E-MENTION-UNKNOWN, E-ASSET-MISSING,
  E-ASSET-FOREIGN, W-ASSET-ORPHAN, W-ASSET-LARGE, E-ASSET-OWNERLESS, W-CONFLICT-OPEN,
  E-TARGET-SUPERSEDED, E-TARGET-DEPRECATED` (as found in files edited outside the tool).
- **Tests & acceptance:** one test per code; cycle report includes the path; mention rules per
  §5.2 (CR IDs exempt from `W-MENTION-UNLINKED`); open-conflict definition per §11.1.
- **Handoff brief:** "Extend gregraph/core/validation.py with the relational/asset codes of §14
  (list in the plan). One test per code. CR and term codes are not yours — S13/S14 add them."

---

## Wave 6

Shared-file rule for this wave: **S12 creates `operations.py`** with the full function surface
(all §13 operations, stubs raising `NotImplementedError` where other subtasks own them). S13–S16
implement their own functions only — partition by function name; never reformat others' blocks.

### S12 — Document lifecycle operations

- **Goal:** `create_document`, linking, refresh, `set`, supersession, deprecation.
- **Spec refs:** §4.2, §5.4, §5.6, §7.4 (effective version at link time), §7.6, §13.2–13.6,
  §13.14, §13.15, §13.23, §11.2 patterns 1–2 behaviour (via supersede/deprecate).
- **Depends on:** S5, S6, S8, S9, S10/S11 (refusal findings), S7 (identity).
- **Deliverables:** `core/operations.py` surface + implementations: `create_document` (ID
  generation, template render, initial links each checked, `--edit` left to CLI, `--cr` hook
  stubbed for S13's `record_introduction`), `link` (rules, exclusivity, cycle refusal with
  path, duplicate no-op notice, `target_version` = target effective version, target must not be
  superseded/deprecated except `supersedes`), `unlink` (symmetric edges found on either
  endpoint), `link_refresh` (`--from/--to/--all`, effective version, `--follow` supersession
  chain with fork refusal `E-SUPERSEDE-FORK`, deprecated target refusal `E-TARGET-DEPRECATED`),
  `set` (tags `=`/`+=`/`-=`, `extra.<name>`, refusal messages pointing to the right command),
  `supersede` (multi-target compromise, `--copy-body`/`--copy-links` defaults per §7.6, `NEW
  supersedes OLD`, inbound links untouched → stale, `--cr` notice-not-mutate behaviour),
  `deprecate`/`undeprecate`.
- **Tests & acceptance:** cycle/rule/exclusivity/target-state refusals (`OperationRefused`
  with the right code); multi-target supersede (conflict compromise, §11.2); copy-links runs
  rule+cycle checks per copied edge; superseded target cannot be linked except `supersedes`;
  refresh `--follow` chain and fork cases.
- **Handoff brief:** "Create gregraph/core/operations.py (full §13 surface as stubs) and
  implement the document lifecycle subset per §7.6, §13.2–13.6, §13.14–13.15. Core rules:
  no printing, findings/refusals as data. Test-first."

### S13 — Change requests (core + operations + validation)

- **Goal:** The complete §9 CR subsystem outside the graph.
- **Spec refs:** §9 (all), §7.6 `--cr` rules, appendix B.3 `ChangeRequest`, §14 CR codes.
- **Depends on:** S12 (operations surface), S7 (`files_at` for baseline view), S9 (effective
  version rule for `at_version`).
- **Deliverables:**
  - `core/changes.py`: scope add/remove (target liveness rules `E-CR-SCOPE-TARGET`; `base_version`
    from baseline-branch version via `files_at`, effective working-tree version in degraded mode;
    new-work refusal pointing to `--cr`); `scope_hash` (canonical JSON of scope sorted by id);
    decision state machine (§9.3 transitions, `E-CR-STATUS`, initial `open` decision with
    `at_version = 1`); effective status (`git show <baseline>:changes/<ID>.json`, `none` if
    absent; equals proposed without Git); `reaffirm`, `reanalyze`; drift evaluation (§9.6 —
    baseline version > `base_version`, or target superseded/deprecated on baseline; only while
    effective status is `open`/`accepted`; `files_at` loaded lazily once); implementation check
    (§9.6 against working tree); origin tracking (`origin_cr` ↔ `introduces`,
    `E-CR-ORIGIN-MISSING`, `E-CR-ORIGIN-MISMATCH`, `E-CR-CLOSED` on closed CRs); modified-after-
    decision computation (`W-CR-MODIFIED-AFTER-DECISION` when effective version > last non-open
    decision's `at_version`).
  - `operations.py` CR functions: `cr_new, cr_scope_add, cr_scope_remove, cr_set (status/branch/
    external_ref/tags/extra), cr_reaffirm, cr_reanalyze, cr_list (filters --status/--effective/
    --pending/--drift), cr_show` (§9.8 incl. impact set: per scope target 1-up + unlimited-down
    de-duplicated); `record_introduction` used by `new`/`supersede --cr`.
  - Validation codes: `E-CR-DISABLED, E-CR-STATUS, E-CR-SCOPE-TARGET, E-CR-ORIGIN-MISSING,
    E-CR-ORIGIN-MISMATCH, W-CR-MODIFIED-AFTER-DECISION, W-CR-DECIDER-UNKNOWN, W-CR-BASE-DRIFT,
    W-CR-IMPLEMENTED-UNCHANGED, W-CR-MENTION-UNSCOPED` (+ `E-MENTION-UNKNOWN` semantics already
    in S11 for CR bodies per §9.7).
  - CR content rule: version bumps on body **or** scope change; status/decisions/introduces/
    branch/external_ref/tags/extra excluded from content (D14) — expose as a hashing contract
    matching S9's reconcile inputs.
- **Tests & acceptance:** one test per CR validation code; scenario tests mirroring BOOT-302
  (drift → reanalyze → modified-after-decision → reaffirm) and BOOT-303 (hook must not block on
  scope changes — contract test at report level); both workflows of §9.9 as state sequences;
  `cr.enabled = false` refusal surface.
- **Handoff brief:** "Implement gregraph/core/changes.py and the cr operations + CR validation
  codes per §9 (r0.2 semantics: CRs outside the graph, scope with base versions, drift,
  origin metadata, proposed vs effective status). Wire record_introduction into S12's new/
  supersede --cr. Test-first; the BOOT-302/303 scenarios are acceptance tests."

### S14 — Glossary

- **Goal:** §10 term entity and its operations/validation.
- **Spec refs:** §10 (all), §14 term codes, appendix B.2 `term` template.
- **Depends on:** S12 (operations surface), S5 (term template), S8 (statuses apply to terms).
- **Deliverables:** `term` operations (`add` with slug derivation, `list`, `show`, `usage`,
  `rename`, `deprecate`) in `operations.py`; validation `E-TERM-SLUG` (slug/filename mismatch
  or H1 ≠ term) and `E-TERM-ALIAS-CLASH` (alias vs alias, alias vs term names); usage matching
  (case-insensitive, word-boundary, over names + aliases); `rename` rewrites files + sidecar and
  **lists** body mentions without rewriting prose.
- **Tests & acceptance:** slug derivation table; alias clash matrix; usage matching (word
  boundaries, case); rename round-trip.
- **Handoff brief:** "Implement the glossary subsystem per §10 in operations.py (small — term
  logic may live in storage.py helpers). Slug identity, alias uniqueness, mention-based usage.
  Test-first."

### S15 — Templates ops, migration, baselines, repair

- **Goal:** The remaining lifecycle commands: `template *`, `migrate`, `baseline`, `repair *`.
- **Spec refs:** §7.7 (execute the S5 plans), §12.4, §12.6, §13.16–13.19, §4.4 (`regenerate-id`),
  §16.5 (`repair cache`).
- **Depends on:** S5, S9, S12 (supersede reused by superseding migration).
- **Deliverables:** operations: `template_list/add/bump/show`; `migrate` (selection `--all/--template/
  ID…`, `--to`, in-place execution of S5's plan incl. `renamed_from`, superseding migration
  with `## Unmapped content (migration)` and manual-attention report, `--dry-run`);
  `baseline_create` (annotated tag `baseline/<name>` with generated manifest — ID, version,
  body_hash, status per document, ID prefix, tool version; refuses on uncommitted managed files
  or validation errors), `baseline_list`; `repair_versions` (uses S9 logic), `repair_regenerate_id`
  (new UUID/ID for one of a duplicate pair, rewrite inbound links **from the same branch's
  history** where the link's `target` equals the old ID and list the rest for manual re-linking),
  `repair_cache`.
- **Tests & acceptance:** M4 acceptance — migration scenarios (additive → version bump on next
  commit; renamed → headings renamed; breaking → supersede path); baseline tag message contains
  the manifest and `baseline list` sees it; regenerate-id on a synthesised `E-ID-DUPLICATE`
  fixture (the fatal validate error from §4.4).
- **Handoff brief:** "Implement template/migrate/baseline/repair operations per §7.7, §12.4,
  §12.6, §13.16–13.19, §4.4. Reuse S5's migration planner and S12's supersede. Test-first."

### S16 — Mermaid export

- **Goal:** `core/mermaid.py` per §15.
- **Spec refs:** §15 (all).
- **Depends on:** S6.
- **Deliverables:** `flowchart TD|LR` emitter: Mermaid node id = document ID without hyphens;
  label `RE-XXXXXX<br/>title truncated to 40 chars` with quote escaping; shapes by kind
  (stadium/rectangle/subroutine/hexagon/flag); edge styles by type (solid/dotted/thick/labelled);
  `conflicts-with`/`relates-to` undirected `---` with label; `linkStyle` red for conflicts;
  `classDef` dashed for deprecated/superseded when included; `--root/--depth` subgraph limiting
  (downstream of roots, depth-limited); warning above 300 nodes.
- **Tests & acceptance:** golden outputs for the `sample_graph` fixture; escaping fixture
  (quotes in titles); >300-node warning; direction and depth limiting.
- **Handoff brief:** "Implement gregraph/core/mermaid.py per §15. Pure string generation from
  the graph model. Golden tests mandatory."

---

## Wave 7

Shared-file rule: **S17 owns `cli/main.py`, `cli/output.py`, `cli/prompts.py`** and registers
*all* subparsers (handlers may delegate to command modules that S18/S19 fill in). S18/S19 only
add/edit their own `cli/commands/*.py` modules.

### S17 — CLI framework and core commands

- **Goal:** argparse tree, global options, exit codes, output/prompt machinery, and the M1
  commands.
- **Spec refs:** §13 (general), §13.1 `init`, §13.2 `new`, §13.11 `show`, §13.10 `list`,
  §13.23 `edit`, §3 (init layout), §5.5 (templates copied on init).
- **Depends on:** S12 (create/list/show ops), S4 (built-ins to copy), S7 (hooks install on init).
- **Deliverables:**
  - `cli/main.py`: subparsers for **all** §13 commands; global `--repo, --no-input, --json,
    -q, -v, --version`; exit-code mapping (0 ok, 1 validation/blocked, 2 usage, 3 no repo/env,
    4 refused, 5 internal); `OperationRefused` → exit 4 with the finding printed.
  - `cli/output.py`: plain-text findings (`E-…`/`W-…` + subject), tables for `list`, JSON
    mode for `list/show/status/validate/check/graph`; colours only when stdout is a TTY and
    `NO_COLOR` unset; no third-party terminal libs.
  - `cli/prompts.py`: TTY prompts for missing required args (skipped with `--no-input` → error,
    exit 2); filtered numbered pickers (ID, type, title, status; accept number/exact ID/refined
    filter; `q` cancels); every prompt has a flag equivalent.
  - `cli/commands/{init,new,show,list,edit}.py`: `init` per §13.1 (layout, copy built-ins
    `--templates all|minimal`, write config/`.gitignore`/`README.md`, `git init` unless
    `--no-git`, install hooks unless `--no-git`, refuse if `.gregraph/` exists); `new` with
    interactive type/title/links prompts and `--edit`.
- **Tests & acceptance:** M1 acceptance — `gregraph init && gregraph new user-story --title X
  --no-input` produces a valid file pair; exit-code tests (3 outside a repo, 2 on usage);
  picker unit tests with a scripted stdin; `NO_COLOR`/TTY colour behaviour.
- **Handoff brief:** "Build the CLI layer per §13 general rules plus commands init/new/show/
  list/edit. argparse only. Register every command's subparser now (stubs ok for S18/S19
  commands). Interactive pickers in cli/prompts.py. CLI tests call gregraph.cli.main.main([...])
  with the tmp_repo fixture."

### S18 — CLI: graph, link, sync, check, validate, status *(parallel with S19)*

- **Goal:** The middle command set, incl. the hook's logical entry behaviours surfaced as
  `check`/`sync`.
- **Spec refs:** §13.3–13.9, §13.12–13.13, §7.5, §14 `--json`, §15 (graph command wrapping S16).
- **Depends on:** S17, S9, S11, S16.
- **Deliverables:** `cli/commands/{link,unlink,refresh,set,sync,check,validate,status,graph}.py`:
  `link` interactive flow (type-filtered pickers, cycle candidates precomputed and excluded,
  help text prints §6.1 guidelines); `link refresh` flags incl. `--follow/--dry-run`;
  `sync [--bump]` (mode per §7.5: bump in degraded mode or with `--bump`, report otherwise);
  `check` (hook simulation over all working-tree changes; exit 1 iff hook would block);
  `validate [--strict] [--only-errors]` with `--json`; `status` (WIP header, all §13.12
  sections); `graph` (S16 output, `--root/--depth/--types/--edges/--include-superseded/
  --direction/-o`).
- **Tests & acceptance:** `check` exit codes match hook policy; `validate --strict` exits 1 on
  warnings only; `status` WIP header format; `graph` golden; link refusals exit 4.
- **Handoff brief:** "Implement cli/commands for link/unlink/refresh/set/sync/check/validate/
  status/graph per §13.3–13.9, §13.12–13.13. Thin: parse → operations → format. Gate green."

### S19 — CLI: lifecycle, templates, repair, term, baseline, hooks, cr *(parallel with S18)*

- **Goal:** The remaining commands including the internal hook entry point.
- **Spec refs:** §13.14–13.22, §7.5 hook behaviour, §12.3, §9.9 workflow notes.
- **Depends on:** S17, S12–S15, S9.
- **Deliverables:** `cli/commands/{supersede,deprecate,migrate,template,repair,term,baseline,
  hooks,cr,hook}.py`: `supersede` incl. multi-target and `--cr`; `migrate` with `--dry-run`
  plan output; `template list/add/bump/show`; `repair versions/regenerate-id/cache` (help text
  prints §12.6 guidance); `term *`; `baseline create/list`; `hooks install/uninstall/status`;
  **`hook pre-commit`** (hidden from `--help`): scope = staged `.md` under `documents/`,
  `changes/`, `glossary/` + documents whose staged assets or sidecars changed; `mode=bump`;
  abort (exit 1) on validation errors or newly outdated links when
  `versioning.on_outdated_links = "block"` (or open conflicts when `graph.open_conflicts =
  "block"` **and** current branch is the baseline branch); print exact
  `gregraph link refresh …` commands; warnings never abort; policy `versioning.on_cr_modified`
  for CR-after-decision; never abort because of drift or scope changes (BOOT-128).
- **Tests & acceptance:** M3 acceptance — a real `git commit` in `tmp_repo` is blocked when a
  link is newly outdated and succeeds after `link refresh`; degraded-mode `sync` bumps;
  M4 acceptance — migrate scenarios end-to-end via CLI; CR proposal-first and single-PR
  walkthroughs via CLI; hook does not block on CR scope edits (BOOT-303).
- **Handoff brief:** "Implement the remaining cli/commands per §13.14–13.22 plus the hidden
  hook pre-commit entry point per §7.5. Hook tests must run real git commits and assert exit
  codes and sidecar changes. Gate green."

---

## Wave 8

### S20 — Documentation

- **Goal:** Human-facing docs and the decision record.
- **Spec refs:** §18 M5 deliverables, appendix C definition of done, §20 (decision log may be
  mirrored into docs/decisions.md).
- **Depends on:** S17–S19 (stable CLI surface).
- **Deliverables:** repository `README.md` (tool overview, install, quickstart); `docs/cli.md`
  (every command, flags, exit codes, interactive behaviour); `docs/concepts.md` (§2 vocabulary,
  §7 versioning model, §8 status, §9 CR workflows — written for humans); `docs/decisions.md`
  completed (TOML writer choice, any documented deviations); `docs/backlog.md` populated with
  the §20 v0.2 open items and anything the agents deferred; `AGENTS.md` kept accurate.
- **Tests & acceptance:** docs mention every §13 command; no undocumented flags; definition-of-
  done doc items checked.
- **Handoff brief:** "Write README.md, docs/cli.md, docs/concepts.md from the spec and the
  implemented CLI; complete docs/decisions.md and docs/backlog.md. Do not change behaviour."

### S21 — Release quality gate

- **Goal:** Meet §17 metrics, verify packaging, release 0.1.0.
- **Spec refs:** §17, §16.4, appendix C definition of done.
- **Depends on:** S20 (and everything before).
- **Deliverables:** coverage gaps filled (≥ 90 % `gregraph/core`, ≥ 75 % overall); CI matrix
  green on Linux/macOS/Windows × 3.12/3.13; `pip install .` and `pipx install .` verified;
  `pipx run gregraph --version` smoke; version consistency (`pyproject`, `__version__`,
  `config.toml` template `tool_version`); annotated tag `v0.1.0`; short release notes.
- **Tests & acceptance:** the definition-of-done checklist in appendix C minus M6.
- **Handoff brief:** "Close out the release: raise coverage to the targets, make CI green on
  the full matrix, verify pip/pipx installs, tag v0.1.0. Fix only test/doc/CI gaps — behaviour
  changes go to docs/backlog.md unless they fix a spec violation."

---

## Wave 9

### S22 — Bootstrap (M6 dogfooding)

- **Goal:** Use the released tool to create the `gregraph-requirements` repository; fix what
  dogfooding exposes; release 0.1.1.
- **Spec refs:** §18 M6, §19 (all), appendix A (source data).
- **Depends on:** S21.
- **Deliverables:** separate repository `gregraph-requirements` created with
  `gregraph init --prefix RE`; one document per appendix A item (`new <type> --title …`,
  EARS text into the *Statement* section, `link` per the Refines/Constrains columns);
  `bootstrap-map.md` mapping `BOOT-nnn → RE-…` deleted once seeding is complete; verification
  documents derived from BOOT-300…303 and the functional requirements (§19 note); commits
  through the pre-commit hook; `baseline/0.1.0` created; findings recorded in the tool repo's
  `docs/backlog.md`/issues; fixes released as 0.1.1.
- **Tests & acceptance:** the seeded repository passes `gregraph validate --strict`; the map is
  gone; baseline tag exists; dogfooding findings triaged.
- **Handoff brief:** "Seed the gregraph-requirements repository per §19 from appendix A using
  the installed tool (not by writing sidecars by hand). Keep bootstrap-map.md until done. Run
  validate --strict. Report dogfooding findings."

---

## Milestone mapping (spec §18)

| Milestone | Subtasks | §18 acceptance |
|---|---|---|
| M1 Skeleton and models | S0–S6, S17 | `init && new user-story --title X --no-input` yields a valid pair |
| M2 Graph | S10–S12 (link/unlink), S16, S18 (link/graph/validate subset) | DAG property tests pass; Mermaid renders |
| M3 Versioning and Git | S7–S9, S18 (sync/check/status), S19 (hook pre-commit) | hook blocks newly outdated links; refresh + commit succeeds; degraded `sync` bumps |
| M4 Lifecycle | S15, S19 (supersede/migrate/template/baseline/repair) | migration scenarios (additive, renamed, breaking) pass |
| M5 CRs, glossary, assets, polish | S13, S14, asset coverage in S11/S12, S20, S21 | §17 quality, docs written, release 0.1.0 |
| M6 Bootstrap | S22 | requirements repo seeded; 0.1.1 |

Tag each milestone when its acceptance row passes (even if a few supporting subtasks from a
neighbouring wave contributed), per appendix C workflow.

## Risks and coordination rules

1. **Shared files.** `operations.py` (S12–S16), `validation.py` (S10–S11), `cli/main.py`
   (S17–S19). Rule: the first subtask creates the complete surface (signatures/stubs); later
   subtasks implement only their named functions and never reformat foreign blocks. If a
   subagent must edit a shared file heavily, run that wave's subtasks sequentially.
2. **Largest subtasks.** S11 (relational validation), S13 (CRs), S19 (CLI + hook). If a single
   agent overflows: S11 splits into link-codes vs mention/asset/conflict-codes (still
   sequential); S13 splits into `changes.py` logic vs `cr` operations+validation; S19 splits
   into hook entry point vs the remaining commands.
3. **Spec ambiguities.** The spec takes decisions (§20) and says the agent implements them as
   written. If an agent finds a genuine gap or contradiction, it records it in
   `docs/backlog.md` with a `SPEC-QUESTION:` prefix and implements the most conservative
   reading; the plan owner reviews between waves.
4. **Performance.** §1.5/§16.6 budgets (5 000 sidecars < 1.5 s load; validate < 5 s) are
   smoke-tested in S6 and re-checked in S21; index/cache design must not be regressed.
5. **Windows/CRLF.** S2 normalisation and S7 path handling carry this; CI matrix (S0/S21)
   enforces it.
