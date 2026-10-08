"""Tests for the glossary subsystem (spec §10, §13.20, §14 term codes).

Test-first (appendix C): slug derivation table, ``term add`` (files, B.3
sidecar, shipped ``term`` template, refusals), the ``E-TERM-SLUG`` and
``E-TERM-ALIAS-CLASH`` validation rules including the alias-clash matrix,
usage matching (word boundaries, case, names + aliases over document bodies),
the ``term rename`` round-trip (files + sidecar rewritten, body mentions listed
but never rewritten) and ``term list``/``show``/``deprecate``.
"""

from __future__ import annotations

import datetime as dt
import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from gregraph.core.git import GitAdapter
from gregraph.core.hashing import body_hash
from gregraph.core.models import (
    Deprecation,
    Document,
    Finding,
    Identity,
    OperationRefused,
    TemplateRef,
    Term,
)
from gregraph.core.operations import (
    TermAddResult,
    TermDeprecateResult,
    TermInfo,
    TermListResult,
    TermMention,
    TermRenameResult,
    TermUsageResult,
    derive_term_slug,
    term_add,
    term_deprecate,
    term_list,
    term_rename,
    term_show,
    term_usage,
)
from gregraph.core.storage import (
    read_body,
    read_sidecar,
    term_paths,
    write_body,
    write_sidecar,
)
from gregraph.core.validation import CODE_SEVERITIES, validate_workspace
from gregraph.core.workspace import Workspace

CREATED = dt.datetime(2026, 9, 10, 14, 2, 11, tzinfo=dt.UTC)
GLOSSARY = Path("glossary")
BUILTIN_TERM_TEMPLATE = (
    Path(__file__).resolve().parents[2] / "gregraph" / "builtin_templates" / "term"
)

S14_CODES: dict[str, str] = {
    "E-TERM-SLUG": "E",
    "E-TERM-ALIAS-CLASH": "E",
}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def install_term_template(root: Path) -> None:
    """Copy the shipped ``term`` template (appendix B.2) into the repository."""
    shutil.copytree(BUILTIN_TERM_TEMPLATE, root / ".gregraph" / "templates" / "term")


def write_term(
    root: Path,
    slug: str,
    term: str | None = None,
    *,
    aliases: Sequence[str] = (),
    stem: str | None = None,
    body: str | None = None,
    deprecated: bool = False,
) -> None:
    """Write one ``glossary/<stem>.md`` + ``.json`` pair directly."""
    name = slug.replace("-", " ").title() if term is None else term
    file_stem = slug if stem is None else stem
    text = (
        body
        if body is not None
        else f"# {name}\n\n## Definition\n\nDefined.\n\n## Notes\n\n"
    )
    model = Term(
        schema=1,
        term=name,
        slug=slug,
        aliases=list(aliases),
        created=CREATED,
        created_by=None,
        template=TemplateRef(name="term", version=1),
        version=1,
        body_hash=body_hash(text),
        deprecated=(
            Deprecation(at=CREATED, by=None, reason="obsolete") if deprecated else None
        ),
    )
    write_body(root / GLOSSARY / f"{file_stem}.md", text)
    write_sidecar(root / GLOSSARY / f"{file_stem}.json", model)


def write_doc(root: Path, body: str, doc_id: str = "RE-AAAAAA") -> None:
    directory = root / "documents" / "user-stories"
    directory.mkdir(parents=True, exist_ok=True)
    document = Document(
        schema=1,
        uuid=uuid5(NAMESPACE_URL, f"gregraph:test:{doc_id}"),
        id=doc_id,
        type="user-story",
        title="Sample",
        created=CREATED,
        created_by=None,
        template=TemplateRef(name="user-story", version=1),
        version=1,
        body_hash=body_hash(body),
        assets=[],
        links=[],
        deprecated=None,
        tags=[],
        extra={},
    )
    write_body(directory / f"{doc_id}.md", body)
    write_sidecar(directory / f"{doc_id}.json", document)


