"""Tests for ``gregraph deprecate`` / ``gregraph undeprecate`` (spec §13.15, §8).

Flag-driven and interactive paths: deprecation sets the one stored status flag
with a reason and lists stale inbound links; ``undeprecate`` clears it. Usage
errors and refusals exit 2/4 (spec §16.2). CLI tests invoke
``gregraph.cli.main.main([...])`` with the ``tmp_repo`` fixture.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from test_hook import install_templates, link, write_doc

from gregraph.cli.main import main
from gregraph.core.config import Config, write_config
from gregraph.core.models import Document
from gregraph.core.storage import config_path, read_sidecar


class FakeTTY(io.StringIO):
    """Scripted stdin that reports itself as a terminal."""

    def isatty(self) -> bool:  # noqa: D102
        return True


@pytest.fixture
def repo(tmp_repo: Path) -> Path:
    install_templates(tmp_repo)
    write_config(config_path(tmp_repo), Config())
    return tmp_repo


def read_doc(root: Path, doc_id: str) -> Document:
    return read_sidecar(next((root / "documents").rglob(f"{doc_id}.json")), Document)


def chain(root: Path) -> tuple[str, str]:
    """``source → target``: deprecating ``target`` leaves one stale inbound link."""
    target = write_doc(root, "feature", "Upload documents")
    source = write_doc(root, "user-story", "Scan uploads", [link("depends-on", target)])
    return source, target


def test_deprecate_sets_flag_and_lists_stale_inbound(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source, target = chain(repo)
    assert (
        main(
            [
                "--repo",
                str(repo),
                "deprecate",
                target,
                "--reason",
                "obsolete",
                "--no-input",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert f"deprecated {target}" in captured.out
    assert "stale inbound links (review before removing or re-pointing):" in (
        captured.out
    )
    assert f"{source}  depends-on  {target}  target_version 1" in captured.out
    model = read_doc(repo, target)
    assert model.deprecated is not None
    assert model.deprecated.reason == "obsolete"


def test_deprecate_without_inbound_links_prints_no_stale_section(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = write_doc(repo, "feature", "Upload documents")
    assert (
        main(
            [
                "--repo",
                str(repo),
                "deprecate",
                target,
                "--reason",
                "obsolete",
                "--no-input",
            ]
        )
        == 0
    )
    captured = capsys.readouterr().out
    assert f"deprecated {target}" in captured
    assert "stale inbound links" not in captured


def test_deprecate_twice_is_noop_notice(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, target = chain(repo)
    argv = [
        "--repo",
        str(repo),
        "deprecate",
        target,
        "--reason",
        "obsolete",
        "--no-input",
    ]
    assert main(argv) == 0
    capsys.readouterr()
    assert main(argv) == 0
    captured = capsys.readouterr()
    assert f"{target} is already deprecated" in captured.err
    assert f"deprecated {target}" not in captured.out


def test_undeprecate_clears_flag(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, target = chain(repo)
    assert (
        main(
            [
                "--repo",
                str(repo),
                "deprecate",
                target,
                "--reason",
                "obsolete",
                "--no-input",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert main(["--repo", str(repo), "undeprecate", target, "--no-input"]) == 0
    assert f"undeprecated {target}" in capsys.readouterr().out
    assert read_doc(repo, target).deprecated is None


def test_undeprecate_not_deprecated_is_noop_notice(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = write_doc(repo, "feature", "Upload documents")
    assert main(["--repo", str(repo), "undeprecate", target, "--no-input"]) == 0
    captured = capsys.readouterr()
    assert f"{target} is not deprecated" in captured.err
    assert f"undeprecated {target}" not in captured.out


def test_deprecate_missing_id_is_usage_error(repo: Path) -> None:
    assert (
        main(["--repo", str(repo), "deprecate", "--reason", "obsolete", "--no-input"])
        == 2
    )


def test_deprecate_missing_reason_is_usage_error(repo: Path) -> None:
    target = write_doc(repo, "feature", "Upload documents")
    assert main(["--repo", str(repo), "deprecate", target, "--no-input"]) == 2


def test_undeprecate_missing_id_is_usage_error(repo: Path) -> None:
    assert main(["--repo", str(repo), "undeprecate", "--no-input"]) == 2


def test_deprecate_unknown_id_is_refused(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(
            [
                "--repo",
                str(repo),
                "deprecate",
                "RE-NOSUCH",
                "--reason",
                "x",
                "--no-input",
            ]
        )
        == 4
    )
    assert "E-ID-UNKNOWN" in capsys.readouterr().err


def test_deprecate_interactive_picks_document_and_reason(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, target = chain(repo)
    monkeypatch.setattr("sys.stdin", FakeTTY(f"{target}\nobsolete reason\n"))
    assert main(["--repo", str(repo), "deprecate"]) == 0
    assert f"deprecated {target}" in capsys.readouterr().out
    assert read_doc(repo, target).deprecated is not None


def test_deprecate_interactive_cancel_is_usage_error(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chain(repo)
    monkeypatch.setattr("sys.stdin", FakeTTY("q\n"))
    assert main(["--repo", str(repo), "deprecate"]) == 2


def test_deprecate_interactive_reason_end_of_input_is_usage_error(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, target = chain(repo)
    monkeypatch.setattr("sys.stdin", FakeTTY(f"{target}\n"))
    assert main(["--repo", str(repo), "deprecate"]) == 2


def test_undeprecate_interactive_picks_document(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, target = chain(repo)
    assert (
        main(
            [
                "--repo",
                str(repo),
                "deprecate",
                target,
                "--reason",
                "obsolete",
                "--no-input",
            ]
        )
        == 0
    )
    capsys.readouterr()
    monkeypatch.setattr("sys.stdin", FakeTTY(f"{target}\n"))
    assert main(["--repo", str(repo), "undeprecate"]) == 0
    assert f"undeprecated {target}" in capsys.readouterr().out
