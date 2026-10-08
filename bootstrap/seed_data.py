"""Seed data for gregraph-requirements, transcribed from docs/design.md appendix A.

One entry per appendix A item. Statements are verbatim; titles and secondary
required-section content are derived. Verification documents are one test-case
per functional requirement (BOOT-100..128), with BOOT-300..303 scenarios used
where they cover the requirement.
"""

# (boot, type, title, sections) — sections are the required template sections.
GOALS = [
    (
        "BOOT-001",
        "goal",
        "Manage requirements as a Git-synchronised DAG",
        {
            "Goal": (
                "The tool shall let a requirements engineer manage requirements as a "
                "directed acyclic graph of atomic Markdown documents, synchronised "
                "only "
                "through Git."
            ),
            "Rationale": (
                "A versioned DAG kept in Git gives the team a reviewable, offline "
                "requirements model with no server to run and no second source of "
                "truth."
            ),
        },
    ),
    (
        "BOOT-002",
        "goal",
        "Tool-owned structure, human-owned prose",
        {
            "Goal": (
                "The tool shall ensure that humans edit only Markdown prose and "
                "configuration, while all structure (files, identifiers, metadata, "
                "links, "
                "versions) is owned by the tool."
            ),
            "Rationale": (
                "Keeping structure in tool-owned sidecars prevents drift and merge "
                "conflicts in metadata, while authors keep editing familiar Markdown."
            ),
        },
    ),
    (
        "BOOT-003",
        "goal",
        "Make every requirement change visible to dependents",
        {
            "Goal": (
                "The tool shall make every change to a requirement visible to the "
                "owners "
                "of dependent requirements."
            ),
            "Rationale": (
                "Dependents must re-check their assumptions whenever a requirement "
                "changes; silent change is the main source of stale requirements."
            ),
        },
    ),
    (
        "BOOT-004",
        "goal",
        "Serve teams of up to 20 engineers without a server",
        {
            "Goal": (
                "The tool shall be usable by a team of up to 20 engineers on "
                "repositories "
                "of several thousand documents without a server."
            ),
            "Rationale": (
                "The tool must stay lightweight enough for ordinary teams: no server, "
                "no "
                "database, and acceptable latency on realistic repositories."
            ),
        },
    ),
]

FEATURES = [
    (
        "BOOT-010",
        "feature",
        "Repository initialisation with shipped templates",
        {
            "Description": "Repository initialisation with shipped templates.",
            "Benefit": (
                "A new repository is usable in one command, with consistent templates "
                "and hooks from the start."
            ),
        },
    ),
    (
        "BOOT-011",
        "feature",
        "Document creation from versioned templates",
        {
            "Description": "Document creation from versioned templates with stable "
            "identifiers.",
            "Benefit": (
                "Engineers create well-formed documents with stable identifiers "
                "without "
                "hand-writing metadata."
            ),
        },
    ),
    (
        "BOOT-012",
        "feature",
        "Typed, rule-checked, acyclic linking",
        {
            "Description": "Typed, rule-checked, acyclic linking.",
            "Benefit": (
                "The graph stays meaningful and acyclic; invalid relationships are "
                "refused at entry time."
            ),
        },
    ),
    (
        "BOOT-013",
        "feature",
        "Content versioning and link freshness",
        {
            "Description": "Content versioning and link freshness.",
            "Benefit": (
                "Owners of dependent requirements see exactly which links need "
                "re-review "
                "after a change."
            ),
        },
    ),
    (
        "BOOT-014",
        "feature",
        "Supersession, deprecation, and template migration",
        {
            "Description": "Supersession, deprecation, and template migration.",
            "Benefit": (
                "Requirements can evolve and retire without losing history or silently "
                "breaking inbound links."
            ),
        },
    ),
    (
        "BOOT-015",
        "feature",
        "Change requests outside the graph",
        {
            "Description": (
                "Change requests outside the graph with scope, drift detection, origin "
                "tracking, and decision tracking."
            ),
            "Benefit": (
                "Proposed change is discussed and decided with explicit scope and "
                "drift "
                "visibility before implementation."
            ),
        },
    ),
    (
        "BOOT-016",
        "feature",
        "Glossary outside the graph",
        {
            "Description": "Glossary outside the graph.",
            "Benefit": (
                "Shared vocabulary is maintained once and discoverable, without "
                "polluting the dependency graph."
            ),
        },
    ),
    (
        "BOOT-017",
        "feature",
        "Validation as command, hook, and CI check",
        {
            "Description": "Validation as command, hook, and CI check.",
            "Benefit": (
                "Consistency is enforced automatically at every stage: locally on "
                "demand, on commit, and in CI."
            ),
        },
    ),
    (
        "BOOT-018",
        "feature",
        "Status and WIP reporting derived from Git",
        {
            "Description": "Status and WIP reporting derived from Git.",
            "Benefit": (
                "Engineers and leads can see at a glance what is still in progress and "
                "what has been merged."
            ),
        },
    ),
    (
        "BOOT-019",
        "feature",
        "Mermaid graph export",
        {
            "Description": "Mermaid graph export.",
            "Benefit": (
                "The requirements structure can be reviewed and shared as a diagram "
                "without extra tooling."
            ),
        },
    ),
    (
        "BOOT-020",
        "feature",
        "Assets owned and versioned by documents",
        {
            "Description": "Assets owned and versioned by documents.",
            "Benefit": (
                "Diagrams and other assets version together with the requirement that "
                "owns them."
            ),
        },
    ),
]

