"""Tests for ``gregraph.core.agents`` (AGENT_READINESS §7).

Scaffolding round-trip: managed-block and skill generation, fresh and
pre-existing ``AGENTS.md``, in-place block replacement, idempotence, CRLF
healing and ``refresh``. The golden texts pin the Appendix A/B draft content
byte-for-byte (AGENT-104: static string templates in core).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from gregraph.core.agents import (
    AGENTS_BLOCK_END,
    AGENTS_BLOCK_START,
    AGENTS_FILES,
    AGENTS_REL_PATH,
    SKILL_REL_PATH,
    agents_block,
    refresh,
    skill_text,
    write_agents_md,
    write_skill,
)

AGENTS_MD = Path("AGENTS.md")
SKILL_MD = Path(".agents/skills/gregraph/SKILL.md")
CUSTOM = "# My project\n\nCustom agent notes.\n"

GOLDEN_AGENTS_LINES: Final[tuple[str, ...]] = (
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

GOLDEN_AGENTS_BLOCK: Final[str] = "\n".join(GOLDEN_AGENTS_LINES) + "\n"

GOLDEN_SKILL_LINES: Final[tuple[str, ...]] = (
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
    "5. IDs look like `RE-FEAT-7F3K2Q`: prefix, the type abbreviation, then 6",
    "   Crockford base32 characters. Change requests use `CHG` as the abbreviation.",
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

GOLDEN_SKILL: Final[str] = "\n".join(GOLDEN_SKILL_LINES) + "\n"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """Bare repository root; the writers create what they need."""
    return tmp_path


class TestConstants:
    def test_marker_values(self) -> None:
        assert AGENTS_BLOCK_START == "<!-- >>> gregraph agent instructions >>> -->"
        assert AGENTS_BLOCK_END == "<!-- <<< gregraph agent instructions <<< -->"

    def test_relative_paths(self) -> None:
        assert AGENTS_REL_PATH == AGENTS_MD
        assert SKILL_REL_PATH == SKILL_MD
        assert AGENTS_FILES == (AGENTS_MD, SKILL_MD)

    def test_paths_are_repository_relative(self) -> None:
        assert not AGENTS_REL_PATH.is_absolute()
        assert not SKILL_REL_PATH.is_absolute()


class TestAgentsBlock:
    def test_matches_appendix_a_byte_for_byte(self) -> None:
        assert agents_block() == GOLDEN_AGENTS_BLOCK

    def test_is_delimited_by_the_markers(self) -> None:
        block = agents_block()
        assert block.startswith(AGENTS_BLOCK_START + "\n")
        assert block.endswith("\n" + AGENTS_BLOCK_END + "\n")
        assert block.count(AGENTS_BLOCK_START) == 1
        assert block.count(AGENTS_BLOCK_END) == 1

    def test_states_the_repository_layout(self) -> None:
        block = agents_block()
        for needle in (
            "documents/",
            "changes/",
            "glossary/",
            "assets/",
            ".gregraph/config.toml",
            ".gregraph/templates/",
        ):
            assert needle in block

    def test_states_the_golden_rules(self) -> None:
        block = agents_block()
        assert "## Golden rules" in block
        for number in range(1, 8):
            assert f"\n{number}. " in block
        assert "--no-input --json" in block
        assert "[[ID]]" in block
        assert "never as a bare ID" in block
        assert "gregraph check" in block
        assert "gregraph validate --strict" in block

    def test_states_the_agent_entry_points(self) -> None:
        block = agents_block()
        assert "## Agent entry points" in block
        for command in (
            "gregraph schema --json",
            "gregraph context <ID…> --json",
            "gregraph link --candidates <SOURCE> --json",
        ):
            assert command in block
        assert str(SKILL_REL_PATH) in block

    def test_is_concise_and_clean(self) -> None:
        block = agents_block()
        lines = block.splitlines()
        assert len(lines) <= 60
        assert all(line == line.rstrip() for line in lines)
        assert "\r" not in block


class TestSkillText:
    def test_matches_appendix_b_byte_for_byte(self) -> None:
        assert skill_text() == GOLDEN_SKILL

    def test_has_yaml_frontmatter(self) -> None:
        text = skill_text()
        assert text.startswith("---\nname: gregraph\ndescription: ")
        assert "\n---\n\n# GREGraph\n" in text
        assert (
            "Use when the repository contains a .gregraph/config.toml directory."
            in text
        )

    def test_covers_the_workflow_in_order(self) -> None:
        text = skill_text()
        sections = (
            "## Golden rules",
            "## Discover the rulebook (once per session)",
            "## Create and edit documents",
            "## Traceability",
            "## Read context before implementing",
            "## Change requests",
            "## Commit lifecycle",
            "## Troubleshooting",
        )
        for section in sections:
            assert section in text
        positions = [text.index(section) for section in sections]
        assert positions == sorted(positions)
        for needle in (
            "E-SECTION-UNKNOWN",
            "E-SECTION-REQUIRED-EMPTY",
            "details.template_sections",
            "grace state",
            "pending-outdated",
            "gregraph sync --bump",
            "gregraph repair versions",
        ):
            assert needle in text

    def test_is_clean_text(self) -> None:
        text = skill_text()
        assert text.endswith("\n")
        assert not text.endswith("\n\n")
        assert "\r" not in text
        assert all(line == line.rstrip() for line in text.splitlines())


class TestWriteAgentsMd:
    def test_creates_agents_md(self, root: Path) -> None:
        assert write_agents_md(root) == AGENTS_MD
        target = root / AGENTS_MD
        assert target.is_file()
        assert target.read_bytes() == agents_block().encode("utf-8")

    @pytest.mark.parametrize("content", ["", " \n\t\n"])
    def test_replaces_blank_file_with_block(self, root: Path, content: str) -> None:
        (root / AGENTS_MD).write_text(content, encoding="utf-8")
        assert write_agents_md(root) == AGENTS_MD
        assert (root / AGENTS_MD).read_bytes() == agents_block().encode("utf-8")

    def test_returns_none_when_already_current(self, root: Path) -> None:
        write_agents_md(root)
        before = (root / AGENTS_MD).read_bytes()
        assert write_agents_md(root) is None
        assert (root / AGENTS_MD).read_bytes() == before

    def test_appends_after_custom_content(self, root: Path) -> None:
        (root / AGENTS_MD).write_text(CUSTOM, encoding="utf-8")
        assert write_agents_md(root) == AGENTS_MD
        text = (root / AGENTS_MD).read_text(encoding="utf-8")
        assert text == CUSTOM + "\n" + agents_block()

    def test_keeps_existing_blank_line_separator(self, root: Path) -> None:
        (root / AGENTS_MD).write_text(CUSTOM + "\n", encoding="utf-8")
        write_agents_md(root)
        text = (root / AGENTS_MD).read_text(encoding="utf-8")
        assert text == CUSTOM + "\n" + agents_block()

    def test_adds_missing_final_newline_before_block(self, root: Path) -> None:
        (root / AGENTS_MD).write_text("no trailing newline", encoding="utf-8")
        write_agents_md(root)
        text = (root / AGENTS_MD).read_text(encoding="utf-8")
        assert text == "no trailing newline\n\n" + agents_block()

    def test_replaces_stale_block_in_place(self, root: Path) -> None:
        stale = agents_block().replace("## Golden rules", "## Old rules")
        (root / AGENTS_MD).write_text("HEAD\n\n" + stale + "\nTAIL\n", encoding="utf-8")
        assert write_agents_md(root) == AGENTS_MD
        text = (root / AGENTS_MD).read_text(encoding="utf-8")
        # The blank line between block and TAIL belongs to the surrounding
        # content and is preserved (spec §7.1: content after is untouched).
        assert text == "HEAD\n\n" + agents_block() + "\nTAIL\n"
        assert text.count(AGENTS_BLOCK_START) == 1
        assert "## Old rules" not in text
        assert "TAIL" in text

    def test_file_ending_at_block_gets_one_trailing_newline(self, root: Path) -> None:
        stale = (
            agents_block()
            .rstrip("\n")
            .replace("## Agent entry points", "## Entry points")
        )
        (root / AGENTS_MD).write_text("HEAD\n\n" + stale, encoding="utf-8")
        assert write_agents_md(root) == AGENTS_MD
        text = (root / AGENTS_MD).read_text(encoding="utf-8")
        assert text == "HEAD\n\n" + agents_block()

    def test_orphan_start_marker_is_not_treated_as_block(self, root: Path) -> None:
        (root / AGENTS_MD).write_text(
            CUSTOM + AGENTS_BLOCK_START + "\n", encoding="utf-8"
        )
        write_agents_md(root)
        text = (root / AGENTS_MD).read_text(encoding="utf-8")
        assert text.count(AGENTS_BLOCK_START) == 2
        assert text.count(AGENTS_BLOCK_END) == 1
        assert text.endswith(agents_block())

    def test_orphan_end_marker_is_not_treated_as_block(self, root: Path) -> None:
        (root / AGENTS_MD).write_text(
            CUSTOM + AGENTS_BLOCK_END + "\n", encoding="utf-8"
        )
        write_agents_md(root)
        text = (root / AGENTS_MD).read_text(encoding="utf-8")
        assert text.count(AGENTS_BLOCK_START) == 1
        assert text.endswith(agents_block())

    def test_heals_edited_block(self, root: Path) -> None:
        write_agents_md(root)
        target = root / AGENTS_MD
        target.write_text(
            target.read_text(encoding="utf-8").replace(
                "## Golden rules", "## Golden rules (edited)"
            ),
            encoding="utf-8",
        )
        assert write_agents_md(root) == AGENTS_MD
        assert target.read_text(encoding="utf-8") == agents_block()

    def test_replacement_is_idempotent(self, root: Path) -> None:
        stale = agents_block().replace("## Golden rules", "## Old rules")
        (root / AGENTS_MD).write_text("HEAD\n\n" + stale + "\nTAIL\n", encoding="utf-8")
        write_agents_md(root)
        data = (root / AGENTS_MD).read_bytes()
        assert write_agents_md(root) is None
        assert (root / AGENTS_MD).read_bytes() == data

    def test_heals_crlf_to_lf(self, root: Path) -> None:
        data = agents_block().replace("\n", "\r\n").encode("utf-8")
        (root / AGENTS_MD).write_bytes(data)
        assert write_agents_md(root) == AGENTS_MD
        assert (root / AGENTS_MD).read_bytes() == agents_block().encode("utf-8")
        assert b"\r" not in (root / AGENTS_MD).read_bytes()

    def test_normalises_crlf_around_custom_content(self, root: Path) -> None:
        crlf_custom = "line one\r\nline two\r\n"
        block = agents_block().replace("\n", "\r\n").encode("utf-8")
        (root / AGENTS_MD).write_bytes(crlf_custom.encode("utf-8") + block)
        assert write_agents_md(root) == AGENTS_MD
        text = (root / AGENTS_MD).read_text(encoding="utf-8")
        assert text == crlf_custom.replace("\r\n", "\n") + agents_block()
        assert "\r" not in text


class TestWriteSkill:
    def test_creates_skill_file_with_parents(self, root: Path) -> None:
        assert write_skill(root) == SKILL_MD
        target = root / SKILL_MD
        assert target.is_file()
        assert (root / ".agents" / "skills" / "gregraph").is_dir()
        assert target.read_bytes() == skill_text().encode("utf-8")

    def test_returns_none_when_already_current(self, root: Path) -> None:
        write_skill(root)
        before = (root / SKILL_MD).read_bytes()
        assert write_skill(root) is None
        assert (root / SKILL_MD).read_bytes() == before

    def test_rewrites_drifted_file_wholesale(self, root: Path) -> None:
        target = root / SKILL_MD
        target.parent.mkdir(parents=True)
        target.write_text("stale skill\n", encoding="utf-8")
        assert write_skill(root) == SKILL_MD
        assert target.read_bytes() == skill_text().encode("utf-8")

    def test_heals_crlf_to_lf(self, root: Path) -> None:
        target = root / SKILL_MD
        target.parent.mkdir(parents=True)
        target.write_bytes(skill_text().replace("\n", "\r\n").encode("utf-8"))
        assert write_skill(root) == SKILL_MD
        written = (root / SKILL_MD).read_bytes()
        assert written == skill_text().encode("utf-8")
        assert b"\r" not in written


class TestRefresh:
    def test_fresh_root_writes_both_files(self, root: Path) -> None:
        assert refresh(root) == (AGENTS_MD, SKILL_MD)
        assert (root / AGENTS_MD).read_bytes() == agents_block().encode("utf-8")
        assert (root / SKILL_MD).read_bytes() == skill_text().encode("utf-8")

    def test_second_run_writes_nothing(self, root: Path) -> None:
        refresh(root)
        assert refresh(root) == ()

    def test_reports_only_changed_files(self, root: Path) -> None:
        refresh(root)
        (root / SKILL_MD).write_text("drifted\n", encoding="utf-8")
        assert refresh(root) == (SKILL_MD,)
        assert refresh(root) == ()

    def test_preserves_custom_agents_md_and_converges(self, root: Path) -> None:
        (root / AGENTS_MD).write_text(CUSTOM, encoding="utf-8")
        assert refresh(root) == (AGENTS_MD, SKILL_MD)
        text = (root / AGENTS_MD).read_text(encoding="utf-8")
        assert text.startswith(CUSTOM)
        assert text.count(AGENTS_BLOCK_START) == 1
        assert text.count(AGENTS_BLOCK_END) == 1
        assert refresh(root) == ()
