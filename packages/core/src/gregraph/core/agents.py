"""Agent scaffolding: the ``AGENTS.md`` managed block and the gregraph skill.

``init``, ``sync`` and ``repair agents`` keep two plain-text files at the
repository root (AGENT_READINESS §7): ``AGENTS.md`` — whose gregraph block
follows the ``hooks.install`` pattern of markers, append-after-content and
idempotent in-place replacement — and the wholly owned
``.agents/skills/gregraph/SKILL.md``, rewritten whenever its bytes differ
(AGENT-031–AGENT-033). Both are static string templates with no reader
(AGENT-104), written with LF line endings on every platform (AGENT-105).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

AGENTS_BLOCK_START: Final[str] = "<!-- >>> gregraph agent instructions >>> -->"
AGENTS_BLOCK_END: Final[str] = "<!-- <<< gregraph agent instructions <<< -->"
AGENTS_REL_PATH: Final[Path] = Path("AGENTS.md")
SKILL_REL_PATH: Final[Path] = Path(".agents/skills/gregraph/SKILL.md")
AGENTS_FILES: Final[tuple[Path, ...]] = (AGENTS_REL_PATH, SKILL_REL_PATH)

_AGENTS_LINES: Final[tuple[str, ...]] = (
    "<!-- >>> gregraph agent instructions >>> -->",
    "# GREGraph agent instructions",
    "",
    "This directory is a GREGraph requirements repository (managed by the `gregraph`",
    "CLI). Managed directories: `documents/`, `changes/`, `glossary/`, `assets/`.",
    "Configuration: `.gregraph/config.toml`. Templates: `.gregraph/templates/`.",
    "Everything outside your prose edits is tool-owned.",
    "",
    "## Golden rules",
    "",
    "1. Never create, rename, move, or delete document files; never hand-edit `*.json`",
    "   sidecars, `.gregraph/`, or links inside sidecars. The tool owns all structure.",
    "2. Never add YAML front matter to a `*.md` document body "
    "(`E-FRONTMATTER-FORBIDDEN`).",
    "3. For automation, always pass `--no-input --json`. Parse stdout only: with",
    "   `--json`, stdout carries exactly one canonical JSON document, and errors",
    '   (exit 2/3/4/5) arrive as `{"error": {code, exit_code, message, finding,',
    "   details}}` on stdout. Exit codes: 0 ok · 1 validation/blocked · 2 usage ·",
    "   3 environment · 4 refused · 5 internal.",
    "4. Reference other documents in prose only as `[[ID]]`, `[[ID|label]]`, or a",
    "   Markdown link to the relative `.md` path — never as a bare ID (bare ID-shaped",
    "   words are not mentions).",
    '5. Create documents with `gregraph new <type> --title "…" --no-input --json`;',
    "   then either edit the returned `md_path` file directly (see the returned",
    "   `sections` for required headings) or pass content with",
    '   `--section "<Heading>=<Content>"`. Never fill documents by editing sidecars.',
    "6. After editing document bodies, run `gregraph check` before committing; commit",
    "   through the installed pre-commit hook. Refresh suspect links with",
    "   `gregraph link refresh`.",
    "7. Before finishing a task, run `gregraph validate --strict`.",
    "",
    "## Agent entry points",
    "",
    "- Rulebook (types, kinds, edge rules, templates, CR lifecycle):",
    "  `gregraph schema --json`",
    "- Context for implementation (targets + neighbours + glossary + findings in one",
    "  call): `gregraph context <ID…> --json`",
    "- Admissible link targets: `gregraph link --candidates <SOURCE> --json`",
    "- Full operating instructions: `.agents/skills/gregraph/SKILL.md`",
    "",
    "<!-- <<< gregraph agent instructions <<< -->",
)

_SKILL_LINES: Final[tuple[str, ...]] = (
    "---",
    "name: gregraph",
    "description: Operate a GREGraph requirements repository from an agent - create, "
    "link, validate and read requirement documents with the gregraph CLI. Use when "
    "the repository contains a .gregraph/config.toml directory.",
    "---",
    "",
    "# GREGraph",
    "",
    "GREGraph manages requirements as a directed acyclic graph of Markdown documents",
    "with JSON sidecars. Humans own prose; the tool owns files, IDs, metadata, links",
    "and versions. This skill tells you how to work in such a repository.",
    "",
    "## Golden rules",
    "",
    "1. Never create, rename, move or delete document files; never hand-edit `*.json`",
    "   sidecars or anything under `.gregraph/`.",
    "2. Never add YAML front matter to a document body. The first non-blank line must",
    "   be the `# Title`.",
    "3. In automation always pass `--no-input --json` and parse stdout only. With",
    "   `--json`, stdout carries exactly one canonical JSON document; errors",
    '   (exit 2/3/4/5) are `{"error": {code, exit_code, message, finding, details}}`',
    "   on stdout; exit 1 (validate/check/hook) is the command's result document.",
    "   Exit codes: 0 ok, 1 validation/blocked, 2 usage, 3 environment, 4 refused,",
    "   5 internal.",
    "4. Refer to other documents in prose only as `[[ID]]` or `[[ID|label]]`, or as a",
    "   Markdown link to the relative `.md` path. Bare ID-shaped words are not",
    "   mentions. Mention IDs are case-sensitive uppercase.",
    "5. IDs look like `RE-7F3K2Q`: prefix plus 6 Crockford base32 characters.",
    "",
    "## Discover the rulebook (once per session)",
    "",
    "    gregraph schema --json",
    "",
    "returns the configured types (kind, folder, template), the five kinds, all nine",
    "edge types with their kind rules and mutual exclusions, the active templates",
    "with required sections, and the CR lifecycle. For one template:",
    "`gregraph template show <NAME> [--version N] --json`.",
    "",
    "## Create and edit documents",
    "",
    "File-first (preferred):",
    "",
    '    gregraph new <type> --title "..." --no-input --json',
    "",
    "The payload contains `md_path`, the rendered `body`, and `sections`",
    "(`heading`, `required`, `placeholder`, `renamed_from`). Edit `md_path` with",
    "your native file-editing tool, filling the required sections. A freshly created",
    "document is in a grace state: until its first commit, edits populate version 1",
    "instead of creating version 2 — the first commit is the first real version.",
    "",
    "CLI-first:",
    "",
    '    gregraph new <type> --title "..." \\',
    '      --section "Statement=WHEN ... THE SYSTEM SHALL ..." \\',
    '      --section-file "Rationale=rationale.md" --strict --no-input --json',
    "",
    "`edit` works the same way on an existing document",
    '(`--section`, `--section-file "Heading=path|-", --body, --body-file`,',
    "`--strict`). Unknown headings are refused with `E-SECTION-UNKNOWN` and the",
    "refusal's `details.template_sections` lists every valid heading with its",
    "placeholder — self-correct and retry, nothing was written. Required sections",
    "must be filled when `--section`/`--strict` is used (`E-SECTION-REQUIRED-EMPTY`).",
    "",
    'Body changes are "modified, unbumped" until the pre-commit hook or',
    "`gregraph sync --bump` records the version bump.",
    "",
    "## Traceability",
    "",
    "    gregraph link <SOURCE> <TYPE> <TARGET> --json",
    "    gregraph link --candidates <SOURCE> --json        # admissible targets",
    "    gregraph link refresh [--to <ID>] [--all] --json  # confirm after edits",
    "",
    "Edge types: refines, derives-from, depends-on, satisfies, verifies, constrains,",
    "supersedes, conflicts-with, relates-to — kind rules are in `schema --json`.",
    "Freshness states: fresh, outdated, stale, pending-outdated.",
    "",
    "## Read context before implementing",
    "",
    "    gregraph context <ID...> --depth 1 --json",
    "",
    "One call returns the requested documents (full bodies), their neighbours with",
    "edge type/direction/freshness, the glossary definitions used in those bodies,",
    "and any validation findings affecting the subgraph. `gregraph show <ID...>",
    "--json` (multiple IDs allowed) and `gregraph list --type <t> --body --json`",
    "are the lighter alternatives.",
    "",
    "## Change requests",
    "",
    'CRs live outside the graph in `changes/`. `cr new --title "..." --scope',
    "<TARGET>[:<modify|supersede|deprecate>]`, `cr scope add/remove`, `cr set",
    "status=...` (open → accepted/rejected → implemented, reopenable), `cr",
    "reaffirm`, `cr reanalyze`. A document created for a CR uses `new ... --cr <CR>`.",
    "",
    "## Commit lifecycle",
    "",
    "Commit through the installed pre-commit hook; it bumps versions and blocks",
    "commits that newly outdate links. Preview with `gregraph check`. After your own",
    "substantive edits run `gregraph link refresh --to <ID>`. Merge conflicts:",
    "resolve prose by hand, then `gregraph repair versions`; `gregraph repair",
    "agents` regenerates these instructions.",
    "",
    "## Troubleshooting",
    "",
    "| Exit | Meaning | Typical fix |",
    "|---|---|---|",
    "| 2 | usage error | fix the flags; the envelope's `details.usage` shows the "
    "usage line |",
    "| 3 | no repository / environment | run inside the repository (or pass `--repo`) "
    "|",
    "| 4 | refused (E-CYCLE, E-EDGE-RULE, E-SECTION-UNKNOWN, ...) | read "
    "`error.finding` and its `details`; the rulebook is in `gregraph schema --json` |",
    "| 5 | internal error | retry once; report with the envelope message |",
)


def agents_block() -> str:
    """The managed ``AGENTS.md`` block, terminated by a single newline."""
    return "\n".join(_AGENTS_LINES) + "\n"


def skill_text() -> str:
    """Full ``SKILL.md`` text: YAML frontmatter plus the skill body."""
    return "\n".join(_SKILL_LINES) + "\n"


def write_agents_md(root: Path) -> Path | None:
    """Write or update ``AGENTS.md`` under ``root``; ``None`` means unchanged.

    A missing or whitespace-only file receives the managed block alone;
    otherwise every byte of existing content is preserved and the block is
    appended after a blank line, or replaced in place when both markers are
    present in order (spec §7.1, AGENT-032). The file is written only when the
    desired UTF-8 LF bytes differ from the raw bytes on disk, which also heals
    CRLF files to LF (AGENT-105). Returns the repository-relative path.
    """
    target = root / AGENTS_REL_PATH
    existing = _read_text(target) if target.exists() else ""
    return _write_if_changed(target, _agents_md_text(existing), AGENTS_REL_PATH)


def write_skill(root: Path) -> Path | None:
    """Write ``SKILL.md`` under ``root`` wholesale; ``None`` means unchanged.

    The file is wholly owned by gregraph — no managed block, no reader: it is
    rewritten whenever its bytes differ from :func:`skill_text`, creating the
    parent directories as needed (spec §7.1). Returns the relative path.
    """
    target = root / SKILL_REL_PATH
    return _write_if_changed(target, skill_text(), SKILL_REL_PATH)


def refresh(root: Path) -> tuple[Path, ...]:
    """Refresh both agent files under ``root``, writing only the changed ones.

    Returns the repository-relative paths that were written, in the order
    :data:`AGENTS_FILES` lists them (0, 1 or 2 items).
    """
    written: list[Path] = []
    for path in (write_agents_md(root), write_skill(root)):
        if path is not None:
            written.append(path)
    return tuple(written)


def _agents_md_text(existing: str) -> str:
    """Desired ``AGENTS.md`` content given the current LF-normalised text."""
    if not existing.strip():
        return agents_block()
    start = existing.find(AGENTS_BLOCK_START)
    end = existing.find(AGENTS_BLOCK_END)
    if start != -1 and end != -1 and start < end:
        tail = existing[end + len(AGENTS_BLOCK_END) :]
        desired = existing[:start] + agents_block().rstrip("\n") + tail
        if not tail:
            desired += "\n"
        return desired
    head = existing if existing.endswith("\n") else existing + "\n"
    if not head.endswith("\n\n"):
        head += "\n"
    return head + agents_block()


def _write_if_changed(target: Path, desired: str, rel_path: Path) -> Path | None:
    """Write ``desired`` (UTF-8, LF) unless ``target`` already holds it."""
    raw = target.read_bytes() if target.exists() else None
    if raw == desired.encode("utf-8"):
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_text(target, desired)
    return rel_path


def _read_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")