FRS = [
    (
        "BOOT-100",
        "functional-requirement",
        "init creates the layout, templates, config, and hook",
        {
            "Statement": (
                "WHEN `gregraph init` is run in a directory without `.gregraph/`, the "
                "tool shall create the repository layout, copy all built-in templates "
                "as "
                "version 1, write the default configuration, and install the "
                "pre-commit "
                "hook if Git is available."
            ),
            "Rationale": (
                "One command must produce a complete, consistent repository so every "
                "team starts from the same layout and hook discipline."
            ),
        },
    ),
    (
        "BOOT-101",
        "functional-requirement",
        "Identifiers are derived, prefixed, and regenerated on collision",
        {
            "Statement": (
                "WHEN a document is created, the tool shall generate a UUIDv4, derive "
                "a "
                "6-character Crockford base32 identifier from its first 30 bits, "
                "prefix "
                "it with the configured prefix, and regenerate on collision with any "
                "existing identifier."
            ),
            "Rationale": (
                "Short, readable, derivable identifiers keep references usable while "
                "the "
                "UUID keeps global uniqueness."
            ),
        },
    ),
    (
        "BOOT-102",
        "functional-requirement",
        "Identifiers are never reused",
        {
            "Statement": (
                "The tool shall never reuse an identifier, including identifiers of "
                "deprecated or superseded documents."
            ),
            "Rationale": (
                "Reusing an identifier would silently re-point references in old "
                "documents and discussions."
            ),
        },
    ),
    (
        "BOOT-103",
        "functional-requirement",
        "Documents are stored as Markdown plus JSON sidecar",
        {
            "Statement": (
                "The tool shall store every document as one Markdown file and one JSON "
                "sidecar with the identifier as filename stem."
            ),
            "Rationale": (
                "Splitting prose from metadata keeps Markdown diffs clean and lets the "
                "tool own structure completely."
            ),
        },
    ),
    (
        "BOOT-104",
        "functional-requirement",
        "Cycle-creating links are refused with the cycle path",
        {
            "Statement": (
                "WHEN a link is requested that would create a directed cycle over the "
                "directed edge types, the tool shall refuse the link and print the "
                "cycle "
                "path."
            ),
            "Rationale": (
                "A cyclic dependency graph cannot be reasoned about topologically; "
                "refusing at link time keeps the graph acyclic."
            ),
        },
    ),
    (
        "BOOT-105",
        "functional-requirement",
        "Kind-rule violations are refused with the rule named",
        {
            "Statement": (
                "WHEN a link is requested whose source or target kind violates the "
                "edge "
                "type's kind rule, the tool shall refuse the link and name the rule."
            ),
            "Rationale": (
                "Kind rules encode the modelling language; naming the rule teaches the "
                "user the intended structure."
            ),
        },
    ),
    (
        "BOOT-106",
        "functional-requirement",
        "Directed edges live on the source only",
        {
            "Statement": (
                "The tool shall store directed edges on the source document only and "
                "compute inbound edges from an index."
            ),
            "Rationale": (
                "Storing an edge once, on its source, avoids split-brain metadata and "
                "merge conflicts on the target."
            ),
        },
    ),
    (
        "BOOT-107",
        "functional-requirement",
        "The pre-commit hook bumps staged changed documents",
        {
            "Statement": (
                "WHEN the pre-commit hook runs, the tool shall increment the version "
                "of "
                "every staged document whose normalised body hash or asset hashes "
                "differ "
                "from the stored hashes, and stage the rewritten sidecar."
            ),
            "Rationale": (
                "Version increments must be automatic and tied to what is actually "
                "committed, or the history lies."
            ),
        },
    ),
    (
        "BOOT-108",
        "functional-requirement",
        "The pre-commit hook blocks newly outdated links",
        {
            "Statement": (
                "WHEN a commit would newly outdate at least one link and the policy is "
                "`block`, the pre-commit hook shall abort the commit and list the "
                "exact "
                "refresh commands."
            ),
            "Rationale": (
                "A commit that changes a requirement must not silently invalidate "
                "dependents; the block forces a deliberate refresh."
            ),
        },
    ),
    (
        "BOOT-109",
        "functional-requirement",
        "sync bumps versions without Git",
        {
            "Statement": (
                "WHERE no Git repository is present, `gregraph sync` shall perform the "
                "version increments that the hook would perform."
            ),
            "Rationale": (
                "The same versioning semantics must hold where no Git repository "
                "exists "
                "so behaviour does not depend on environment."
            ),
        },
    ),
    (
        "BOOT-110",
        "functional-requirement",
        "check reports the hook's findings without modifying files",
        {
            "Statement": (
                "`gregraph check` shall report what the pre-commit hook would report "
                "for "
                "all working-tree changes without modifying files."
            ),
            "Rationale": (
                "Users need to see what the hook will do before committing, without "
                "side effects."
            ),
        },
    ),
    (
        "BOOT-111",
        "functional-requirement",
        "link refresh --follow follows supersession chains",
        {
            "Statement": (
                "WHEN a link's target is superseded, `gregraph link refresh --follow` "
                "shall re-point the link to the end of the supersession chain, or fail "
                "if the chain forks."
            ),
            "Rationale": (
                "When a requirement is replaced, dependents should be re-pointed to "
                "the "
                "successor in one review act."
            ),
        },
    ),
    (
        "BOOT-112",
        "functional-requirement",
        "supersede accepts multiple targets",
        {
            "Statement": (
                "WHEN `gregraph supersede` is given multiple targets, the tool shall "
                "create one document with one `supersedes` edge per target."
            ),
            "Rationale": (
                "Conflict compromise and consolidation need a single new document "
                "replacing several old ones."
            ),
        },
    ),
    (
        "BOOT-113",
        "functional-requirement",
        "Documents are validated against their pinned template version",
        {
            "Statement": (
                "The tool shall validate each document against the template version "
                "pinned in its sidecar."
            ),
            "Rationale": (
                "Documents must be judged against the template version they were "
                "written for, not against later changes."
            ),
        },
    ),
    (
        "BOOT-114",
        "functional-requirement",
        "Deprecated template versions warn per document",
        {
            "Statement": (
                "WHEN a template version is marked deprecated, `gregraph validate` "
                "shall warn for every document pinned to it."
            ),
            "Rationale": (
                "A deprecated template version signals that its documents should "
                "migrate; the warning makes them findable."
            ),
        },
    ),
    (
        "BOOT-115",
        "functional-requirement",
        "Modification after decision warns",
        {
            "Statement": (
                "WHEN a change request's version exceeds the version recorded by its "
                "last non-open decision, `gregraph validate` shall warn that the "
                "change "
                "request was modified after decision."
            ),
            "Rationale": (
                "A decision made on older content must be flagged so deciders "
                "re-examine "
                "what they approved."
            ),
        },
    ),
    (
        "BOOT-116",
        "functional-requirement",
        "Scope entries record base versions",
        {
            "Statement": (
                "WHEN a scope entry is added to a change request, the tool shall "
                "record "
                "the target's version on the baseline branch (without Git: the "
                "working-tree version) as base version and shall change it only "
                "through "
                "`gregraph cr reanalyze`."
            ),
            "Rationale": (
                "Drift detection needs a recorded starting point per scope target that "
                "only explicit re-analysis may change."
            ),
        },
    ),
    (
        "BOOT-117",
        "functional-requirement",
        "Glossary terms are slug-identified with usage reports",
        {
            "Statement": (
                "The tool shall manage glossary terms as slug-identified Markdown "
                "files "
                "outside the graph and report documents that mention a term."
            ),
            "Rationale": (
                "Shared vocabulary needs one authoritative definition and a way to "
                "find "
                "every document that uses it."
            ),
        },
    ),
    (
        "BOOT-118",
        "functional-requirement",
        "validate --strict fails on any warning or error",
        {
            "Statement": (
                "`gregraph validate --strict` shall exit non-zero if any warning or "
                "error is found."
            ),
            "Rationale": (
                "CI must be able to treat warnings as failures so that hygiene does "
                "not "
                "erode."
            ),
        },
    ),
    (
        "BOOT-119",
        "functional-requirement",
        "status reports WIP, drafts, and unbumped modifications",
        {
            "Statement": (
                "`gregraph status` shall report whether the repository is in WIP state "
                "and list drafts and unbumped modifications."
            ),
            "Rationale": (
                "Engineers need a single view of what is unfinished before review or "
                "release."
            ),
        },
    ),
    (
        "BOOT-120",
        "functional-requirement",
        "draft and active are derived from the baseline branch",
        {
            "Statement": (
                "The tool shall derive `draft` and `active` status by comparing files "
                "with the configured baseline branch and report `unknown` without Git."
            ),
            "Rationale": (
                "Status must reflect what has actually been merged to the baseline "
                "branch, not what is merely written."
            ),
        },
    ),
    (
        "BOOT-121",
        "functional-requirement",
        "graph emits a styled Mermaid flowchart",
        {
            "Statement": (
                "`gregraph graph` shall emit a Mermaid flowchart with node shapes by "
                "kind and edge styles by type."
            ),
            "Rationale": (
                "A diagram is the fastest way to review overall requirements structure "
                "with stakeholders."
            ),
        },
    ),
    (
        "BOOT-122",
        "functional-requirement",
        "Asset changes count as content changes",
        {
            "Statement": (
                "The tool shall recompute a document's asset list and hashes on "
                "reconcile and treat any asset change as a content change."
            ),
            "Rationale": (
                "Assets are part of a requirement's content; their change must bump "
                "versions like body changes."
            ),
        },
    ),
    (
        "BOOT-123",
        "functional-requirement",
        "Missing arguments prompt or fail under --no-input",
        {
            "Statement": (
                "WHEN a required argument is missing and stdin is a terminal, the tool "
                "shall prompt with a filtered picker; WHERE `--no-input` is given, the "
                "tool shall fail instead."
            ),
            "Rationale": (
                "Interactive use should guide; automation must fail loudly instead of "
                "hanging."
            ),
        },
    ),
    (
        "BOOT-124",
        "functional-requirement",
        "Unlinked identifier mentions warn",
        {
            "Statement": (
                "WHEN a body mentions an identifier that has no edge in either "
                "direction, the tool shall warn."
            ),
            "Rationale": (
                "An identifier mentioned without an edge is usually an intended "
                "relationship that was never recorded."
            ),
        },
    ),
    (
        "BOOT-125",
        "functional-requirement",
        "Scope drift warns while a change request is open or accepted",
        {
            "Statement": (
                "WHILE a change request's effective status is `open` or `accepted`, IF "
                "a scope target's version on the baseline branch exceeds its base "
                "version, or the target is superseded or deprecated on the baseline "
                "branch, THEN `gregraph validate` shall warn of drift."
            ),
            "Rationale": (
                "A change request decided against older baseline content no longer "
                "reflects reality and must be re-examined."
            ),
        },
    ),
    (
        "BOOT-126",
        "functional-requirement",
        "origin_cr and introduces are recorded with --cr",
        {
            "Statement": (
                "WHEN a document is created or superseded with `--cr`, the tool shall "
                "record the change request in the new document's `origin_cr` and add "
                "the document's ID to the change request's `introduces` list."
            ),
            "Rationale": (
                "Traceability from a requirement back to the change request that "
                "introduced it must be recorded automatically."
            ),
        },
    ),
    (
        "BOOT-127",
        "functional-requirement",
        "Effective change request status comes from the baseline branch",
        {
            "Statement": (
                "The tool shall derive a change request's effective status from its "
                "sidecar on the baseline branch and show the working-tree status as "
                "proposed when the two differ."
            ),
            "Rationale": (
                "What is decided on the baseline branch is what counts; a pending "
                "local "
                "status must not masquerade as decided."
            ),
        },
    ),
    (
        "BOOT-128",
        "functional-requirement",
        "The hook ignores drift and CR scope changes",
        {
            "Statement": (
                "The pre-commit hook shall not abort a commit because of drift or "
                "because documents in a change request's scope changed."
            ),
            "Rationale": (
                "Drift and scope churn are review topics; they must not block "
                "unrelated "
                "commits on the change request's branch."
            ),
        },
    ),
]