def findings_with(findings: Sequence[Finding], code: str) -> list[Finding]:
    return [finding for finding in findings if finding.code == code]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env={**os.environ, "LC_ALL": "C"},
        capture_output=True,
        check=True,
        text=True,
    )


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Git repository on ``main`` with the spec §3 layout and one init commit.

    Status of a term resolves ``draft``/``active`` only with a baseline branch
    present locally (spec §8) — ``tmp_repo`` alone stays ``unknown``.
    """
    root = tmp_path
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.name", "Test Author")
    _git(root, "config", "user.email", "test.author@example.org")
    (root / ".gregraph").mkdir()
    (root / ".gregraph" / "config.toml").write_text(
        "# gregraph configuration (spec §5.3, appendix B.1)\n", encoding="utf-8"
    )
    (root / ".gregraph" / "templates").mkdir()
    for name in ("documents", "changes", "glossary", "assets"):
        (root / name).mkdir()
    (root / ".gitignore").write_text(".gregraph/cache/\n", encoding="utf-8")
    _commit_all(root, "init")
    return root


# --------------------------------------------------------------------------
# slug derivation (spec §10.2)
# --------------------------------------------------------------------------


class TestDeriveSlug:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Knowledge base", "knowledge-base"),
            ("knowledge base", "knowledge-base"),
            ("  Trimmed  Name  ", "trimmed-name"),
            ("HTTP/2", "http-2"),
            ("C++", "c"),
            ("snake_case", "snake-case"),
            ("multi---hyphens", "multi-hyphens"),
            ("-+leading/trailing+-", "leading-trailing"),
            ("2-factor auth", "2-factor-auth"),
            ("100%", "100"),
            ("E-mail", "e-mail"),
            ("ÜBER", "über"),
            ("a", "a"),
        ],
    )
    def test_slug_derivation_table(self, name: str, expected: str) -> None:
        assert derive_term_slug(name) == expected

    def test_slug_derivation_normalises_composed_forms(self) -> None:
        # NFC so "é" slugs identically on every platform (macOS stores NFD)
        assert derive_term_slug("e\u0301clair") == "\u00e9clair"

    def test_symbol_only_name_derives_empty(self) -> None:
        assert derive_term_slug("!!!") == ""


# --------------------------------------------------------------------------
# term add (spec §13.20, §10.2)
# --------------------------------------------------------------------------


class TestTermAdd:
    def test_add_creates_body_and_sidecar(self, tmp_repo: Path) -> None:
        install_term_template(tmp_repo)
        ws = Workspace.open(tmp_repo)
        result = term_add(ws, term="Knowledge base", aliases=["KB"])
        assert isinstance(result, TermAddResult)
        assert result.slug == "knowledge-base"
        assert result.term == "Knowledge base"
        assert result.aliases == ("KB",)
        assert result.body == GLOSSARY / "knowledge-base.md"
        assert result.sidecar == GLOSSARY / "knowledge-base.json"
        assert result.template == TemplateRef(name="term", version=1)

        body_abs, sidecar_abs = term_paths(tmp_repo, "knowledge-base")
        assert body_abs.is_file() and sidecar_abs.is_file()
        sidecar = read_sidecar(sidecar_abs, Term)
        assert sidecar.schema_ == 1
        assert sidecar.term == "Knowledge base"
        assert sidecar.slug == "knowledge-base"
        assert sidecar.aliases == ["KB"]
        assert sidecar.created.tzinfo is not None
        assert sidecar.created.microsecond == 0
        assert sidecar.template == TemplateRef(name="term", version=1)
        assert sidecar.version == 1
        assert sidecar.deprecated is None
        text = read_body(body_abs)
        assert sidecar.body_hash == body_hash(text)

    def test_add_renders_term_template_body(self, tmp_repo: Path) -> None:
        install_term_template(tmp_repo)
        ws = Workspace.open(tmp_repo)
        term_add(ws, term="Knowledge base")
        text = read_body(tmp_repo / GLOSSARY / "knowledge-base.md")
        assert text.startswith("# Knowledge base\n")
        assert "## Definition" in text
        assert "## Notes" in text

    def test_add_derives_slug(self, tmp_repo: Path) -> None:
        install_term_template(tmp_repo)
        ws = Workspace.open(tmp_repo)
        result = term_add(ws, term="  HTTP/2  ")
        assert result.slug == "http-2"
        assert result.term == "HTTP/2"
        assert (tmp_repo / GLOSSARY / "http-2.md").is_file()

    def test_add_stores_aliases_in_order(self, tmp_repo: Path) -> None:
        install_term_template(tmp_repo)
        ws = Workspace.open(tmp_repo)
        result = term_add(ws, term="Knowledge base", aliases=["KB", "k-base"])
        assert result.aliases == ("KB", "k-base")
        sidecar = read_sidecar(tmp_repo / GLOSSARY / "knowledge-base.json", Term)
        assert sidecar.aliases == ["KB", "k-base"]

    def test_add_records_created_by(self, tmp_repo: Path, identity: object) -> None:
        install_term_template(tmp_repo)
        ws = Workspace.open(tmp_repo, git=GitAdapter(tmp_repo))
        result = term_add(ws, term="Knowledge base")
        assert result.findings == ()
        sidecar = read_sidecar(tmp_repo / GLOSSARY / "knowledge-base.json", Term)
        assert sidecar.created_by == Identity(
            name="Test Author", email="test.author@example.org"
        )

    def test_add_warns_without_git_identity(self, tmp_repo: Path) -> None:
        install_term_template(tmp_repo)
        ws = Workspace.open(tmp_repo)
        result = term_add(ws, term="Knowledge base")
        [warning] = findings_with(result.findings, "W-NO-GIT-IDENTITY")
        assert warning.severity == "W"
        sidecar = read_sidecar(tmp_repo / GLOSSARY / "knowledge-base.json", Term)
        assert sidecar.created_by is None

    def test_add_slug_collision_refused(self, tmp_repo: Path) -> None:
        install_term_template(tmp_repo)
        ws = Workspace.open(tmp_repo)
        term_add(ws, term="Knowledge base")
        for name in ("knowledge base", "KNOWLEDGE BASE", "Knowledge-base"):
            with pytest.raises(OperationRefused) as excinfo:
                term_add(ws, term=name)
            assert excinfo.value.finding.code == "E-TERM-SLUG"
        assert [p.name for p in sorted((tmp_repo / GLOSSARY).iterdir())] == [
            "knowledge-base.json",
            "knowledge-base.md",
        ]

    def test_add_missing_template_refused(self, tmp_repo: Path) -> None:
        ws = Workspace.open(tmp_repo)
        with pytest.raises(OperationRefused) as excinfo:
            term_add(ws, term="Knowledge base")
        assert excinfo.value.finding.code == "E-TEMPLATE-UNKNOWN"

    @pytest.mark.parametrize("blank", ["", "   ", "!!!", "-+-"])
    def test_add_blank_or_unslugable_name_raises_value_error(
        self, tmp_repo: Path, blank: str
    ) -> None:
        install_term_template(tmp_repo)
        ws = Workspace.open(tmp_repo)
        with pytest.raises(ValueError):
            term_add(ws, term=blank)

    @pytest.mark.parametrize("blank", ["", "  "])
    def test_add_blank_alias_raises_value_error(
        self, tmp_repo: Path, blank: str
    ) -> None:
        install_term_template(tmp_repo)
        ws = Workspace.open(tmp_repo)
        with pytest.raises(ValueError):
            term_add(ws, term="Knowledge base", aliases=[blank])

    @pytest.mark.parametrize(
        "aliases",
        [
            ["KB", "kb"],
            ["Knowledge base"],
            ["knowledge base"],
        ],
    )
    def test_add_self_clashing_aliases_refused(
        self, tmp_repo: Path, aliases: list[str]
    ) -> None:
        install_term_template(tmp_repo)
        ws = Workspace.open(tmp_repo)
        with pytest.raises(OperationRefused) as excinfo:
            term_add(ws, term="Knowledge base", aliases=aliases)
        assert excinfo.value.finding.code == "E-TERM-ALIAS-CLASH"
        assert not (tmp_repo / GLOSSARY / "knowledge-base.md").exists()

    def test_add_alias_clash_with_existing_refused(self, tmp_repo: Path) -> None:
        install_term_template(tmp_repo)
        ws = Workspace.open(tmp_repo)
        term_add(ws, term="Knowledge base", aliases=["KB"])
        for name, aliases in (
            ("Other term", ["kb"]),
            ("Other term", ["Knowledge Base"]),
            ("kb", []),
            ("k-b", ["KB"]),
        ):
            with pytest.raises(OperationRefused) as excinfo:
                term_add(ws, term=name, aliases=aliases)
            assert excinfo.value.finding.code == "E-TERM-ALIAS-CLASH"

    def test_add_non_clashing_names_and_aliases_accepted(self, tmp_repo: Path) -> None:
        install_term_template(tmp_repo)
        ws = Workspace.open(tmp_repo)
        term_add(ws, term="Knowledge base", aliases=["KB"])
        # alias vs slug is not a clash; name vs name is not a clash
        result = term_add(ws, term="Knowledge basis", aliases=["knowledge-base"])
        assert result.slug == "knowledge-basis"

    def test_add_reloads_workspace(self, tmp_repo: Path) -> None:
        install_term_template(tmp_repo)
        ws = Workspace.open(tmp_repo)
        term_add(ws, term="Knowledge base")
        assert "knowledge-base" in ws.index.terms


# --------------------------------------------------------------------------
# E-TERM-SLUG (spec §10.2, §14)
# --------------------------------------------------------------------------


class TestSlugIdentityValidation:
    def test_consistent_term_is_silent(self, tmp_repo: Path) -> None:
        write_term(tmp_repo, "knowledge-base", "Knowledge base")
        findings = validate_workspace(Workspace.open(tmp_repo))
        assert findings_with(findings, "E-TERM-SLUG") == []
        assert findings_with(findings, "E-TERM-ALIAS-CLASH") == []

    def test_slug_filename_mismatch(self, tmp_repo: Path) -> None:
        write_term(tmp_repo, "knowledge-base", "Knowledge base", stem="other")
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-TERM-SLUG")
        assert item.severity == "E"
        assert item.subject == GLOSSARY / "other.json"
        assert "knowledge-base" in item.message

    def test_h1_must_equal_term(self, tmp_repo: Path) -> None:
        write_term(
            tmp_repo,
            "knowledge-base",
            "Knowledge base",
            body="# Knowledge Base\n\n## Definition\n\nX.\n\n## Notes\n\n",
        )
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-TERM-SLUG")
        assert item.subject == GLOSSARY / "knowledge-base.md"
        assert "Knowledge base" in item.message

    def test_missing_h1_reported_as_term_slug(self, tmp_repo: Path) -> None:
        write_term(
            tmp_repo,
            "knowledge-base",
            "Knowledge base",
            body="No heading at all.\n",
        )
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-TERM-SLUG")
        assert item.subject == GLOSSARY / "knowledge-base.md"

    def test_slug_uniqueness_is_case_insensitive(self, tmp_repo: Path) -> None:
        write_term(tmp_repo, "KB", "KB", stem="KB")
        write_term(tmp_repo, "kb", "kb", stem="kb")
        findings = validate_workspace(Workspace.open(tmp_repo))
        items = findings_with(findings, "E-TERM-SLUG")
        assert {item.subject for item in items} == {
            GLOSSARY / "KB.json",
            GLOSSARY / "kb.json",
        }

    def test_distinct_slugs_are_unique(self, tmp_repo: Path) -> None:
        write_term(tmp_repo, "knowledge-base", "Knowledge base")
        write_term(tmp_repo, "project-wiki", "Project wiki")
        findings = validate_workspace(Workspace.open(tmp_repo))
        assert findings_with(findings, "E-TERM-SLUG") == []


# --------------------------------------------------------------------------
# E-TERM-ALIAS-CLASH matrix (spec §10.2, §14)
# --------------------------------------------------------------------------


class TestAliasClashValidation:
    def test_alias_vs_other_term_name(self, tmp_repo: Path) -> None:
        write_term(tmp_repo, "knowledge-base", "Knowledge base")
        write_term(tmp_repo, "project-wiki", "Project wiki", aliases=["Knowledge Base"])
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-TERM-ALIAS-CLASH")
        assert item.subject == GLOSSARY / "project-wiki.json"
        assert "Knowledge Base" in item.message
        assert "knowledge-base" in item.message

    def test_alias_vs_other_alias_reports_both(self, tmp_repo: Path) -> None:
        write_term(tmp_repo, "knowledge-base", "Knowledge base", aliases=["KB"])
        write_term(tmp_repo, "project-wiki", "Project wiki", aliases=["kb"])
        findings = validate_workspace(Workspace.open(tmp_repo))
        items = findings_with(findings, "E-TERM-ALIAS-CLASH")
        assert {item.subject for item in items} == {
            GLOSSARY / "knowledge-base.json",
            GLOSSARY / "project-wiki.json",
        }

    def test_alias_vs_own_term_name(self, tmp_repo: Path) -> None:
        write_term(
            tmp_repo, "knowledge-base", "Knowledge base", aliases=["knowledge base"]
        )
        findings = validate_workspace(Workspace.open(tmp_repo))
        [item] = findings_with(findings, "E-TERM-ALIAS-CLASH")
        assert item.subject == GLOSSARY / "knowledge-base.json"

    def test_duplicate_aliases_within_one_term(self, tmp_repo: Path) -> None:
        write_term(tmp_repo, "knowledge-base", "Knowledge base", aliases=["KB", "kb"])
        findings = validate_workspace(Workspace.open(tmp_repo))
        items = findings_with(findings, "E-TERM-ALIAS-CLASH")
        assert len(items) == 2
        assert {item.subject for item in items} == {GLOSSARY / "knowledge-base.json"}

    def test_clash_is_case_insensitive(self, tmp_repo: Path) -> None:
        write_term(tmp_repo, "knowledge-base", "Knowledge base", aliases=["KB"])
        write_term(tmp_repo, "project-wiki", "Project wiki", aliases=["Kb"])
        findings = validate_workspace(Workspace.open(tmp_repo))
        assert len(findings_with(findings, "E-TERM-ALIAS-CLASH")) == 2

    def test_clean_matrix_rows_are_silent(self, tmp_repo: Path) -> None:
        # negative rows: name vs name, alias vs slug, distinct aliases
        write_term(tmp_repo, "knowledge-base", "Same Name", aliases=["KB"])
        write_term(
            tmp_repo, "project-wiki", "Same Name", aliases=["knowledge-base", "k"]
        )
        findings = validate_workspace(Workspace.open(tmp_repo))
        assert findings_with(findings, "E-TERM-ALIAS-CLASH") == []

    def test_clash_with_third_party_name(self, tmp_repo: Path) -> None:
        # alias A vs name B: one finding on A's owner even with three terms
        write_term(tmp_repo, "alpha", "Alpha")
        write_term(tmp_repo, "beta", "Beta", aliases=["alpha"])
        write_term(tmp_repo, "gamma", "Gamma", aliases=["alpha"])
        findings = validate_workspace(Workspace.open(tmp_repo))
        items = findings_with(findings, "E-TERM-ALIAS-CLASH")
        assert {item.subject for item in items} == {
            GLOSSARY / "beta.json",
            GLOSSARY / "gamma.json",
        }


# --------------------------------------------------------------------------
# usage matching (spec §10.2, §13.20)
# --------------------------------------------------------------------------


class TestTermUsage:
    @pytest.mark.parametrize(
        ("text", "matched"),
        [
            ("The knowledge base is used.", ("Knowledge base",)),
            ("See Knowledge Base for details.", ("Knowledge base",)),
            ("KNOWLEDGE BASE", ("Knowledge base",)),
            ("A knowledge-base is different prose.", ()),
            ("The knowledge base's age.", ("Knowledge base",)),
            ("knowledge baseness is not the term.", ()),
            ("Here KB is used.", ("KB",)),
            ("kb in lower case.", ("KB",)),
            ("KBs are plural.", ()),
            ("KB47 is a model.", ()),
            ("KB's", ("KB",)),
            ("Nothing here.", ()),
        ],
    )
    def test_word_boundary_and_case_matching(
        self, tmp_repo: Path, text: str, matched: tuple[str, ...]
    ) -> None:
        write_term(tmp_repo, "knowledge-base", "Knowledge base", aliases=["KB"])
        write_doc(tmp_repo, f"# Sample\n\n{text}\n")
        result = term_usage(Workspace.open(tmp_repo), "knowledge-base")
        assert isinstance(result, TermUsageResult)
        assert result.names == ("Knowledge base", "KB")
        expected = (
            (
                TermMention(
                    id="RE-AAAAAA",
                    path=Path("documents/user-stories/RE-AAAAAA.md"),
                    matched=matched,
                ),
            )
            if matched
            else ()
        )
        assert result.mentions == expected

    def test_usage_lists_documents_sorted_with_matches(self, tmp_repo: Path) -> None:
        write_term(tmp_repo, "knowledge-base", "Knowledge base", aliases=["KB"])
        write_doc(tmp_repo, "# A\n\nUses KB and the knowledge base.\n", "RE-AAAAAA")
        write_doc(tmp_repo, "# B\n\nUses only KB.\n", "RE-BBBBBB")
        write_doc(tmp_repo, "# C\n\nUses neither.\n", "RE-CCCCCC")
        result = term_usage(Workspace.open(tmp_repo), "knowledge-base")
        assert result.slug == "knowledge-base"
        assert result.term == "Knowledge base"
        assert result.mentions == (
            TermMention(
                id="RE-AAAAAA",
                path=Path("documents/user-stories/RE-AAAAAA.md"),
                matched=("Knowledge base", "KB"),
            ),
            TermMention(
                id="RE-BBBBBB",
                path=Path("documents/user-stories/RE-BBBBBB.md"),
                matched=("KB",),
            ),
        )

    def test_usage_without_documents_is_empty(self, tmp_repo: Path) -> None:
        write_term(tmp_repo, "knowledge-base", "Knowledge base")
        result = term_usage(Workspace.open(tmp_repo), "knowledge-base")
        assert result.mentions == ()

    def test_usage_resolves_slug_case_insensitively(self, tmp_repo: Path) -> None:
        write_term(tmp_repo, "knowledge-base", "Knowledge base")
        result = term_usage(Workspace.open(tmp_repo), "Knowledge-Base")
        assert result.slug == "knowledge-base"

    def test_usage_unknown_slug_refused(self, tmp_repo: Path) -> None:
        with pytest.raises(OperationRefused) as excinfo:
            term_usage(Workspace.open(tmp_repo), "no-such")
        assert excinfo.value.finding.code == "E-TERM-UNKNOWN"

    def test_usage_special_characters(self, tmp_repo: Path) -> None:
        write_term(tmp_repo, "c", "C++")
        write_doc(tmp_repo, "# Sample\n\nWritten in C++ today.\n", "RE-AAAAAA")
        write_doc(tmp_repo, "# Sample\n\nThe C++17 standard.\n", "RE-BBBBBB")
        result = term_usage(Workspace.open(tmp_repo), "c")
        assert [mention.id for mention in result.mentions] == ["RE-AAAAAA"]


# --------------------------------------------------------------------------
# term rename (spec §10.2, §13.20)
# --------------------------------------------------------------------------


class TestTermRename:
    def test_rename_round_trip(self, tmp_repo: Path) -> None:
        install_term_template(tmp_repo)
        ws = Workspace.open(tmp_repo)
        term_add(ws, term="Knowledge base", aliases=["KB"])
        write_doc(tmp_repo, "# Sample\n\nThe knowledge base and KB.\n", "RE-AAAAAA")
        write_doc(tmp_repo, "# Sample\n\nUnrelated.\n", "RE-BBBBBB")

        result = term_rename(ws, "knowledge-base", "Project wiki")
        assert isinstance(result, TermRenameResult)
        assert result.old_slug == "knowledge-base"
        assert result.slug == "project-wiki"
        assert result.old_term == "Knowledge base"
        assert result.term == "Project wiki"
        assert result.changed is True
        assert result.body == GLOSSARY / "project-wiki.md"
        assert result.sidecar == GLOSSARY / "project-wiki.json"
        assert result.mentions == (
            TermMention(
                id="RE-AAAAAA",
                path=Path("documents/user-stories/RE-AAAAAA.md"),
                matched=("Knowledge base", "KB"),
            ),
        )

        assert not (tmp_repo / GLOSSARY / "knowledge-base.md").exists()
        assert not (tmp_repo / GLOSSARY / "knowledge-base.json").exists()
        body_abs, sidecar_abs = term_paths(tmp_repo, "project-wiki")
        sidecar = read_sidecar(sidecar_abs, Term)
        assert sidecar.term == "Project wiki"
        assert sidecar.slug == "project-wiki"
        assert sidecar.aliases == ["KB"]
        text = read_body(body_abs)
        assert text.startswith("# Project wiki\n")

        # prose is human-owned: mentions are listed, never rewritten
        doc_body = read_body(tmp_repo / "documents" / "user-stories" / "RE-AAAAAA.md")
        assert "The knowledge base and KB." in doc_body

    def test_rename_leaves_body_hash_for_the_reconcile_pass(
        self, tmp_repo: Path
    ) -> None:
        # the H1 change is an effective content change (§7.3); the bump is
        # the hook/sync's job (§7.5), so rename stores the old hash on purpose
        install_term_template(tmp_repo)
        ws = Workspace.open(tmp_repo)
        term_add(ws, term="Knowledge base")
        before = read_sidecar(tmp_repo / GLOSSARY / "knowledge-base.json", Term)
        term_rename(ws, "knowledge-base", "Project wiki")
        after = read_sidecar(tmp_repo / GLOSSARY / "project-wiki.json", Term)
        assert after.body_hash == before.body_hash
        assert after.body_hash != body_hash(
            read_body(tmp_repo / GLOSSARY / "project-wiki.md")
        )
        assert after.version == before.version == 1

    def test_rename_same_slug_updates_in_place(self, tmp_repo: Path) -> None:
        install_term_template(tmp_repo)
        ws = Workspace.open(tmp_repo)
        term_add(ws, term="Knowledge base")
        result = term_rename(ws, "knowledge-base", "Knowledge Base")
        assert result.slug == result.old_slug == "knowledge-base"
        sidecar = read_sidecar(tmp_repo / GLOSSARY / "knowledge-base.json", Term)
        assert sidecar.term == "Knowledge Base"
        text = read_body(tmp_repo / GLOSSARY / "knowledge-base.md")
        assert text.startswith("# Knowledge Base\n")
        assert "knowledge-base" in ws.index.terms

    def test_rename_lists_old_alias_mentions(self, tmp_repo: Path) -> None:
        install_term_template(tmp_repo)
        ws = Workspace.open(tmp_repo)
        term_add(ws, term="Knowledge base", aliases=["KB", "k-base"])
        write_doc(tmp_repo, "# Sample\n\nOnly k-base here.\n", "RE-AAAAAA")
        result = term_rename(ws, "knowledge-base", "Project wiki")
        assert result.mentions[0].matched == ("k-base",)

    def test_rename_identical_name_is_noop(self, tmp_repo: Path) -> None:
        install_term_template(tmp_repo)
        ws = Workspace.open(tmp_repo)
        term_add(ws, term="Knowledge base")
        result = term_rename(ws, "knowledge-base", "Knowledge base")
        assert result.changed is False
        assert result.notices
        assert (tmp_repo / GLOSSARY / "knowledge-base.md").is_file()

    def test_rename_slug_collision_refused(self, tmp_repo: Path) -> None:
        install_term_template(tmp_repo)
        ws = Workspace.open(tmp_repo)
        term_add(ws, term="Knowledge base")
        term_add(ws, term="Other term")
        with pytest.raises(OperationRefused) as excinfo:
            term_rename(ws, "other-term", "Knowledge Base")
        assert excinfo.value.finding.code == "E-TERM-SLUG"
        assert (tmp_repo / GLOSSARY / "other-term.md").is_file()

    def test_rename_alias_clash_refused(self, tmp_repo: Path) -> None:
        install_term_template(tmp_repo)
        ws = Workspace.open(tmp_repo)
        term_add(ws, term="Knowledge base", aliases=["Wiki"])
        term_add(ws, term="Other term")
        with pytest.raises(OperationRefused) as excinfo:
            term_rename(ws, "other-term", "wiki")
        assert excinfo.value.finding.code == "E-TERM-ALIAS-CLASH"

        # including the renamed term's own aliases
        with pytest.raises(OperationRefused) as excinfo:
            term_rename(ws, "knowledge-base", "wiki")
        assert excinfo.value.finding.code == "E-TERM-ALIAS-CLASH"

    def test_rename_unknown_slug_refused(self, tmp_repo: Path) -> None:
        ws = Workspace.open(tmp_repo)
        with pytest.raises(OperationRefused) as excinfo:
            term_rename(ws, "no-such", "New term")
        assert excinfo.value.finding.code == "E-TERM-UNKNOWN"

    @pytest.mark.parametrize("blank", ["", "  ", "!!!"])
    def test_rename_blank_name_raises_value_error(
        self, tmp_repo: Path, blank: str
    ) -> None:
        install_term_template(tmp_repo)
        ws = Workspace.open(tmp_repo)
        term_add(ws, term="Knowledge base")
        with pytest.raises(ValueError):
            term_rename(ws, "knowledge-base", blank)

    def test_rename_keeps_repo_valid(self, tmp_repo: Path) -> None:
        install_term_template(tmp_repo)
        ws = Workspace.open(tmp_repo)
        term_add(ws, term="Knowledge base", aliases=["KB"])
        term_rename(ws, "knowledge-base", "Project wiki")
        findings = validate_workspace(Workspace.open(tmp_repo))
        assert findings_with(findings, "E-TERM-SLUG") == []
        assert findings_with(findings, "E-TERM-ALIAS-CLASH") == []


# --------------------------------------------------------------------------
# term list / show / deprecate (spec §13.20)
# --------------------------------------------------------------------------


class TestListShowDeprecate:
    def test_list_sorted_by_slug(self, tmp_repo: Path) -> None:
        write_term(tmp_repo, "project-wiki", "Project wiki")
        write_term(tmp_repo, "knowledge-base", "Knowledge base", aliases=["KB"])
        result = term_list(Workspace.open(tmp_repo))
        assert isinstance(result, TermListResult)
        assert [info.slug for info in result.terms] == [
            "knowledge-base",
            "project-wiki",
        ]
        first = result.terms[0]
        assert isinstance(first, TermInfo)
        assert first.term == "Knowledge base"
        assert first.aliases == ("KB",)
        assert first.version == 1
        assert first.deprecated is None
        assert first.body == GLOSSARY / "knowledge-base.md"
        assert first.sidecar == GLOSSARY / "knowledge-base.json"

    def test_show_fields_and_status(self, tmp_repo: Path) -> None:
        write_term(tmp_repo, "knowledge-base", "Knowledge base", aliases=["KB"])
        result = term_show(Workspace.open(tmp_repo), "knowledge-base")
        assert isinstance(result, TermInfo)
        assert result.term == "Knowledge base"
        assert result.slug == "knowledge-base"
        assert result.aliases == ("KB",)
        assert result.created == CREATED
        assert result.created_by is None
        assert result.template == TemplateRef(name="term", version=1)
        assert result.version == 1
        assert result.deprecated is None
        # degraded mode / missing baseline branch: draft/active is unknown (§8)
        assert result.status == "unknown"

    def test_show_status_draft_and_active(self, git_repo: Path) -> None:
        write_term(git_repo, "knowledge-base", "Knowledge base")
        ws = Workspace.open(git_repo, git=GitAdapter(git_repo))
        assert term_show(ws, "knowledge-base").status == "draft"
        _commit_all(git_repo, "add term")
        assert term_show(ws, "knowledge-base").status == "active"

    def test_deprecate_sets_marker(self, tmp_repo: Path) -> None:
        write_term(tmp_repo, "knowledge-base", "Knowledge base")
        ws = Workspace.open(tmp_repo)
        result = term_deprecate(ws, "knowledge-base", reason="Superseded wording")
        assert isinstance(result, TermDeprecateResult)
        assert result.changed is True
        assert result.deprecated is not None
        assert result.deprecated.reason == "Superseded wording"
        assert result.deprecated.by is None
        sidecar = read_sidecar(tmp_repo / GLOSSARY / "knowledge-base.json", Term)
        assert sidecar.deprecated is not None
        assert term_show(ws, "knowledge-base").status == "deprecated"

    def test_deprecate_twice_is_noop(self, tmp_repo: Path) -> None:
        write_term(tmp_repo, "knowledge-base", "Knowledge base")
        ws = Workspace.open(tmp_repo)
        term_deprecate(ws, "knowledge-base", reason="first")
        result = term_deprecate(ws, "knowledge-base", reason="second")
        assert result.changed is False
        assert result.notices
        sidecar = read_sidecar(tmp_repo / GLOSSARY / "knowledge-base.json", Term)
        assert sidecar.deprecated is not None
        assert sidecar.deprecated.reason == "first"

    def test_deprecated_term_still_deprecated_over_draft(self, git_repo: Path) -> None:
        write_term(git_repo, "knowledge-base", "Knowledge base", deprecated=True)
        ws = Workspace.open(git_repo, git=GitAdapter(git_repo))
        assert term_show(ws, "knowledge-base").status == "deprecated"

    @pytest.mark.parametrize(
        "call",
        [
            lambda ws: term_show(ws, "no-such"),
            lambda ws: term_deprecate(ws, "no-such", reason="r"),
        ],
    )
    def test_unknown_slug_refused(self, tmp_repo: Path, call: object) -> None:
        with pytest.raises(OperationRefused) as excinfo:
            call(Workspace.open(tmp_repo))  # type: ignore[operator]
        assert excinfo.value.finding.code == "E-TERM-UNKNOWN"


# --------------------------------------------------------------------------
# registry (spec §14)
# --------------------------------------------------------------------------


class TestRegistry:
    def test_s14_codes_are_registered(self) -> None:
        for code, severity in S14_CODES.items():
            assert CODE_SEVERITIES.get(code) == severity