NFRS = [
    (
        "BOOT-200",
        "non-functional-requirement",
        "Validate 5,000 documents within 5 seconds",
        {
            "Statement": (
                "The tool shall load a repository of 5,000 documents and complete "
                "`gregraph validate` within 5 seconds on a laptop-class machine."
            ),
            "Rationale": (
                "5,000 documents is the design sizing assumption (§1.5); validate is "
                "the "
                "hot path for hooks and CI."
            ),
        },
    ),
    (
        "BOOT-201",
        "non-functional-requirement",
        "Only pydantic, jinja2, and markdown-it-py at runtime",
        {
            "Statement": (
                "The tool shall run with only `pydantic`, `jinja2`, and "
                "`markdown-it-py` "
                "as runtime dependencies."
            ),
            "Rationale": (
                "A tiny dependency set keeps installation trivial and the security "
                "surface small."
            ),
        },
    ),
    (
        "BOOT-202",
        "non-functional-requirement",
        "Byte-identical canonical sidecars",
        {
            "Statement": (
                "The tool shall produce byte-identical sidecars for identical logical "
                "content (canonical serialisation)."
            ),
            "Rationale": (
                "Byte-identical output for identical content keeps diffs, merges, and "
                "hashes stable across machines."
            ),
        },
    ),
    (
        "BOOT-203",
        "non-functional-requirement",
        "Core operations without console I/O",
        {
            "Statement": (
                "The core library shall expose every operation as a function without "
                "console I/O so that a web UI can reuse it."
            ),
            "Rationale": (
                "The core is the future API for any front end; console I/O in the core "
                "would block that."
            ),
        },
    ),
    (
        "BOOT-204",
        "non-functional-requirement",
        "Linux, macOS, and Windows on Python 3.12+",
        {
            "Statement": (
                "The tool shall run on Linux, macOS, and Windows with Python 3.12 or "
                "later."
            ),
            "Rationale": (
                "Requirements teams use mixed platforms; file handling must be "
                "portable "
                "and identical everywhere."
            ),
        },
    ),
    (
        "BOOT-205",
        "constraint",
        "No network communication",
        {
            "Constraint": "The tool shall not communicate with any network service.",
            "Source": "GREGraph design §1.2 design principles (local-first, offline).",
        },
    ),
]

# Directed links (type, source boot key, target boot key) from the
# Refines / Constrains columns of appendix A.
LINKS = [
    ("refines", "BOOT-010", "BOOT-001"),
    ("refines", "BOOT-010", "BOOT-002"),
    ("refines", "BOOT-011", "BOOT-002"),
    ("refines", "BOOT-012", "BOOT-001"),
    ("refines", "BOOT-013", "BOOT-003"),
    ("refines", "BOOT-014", "BOOT-001"),
    ("refines", "BOOT-014", "BOOT-003"),
    ("refines", "BOOT-015", "BOOT-003"),
    ("refines", "BOOT-016", "BOOT-002"),
    ("refines", "BOOT-017", "BOOT-002"),
    ("refines", "BOOT-017", "BOOT-003"),
    ("refines", "BOOT-018", "BOOT-003"),
    ("refines", "BOOT-019", "BOOT-001"),
    ("refines", "BOOT-020", "BOOT-002"),
    ("refines", "BOOT-100", "BOOT-010"),
    ("refines", "BOOT-101", "BOOT-011"),
    ("refines", "BOOT-102", "BOOT-011"),
    ("refines", "BOOT-103", "BOOT-011"),
    ("refines", "BOOT-104", "BOOT-012"),
    ("refines", "BOOT-105", "BOOT-012"),
    ("refines", "BOOT-106", "BOOT-012"),
    ("refines", "BOOT-107", "BOOT-013"),
    ("refines", "BOOT-108", "BOOT-013"),
    ("refines", "BOOT-109", "BOOT-013"),
    ("refines", "BOOT-110", "BOOT-013"),
    ("refines", "BOOT-110", "BOOT-017"),
    ("refines", "BOOT-111", "BOOT-014"),
    ("refines", "BOOT-112", "BOOT-014"),
    ("refines", "BOOT-113", "BOOT-014"),
    ("refines", "BOOT-113", "BOOT-017"),
    ("refines", "BOOT-114", "BOOT-014"),
    ("refines", "BOOT-115", "BOOT-015"),
    ("refines", "BOOT-116", "BOOT-015"),
    ("refines", "BOOT-117", "BOOT-016"),
    ("refines", "BOOT-118", "BOOT-017"),
    ("refines", "BOOT-119", "BOOT-018"),
    ("refines", "BOOT-120", "BOOT-018"),
    ("refines", "BOOT-121", "BOOT-019"),
    ("refines", "BOOT-122", "BOOT-020"),
    ("refines", "BOOT-123", "BOOT-011"),
    ("refines", "BOOT-123", "BOOT-012"),
    ("refines", "BOOT-124", "BOOT-012"),
    ("refines", "BOOT-125", "BOOT-015"),
    ("refines", "BOOT-125", "BOOT-003"),
    ("refines", "BOOT-126", "BOOT-015"),
    ("refines", "BOOT-127", "BOOT-015"),
    ("refines", "BOOT-127", "BOOT-018"),
    ("refines", "BOOT-128", "BOOT-015"),
    ("constrains", "BOOT-200", "BOOT-004"),
    ("constrains", "BOOT-201", "BOOT-001"),
    ("constrains", "BOOT-202", "BOOT-002"),
    ("constrains", "BOOT-203", "BOOT-001"),
    ("constrains", "BOOT-204", "BOOT-004"),
    ("constrains", "BOOT-205", "BOOT-001"),
]

# One test-case per functional requirement (appendix A note). (fr_boot, title, sections)
TESTCASES = [
    (
        "BOOT-100",
        "Verify: init creates the layout, templates, config, and hook",
        {
            "Objective": (
                "Verify that `gregraph init` creates the repository layout, copies all "
                "built-in templates as version 1, writes the default configuration, "
                "and "
                "installs the pre-commit hook."
            ),
            "Preconditions": (
                "An empty directory that does not contain `.gregraph/`; Git is "
                "available."
            ),
            "Steps": "Run `gregraph init` in the directory.",
            "Expected result": (
                "The repository layout exists, `.gregraph/templates/` holds every "
                "built-in template at version 1, `config.toml` holds the default "
                "configuration, and the pre-commit hook is installed."
            ),
        },
    ),
    (
        "BOOT-101",
        "Verify: identifiers are derived, prefixed, and regenerated on collision",
        {
            "Objective": (
                "Verify that document creation generates a UUIDv4, derives the "
                "identifier from its first 30 bits, prefixes it, and regenerates on "
                "collision."
            ),
            "Preconditions": "An initialised repository with the configured prefix "
            "`RE`.",
            "Steps": (
                "Create several documents and inspect their sidecars; force an "
                "identifier collision with an existing document and create another."
            ),
            "Expected result": (
                "Every identifier is the configured prefix plus a 6-character "
                "Crockford "
                "base32 encoding of the UUID's first 30 bits; on collision a new UUID "
                "is "
                "generated and the check repeats."
            ),
        },
    ),
    (
        "BOOT-102",
        "Verify: identifiers are never reused",
        {
            "Objective": (
                "Verify that no identifier is ever reused, including identifiers of "
                "deprecated and superseded documents."
            ),
            "Preconditions": (
                "A repository containing a deprecated document and a superseded "
                "document."
            ),
            "Steps": (
                "Create new documents and compare their identifiers with every "
                "existing "
                "identifier, including the retired ones."
            ),
            "Expected result": "No new identifier equals any existing identifier.",
        },
    ),
    (
        "BOOT-103",
        "Verify: documents are stored as Markdown plus JSON sidecar",
        {
            "Objective": "Verify the on-disk shape of a document.",
            "Preconditions": "An initialised repository.",
            "Steps": "Create a document and list the files written for it.",
            "Expected result": (
                "Exactly one Markdown file and one JSON sidecar exist for the "
                "document, "
                "both with the identifier as filename stem."
            ),
        },
    ),
    (
        "BOOT-104",
        "Verify: cycle-creating links are refused with the cycle path",
        {
            "Objective": (
                "Verify that a link that would create a directed cycle is refused and "
                "the cycle path is printed."
            ),
            "Preconditions": (
                "A repository with document A linked `refines` to document B."
            ),
            "Steps": "Request the link `B depends-on A`.",
            "Expected result": (
                "The tool exits with code 4 and prints the cycle A through B back to A."
            ),
            "Notes": "Derived from design appendix A, BOOT-300.",
        },
    ),
    (
        "BOOT-105",
        "Verify: kind-rule violations are refused with the rule named",
        {
            "Objective": (
                "Verify that a link violating an edge type's kind rule is refused and "
                "the rule is named."
            ),
            "Preconditions": (
                "A repository with a goal document and a test-case document."
            ),
            "Steps": "Request the link `goal verifies test-case`.",
            "Expected result": (
                "The tool exits with code 4 and the refusal names the violated kind "
                "rule."
            ),
        },
    ),
    (
        "BOOT-106",
        "Verify: directed edges live on the source only",
        {
            "Objective": (
                "Verify that directed edges are stored on the source document only and "
                "inbound edges are computed from an index."
            ),
            "Preconditions": "Documents A and B with edge `A refines B`.",
            "Steps": "Inspect both sidecars and run `gregraph show B`.",
            "Expected result": (
                "The edge appears only in A's sidecar; B's sidecar contains no copy; "
                "`show B` lists the inbound edge from the index."
            ),
        },
    ),
    (
        "BOOT-107",
        "Verify: the pre-commit hook bumps staged changed documents",
        {
            "Objective": (
                "Verify that the pre-commit hook increments the version of every "
                "staged "
                "document whose body or asset hashes differ from the stored hashes and "
                "stages the rewritten sidecar."
            ),
            "Preconditions": (
                "Document A is at version 1 with an inbound link at target version 1; "
                "A's body has been edited in the working tree."
            ),
            "Steps": "Stage A's Markdown file and commit.",
            "Expected result": (
                "A's version becomes 2, the new body hash is stored, and the rewritten "
                "sidecar is staged by the hook."
            ),
            "Notes": "Derived from design appendix A, BOOT-301.",
        },
    ),
    (
        "BOOT-108",
        "Verify: the pre-commit hook blocks newly outdated links",
        {
            "Objective": (
                "Verify that a commit that would newly outdate at least one link is "
                "aborted and the exact refresh commands are listed."
            ),
            "Preconditions": (
                "The hook bump scenario: A's body is edited and staged while a link "
                "points at A at target version 1; `versioning.on_outdated_links` is "
                "`block`."
            ),
            "Steps": (
                "Commit the staged change; then run the printed `gregraph link "
                "refresh` "
                "command and commit again."
            ),
            "Expected result": (
                "The first commit is aborted and the refresh command is printed; the "
                "second commit succeeds and the link records version 2."
            ),
            "Notes": "Derived from design appendix A, BOOT-301.",
        },
    ),
    (
        "BOOT-109",
        "Verify: sync bumps versions without Git",
        {
            "Objective": (
                "Verify that without a Git repository `gregraph sync` performs the "
                "version increments the hook would perform."
            ),
            "Preconditions": (
                "A repository initialised with `--no-git`; a document whose body was "
                "edited since its last bump."
            ),
            "Steps": "Run `gregraph sync`.",
            "Expected result": (
                "The document's version is incremented by one and the stored hashes "
                "are "
                "updated, exactly as the hook would."
            ),
        },
    ),
    (
        "BOOT-110",
        "Verify: check reports the hook's findings without modifying files",
        {
            "Objective": (
                "Verify that `gregraph check` reports what the pre-commit hook would "
                "report for all working-tree changes without modifying files."
            ),
            "Preconditions": (
                "A repository with working-tree changes, including an edited document "
                "whose inbound link is now behind its version."
            ),
            "Steps": "Run `gregraph check`, then inspect the working tree.",
            "Expected result": (
                "The report lists the bumps, newly outdated links, and findings the "
                "hook "
                "would produce; no file is modified; the exit code is non-zero when "
                "the "
                "hook would block."
            ),
        },
    ),
    (
        "BOOT-111",
        "Verify: link refresh --follow follows supersession chains",
        {
            "Objective": (
                "Verify that `gregraph link refresh --follow` re-points a stale link "
                "to "
                "the end of the supersession chain, or fails if the chain forks."
            ),
            "Preconditions": (
                "One setup where A is superseded by B, which is superseded by C, with "
                "a "
                "link pointing at A; a second setup where A is superseded by both B "
                "and "
                "C."
            ),
            "Steps": (
                "Run `gregraph link refresh --follow` on the link in each setup under "
                "`--no-input`."
            ),
            "Expected result": (
                "In the chain setup the link is re-pointed to C; in the fork setup the "
                "tool fails with `E-SUPERSEDE-FORK`."
            ),
        },
    ),
    (
        "BOOT-112",
        "Verify: supersede accepts multiple targets",
        {
            "Objective": (
                "Verify that multi-target supersession creates one document with one "
                "`supersedes` edge per target."
            ),
            "Preconditions": "Documents A and B of the same kind.",
            "Steps": 'Run `gregraph supersede A B --title "Replacement"`.',
            "Expected result": (
                "One new document is created carrying one `supersedes` edge per "
                "target; "
                "A and B both become superseded."
            ),
        },
    ),
    (
        "BOOT-113",
        "Verify: documents are validated against their pinned template version",
        {
            "Objective": (
                "Verify that each document is validated against the template version "
                "pinned in its sidecar."
            ),
            "Preconditions": (
                "A document pinned to `requirement-ears` version 1, and a "
                "`requirement-ears` version 2 that adds a required section."
            ),
            "Steps": "Run `gregraph validate`.",
            "Expected result": (
                "Only the pinned version's sections are enforced for the document; the "
                "extra version 2 section is not required of it."
            ),
        },
    ),
    (
        "BOOT-114",
        "Verify: deprecated template versions warn per document",
        {
            "Objective": (
                "Verify that `gregraph validate` warns for every document pinned to a "
                "deprecated template version."
            ),
            "Preconditions": (
                "A template version marked deprecated with at least one document "
                "pinned "
                "to it."
            ),
            "Steps": "Run `gregraph validate`.",
            "Expected result": (
                "`W-TEMPLATE-DEPRECATED` is reported once per pinned document."
            ),
        },
    ),
    (
        "BOOT-115",
        "Verify: modification after decision warns",
        {
            "Objective": (
                "Verify that a change request whose version exceeds the version "
                "recorded by its last non-open decision warns as modified after "
                "decision."
            ),
            "Preconditions": (
                "An accepted change request that has been modified after its "
                "acceptance."
            ),
            "Steps": "Run `gregraph validate`, then `gregraph cr reaffirm` and "
            "validate again.",
            "Expected result": (
                "`W-CR-MODIFIED-AFTER-DECISION` is reported until `gregraph cr "
                "reaffirm` "
                "is run."
            ),
            "Notes": "Derived from design appendix A, BOOT-302.",
        },
    ),
    (
        "BOOT-116",
        "Verify: scope entries record base versions",
        {
            "Objective": (
                "Verify that adding a scope entry records the target's baseline-branch "
                "version as base version, changed only through `gregraph cr reanalyze`."
            ),
            "Preconditions": (
                "A change request; target X at version 2 on the baseline branch."
            ),
            "Steps": (
                "Add X to the change request's scope; let X advance to version 3 on "
                "the "
                "baseline branch; run `gregraph cr reanalyze`; attempt to change the "
                "base version any other way."
            ),
            "Expected result": (
                "The base version is 2 when the entry is added, becomes 3 only after "
                "`cr reanalyze`, and no other command changes it."
            ),
            "Notes": "Derived from design appendix A, BOOT-302.",
        },
    ),
    (
        "BOOT-117",
        "Verify: glossary terms are slug-identified with usage reports",
        {
            "Objective": (
                "Verify that glossary terms are managed as slug-identified Markdown "
                "files outside the graph and that usage is reported."
            ),
            "Preconditions": "An initialised repository.",
            "Steps": (
                "Add the term `Traceability` with an alias; run `gregraph term usage` "
                "for its slug."
            ),
            "Expected result": (
                "The term is stored as a slug-named Markdown file under `glossary/`; "
                "usage lists every document that mentions the term."
            ),
        },
    ),
    (
        "BOOT-118",
        "Verify: validate --strict fails on any warning or error",
        {
            "Objective": (
                "Verify that `gregraph validate --strict` exits non-zero if any "
                "warning "
                "or error is found."
            ),
            "Preconditions": (
                "A repository that reports at least one warning and no errors."
            ),
            "Steps": "Run `gregraph validate` and then `gregraph validate --strict`.",
            "Expected result": ("The first run exits 0; the second exits non-zero."),
        },
    ),
    (
        "BOOT-119",
        "Verify: status reports WIP, drafts, and unbumped modifications",
        {
            "Objective": (
                "Verify that `gregraph status` reports the WIP state and lists drafts "
                "and unbumped modifications."
            ),
            "Preconditions": (
                "A repository containing one draft document and one document with "
                "unbumped modifications."
            ),
            "Steps": "Run `gregraph status`.",
            "Expected result": (
                "The header reports `WIP: yes` and the draft and modified documents "
                "are "
                "listed."
            ),
        },
    ),
    (
        "BOOT-120",
        "Verify: draft and active are derived from the baseline branch",
        {
            "Objective": (
                "Verify that `draft` and `active` statuses are derived by comparing "
                "with the configured baseline branch and that `unknown` is reported "
                "without Git."
            ),
            "Preconditions": (
                "A Git repository whose baseline branch contains one document; a "
                "second document exists only in the working tree or on a side branch."
            ),
            "Steps": (
                "Run `gregraph status` on the branch, then in a copy without the "
                "`.git` "
                "directory."
            ),
            "Expected result": (
                "The merged document reports `active` and the other `draft`; without "
                "Git both report `unknown`."
            ),
        },
    ),
    (
        "BOOT-121",
        "Verify: graph emits a styled Mermaid flowchart",
        {
            "Objective": (
                "Verify that `gregraph graph` emits a Mermaid flowchart with node "
                "shapes "
                "by kind and edge styles by type."
            ),
            "Preconditions": (
                "A repository with documents of several kinds linked by several edge "
                "types."
            ),
            "Steps": "Run `gregraph graph`.",
            "Expected result": (
                "The output is a fenced Mermaid flowchart whose node shapes follow the "
                "kinds and whose edge styles follow the edge types."
            ),
        },
    ),
    (
        "BOOT-122",
        "Verify: asset changes count as content changes",
        {
            "Objective": (
                "Verify that a document's asset list and hashes are recomputed on "
                "reconcile and that any asset change is treated as a content change."
            ),
            "Preconditions": (
                "A document referencing an asset under its `assets/<ID>/` folder."
            ),
            "Steps": "Modify the asset's bytes and commit the change.",
            "Expected result": (
                "The hook bumps the document's version and stores the new asset hash."
            ),
        },
    ),
    (
        "BOOT-123",
        "Verify: missing arguments prompt or fail under --no-input",
        {
            "Objective": (
                "Verify that a missing required argument prompts with a filtered "
                "picker "
                "on a terminal and fails under `--no-input`."
            ),
            "Preconditions": (
                "One run with stdin as a terminal and one run with `--no-input`; both "
                "omit a required argument."
            ),
            "Steps": "Run `gregraph new` without a type or title in both setups.",
            "Expected result": (
                "The interactive run shows a filtered picker; the `--no-input` run "
                "fails as a usage error."
            ),
        },
    ),
    (
        "BOOT-124",
        "Verify: unlinked identifier mentions warn",
        {
            "Objective": (
                "Verify that a body mention of an identifier with no edge in either "
                "direction produces a warning."
            ),
            "Preconditions": (
                "A document whose body mentions another document's identifier; no edge "
                "connects them."
            ),
            "Steps": "Run `gregraph validate`.",
            "Expected result": (
                "`W-MENTION-UNLINKED` is reported for the mentioning document."
            ),
        },
    ),
    (
        "BOOT-125",
        "Verify: scope drift warns while a change request is open or accepted",
        {
            "Objective": (
                "Verify that drift is warned about while a change request's effective "
                "status is `open` or `accepted`."
            ),
            "Preconditions": (
                "An accepted change request on a side branch with scope entry X at "
                "base "
                "version 2; another branch changes X and is merged into the baseline "
                "branch."
            ),
            "Steps": "Run `gregraph validate` on the change request's branch.",
            "Expected result": (
                "`W-CR-BASE-DRIFT` is reported for X while the effective status is "
                "accepted."
            ),
            "Notes": "Derived from design appendix A, BOOT-302.",
        },
    ),
    (
        "BOOT-126",
        "Verify: origin_cr and introduces are recorded with --cr",
        {
            "Objective": (
                "Verify that `--cr` records the change request in the new document's "
                "`origin_cr` and adds the document's ID to the change request's "
                "`introduces` list."
            ),
            "Preconditions": "An open change request.",
            "Steps": (
                "Create a document with `--cr` naming the change request and inspect "
                "both sidecars."
            ),
            "Expected result": (
                "The new document's `origin_cr` names the change request and the "
                "change "
                "request's `introduces` lists the new document's identifier."
            ),
        },
    ),
    (
        "BOOT-127",
        "Verify: effective change request status comes from the baseline branch",
        {
            "Objective": (
                "Verify that the effective status is derived from the change request's "
                "sidecar on the baseline branch and the working-tree status is shown "
                "as "
                "proposed when the two differ."
            ),
            "Preconditions": (
                "A change request whose working-tree sidecar records a newer status "
                "than the sidecar on the baseline branch."
            ),
            "Steps": "Run `gregraph cr list --pending` and `gregraph status`.",
            "Expected result": (
                "The effective status is read from the baseline branch and the "
                "working-tree status is shown as proposed."
            ),
        },
    ),
    (
        "BOOT-128",
        "Verify: the hook ignores drift and CR scope changes",
        {
            "Objective": (
                "Verify that the pre-commit hook does not abort a commit because of "
                "drift or because documents in a change request's scope changed."
            ),
            "Preconditions": (
                "An accepted change request whose scope contains X; drift findings for "
                "the change request exist."
            ),
            "Steps": "Edit X and commit the change on the change request's branch.",
            "Expected result": (
                "The hook output contains no finding about the change request and the "
                "commit is not aborted because of it."
            ),
            "Notes": "Derived from design appendix A, BOOT-303.",
        },
    ),
]
