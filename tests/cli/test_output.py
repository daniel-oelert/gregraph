"""Tests for ``gregraph.cli.output`` (spec §13 output rules, §16.1).

Findings print one per line prefixed by code and subject; tables align for
``list``; JSON output is canonical (indent 2, sorted keys, trailing newline);
colours appear only when stdout is a TTY and ``NO_COLOR`` is unset — no
third-party terminal library (``\033`` codes only).
"""

from __future__ import annotations

import datetime as dt
import io
import json
from pathlib import Path
from uuid import UUID

from gregraph.cli.output import (
    Output,
    Palette,
    canonical_json,
    colour_enabled,
    document_payload,
    error_envelope,
    format_finding,
    format_table,
)
from gregraph.core.models import Document, Finding, Link, TemplateRef


class FakeTTY(io.StringIO):
    """StringIO whose ``isatty`` reports a terminal (or not)."""

    def __init__(self, tty: bool = True) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:  # noqa: D102
        return self._tty


def sample_document() -> Document:
    return Document(
        schema=1,
        uuid=UUID("00000000-0000-4000-8000-000000000001"),
        id="RE-AAAAAA",
        type="user-story",
        title="Upload from the desktop",
        created=dt.datetime(2026, 9, 10, 14, 2, 11, tzinfo=dt.UTC),
        created_by=None,
        template=TemplateRef(name="user-story", version=1),
        version=2,
        body_hash="sha256:abc",
        assets=[],
        links=[Link(type="refines", target="RE-BBBBB", target_version=1)],
        deprecated=None,
        tags=["ux"],
        extra={},
    )


# --------------------------------------------------------------------------
# colour behaviour
# --------------------------------------------------------------------------


def test_colour_enabled_when_tty_and_no_color_unset(monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert colour_enabled(FakeTTY(True)) is True


def test_colour_disabled_when_not_a_tty(monkeypatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert colour_enabled(FakeTTY(False)) is False
    assert colour_enabled(io.StringIO()) is False


def test_colour_disabled_when_no_color_set(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    assert colour_enabled(FakeTTY(True)) is False


def test_colour_disabled_when_no_color_empty(monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "")
    assert colour_enabled(FakeTTY(True)) is False


def test_plain_finding_has_code_and_subject() -> None:
    finding = Finding(
        code="E-TITLE-MISSING",
        severity="E",
        subject=Path("documents/x.md"),
        message="no H1",
    )
    assert format_finding(finding) == "E-TITLE-MISSING documents/x.md: no H1"


def test_plain_finding_id_subject_and_fix() -> None:
    finding = Finding(
        code="W-ORPHAN",
        severity="W",
        subject="RE-AAAAAA",
        message="no edges",
        fix="gregraph link",
    )
    line = format_finding(finding)
    assert line == "W-ORPHAN RE-AAAAAA: no edges (fix: gregraph link)"


def test_colour_finding_paints_severity() -> None:
    palette = Palette(enabled=True)
    error = format_finding(
        Finding(code="E-CYCLE", severity="E", subject="RE-1", message="cycle"),
        palette=palette,
    )
    warning = format_finding(
        Finding(code="W-ORPHAN", severity="W", subject="RE-2", message="orphan"),
        palette=palette,
    )
    assert "\033[31m" in error and "\033[0m" in error
    assert "\033[33m" in warning and "\033[0m" in warning
    stripped_error = error.replace("\033[31m", "").replace("\033[0m", "")
    assert stripped_error == "E-CYCLE RE-1: cycle"


def test_palette_disabled_paints_nothing() -> None:
    palette = Palette(enabled=False)
    assert palette.error("x") == "x"
    assert palette.warn("x") == "x"
    assert palette.key("x") == "x"


# --------------------------------------------------------------------------
# tables and JSON
# --------------------------------------------------------------------------


def test_table_aligns_columns() -> None:
    text = format_table(
        ["ID", "TITLE"],
        [["RE-A", "Long title here"], ["RE-BB", "x"]],
    )
    lines = text.splitlines()
    assert lines[0].startswith("ID")
    assert "TITLE" in lines[0]
    assert lines[1].startswith("RE-A")
    assert lines[2].startswith("RE-BB")
    assert lines[1].index("Long") == lines[2].index("x")


def test_canonical_json_sorted_indent_trailing_newline() -> None:
    text = canonical_json({"b": 1, "a": "ü"})
    assert text.endswith("\n")
    assert not text.endswith("\n\n")
    assert text.splitlines()[0] == "{"
    assert json.loads(text) == {"b": 1, "a": "ü"}
    assert '"a"' in text.splitlines()[1]
    assert "ü" in text


def test_document_payload_sidecar_fields_plus_status() -> None:
    payload = document_payload(sample_document(), status="active", kind="requirement")
    assert payload["schema"] == 1
    assert payload["id"] == "RE-AAAAAA"
    assert payload["status"] == "active"
    assert payload["kind"] == "requirement"
    assert payload["links"][0]["target"] == "RE-BBBBB"
    assert payload["created"] == "2026-09-10T14:02:11Z"


# --------------------------------------------------------------------------
# Output stream discipline
# --------------------------------------------------------------------------


def output_pair(**kwargs: object) -> tuple[Output, io.StringIO, io.StringIO]:
    out, err = io.StringIO(), io.StringIO()
    return Output(stdout=out, stderr=err, **kwargs), out, err  # type: ignore[arg-type]


def test_line_goes_to_stdout() -> None:
    handle, out, err = output_pair()
    handle.line("hello")
    assert out.getvalue() == "hello\n"
    assert err.getvalue() == ""


def test_error_goes_to_stderr_always() -> None:
    handle, out, err = output_pair(quiet=True)
    handle.error("bad")
    assert err.getvalue() == "error: bad\n"
    assert out.getvalue() == ""


def test_quiet_suppresses_line_warn_note() -> None:
    handle, out, err = output_pair(quiet=True)
    handle.line("a")
    handle.warn("b")
    handle.note("c")
    handle.detail("d")
    assert out.getvalue() == ""
    assert err.getvalue() == ""


def test_detail_only_when_verbose() -> None:
    handle, out, _ = output_pair(verbose=False)
    handle.detail("hidden")
    assert out.getvalue() == ""
    handle2, out2, _ = output_pair(verbose=True)
    handle2.detail("shown")
    assert out2.getvalue() == "shown\n"


def test_json_mode_suppresses_human_lines() -> None:
    handle, out, _ = output_pair(json_mode=True)
    handle.line("human noise")
    handle.json({"a": 1})
    assert out.getvalue() == canonical_json({"a": 1})


def test_report_prints_findings_to_stdout() -> None:
    handle, out, err = output_pair()
    handle.report(
        [
            Finding(code="W-ORPHAN", severity="W", subject="RE-1", message="no edges"),
            Finding(code="E-CYCLE", severity="E", subject="RE-2", message="cycle"),
        ]
    )
    lines = out.getvalue().splitlines()
    assert lines[0] == "W-ORPHAN RE-1: no edges"
    assert lines[1] == "E-CYCLE RE-2: cycle"
    assert err.getvalue() == ""


def test_finding_to_stderr_for_refusals() -> None:
    handle, out, err = output_pair()
    handle.finding(
        Finding(code="E-ID-UNKNOWN", severity="E", subject="RE-9", message="unknown")
    )
    assert err.getvalue() == "E-ID-UNKNOWN RE-9: unknown\n"
    assert out.getvalue() == ""


def test_table_output_on_stdout() -> None:
    handle, out, _ = output_pair()
    handle.table(["ID", "TITLE"], [["RE-A", "t"]])
    assert "ID" in out.getvalue()
    assert "RE-A" in out.getvalue()


def test_output_defaults_to_current_sys_streams() -> None:
    handle = Output()
    assert hasattr(handle.stdout, "write")
    assert hasattr(handle.stderr, "write")


class _FlushSpy(io.StringIO):
    """Records what had been flushed to the stream at each flush call."""

    def __init__(self) -> None:
        super().__init__()
        self.flushed = ""

    def flush(self) -> None:
        super().flush()
        self.flushed = self.getvalue()


def test_announce_survives_quiet_and_json() -> None:
    for kwargs in ({"quiet": True}, {"json_mode": True}):
        handle, out, err = output_pair(**kwargs)
        handle.announce("GREGraph UI: http://127.0.0.1:8765/")
        assert out.getvalue() == "GREGraph UI: http://127.0.0.1:8765/\n"
        assert err.getvalue() == ""


def test_announce_is_flushed_before_returning() -> None:
    spy = _FlushSpy()
    Output(stdout=spy, stderr=io.StringIO()).announce("banner")
    assert spy.flushed == "banner\n"


def test_line_still_suppressed_when_quiet_after_announce() -> None:
    handle, out, _ = output_pair(quiet=True)
    handle.line("ordinary")
    assert out.getvalue() == ""


# --------------------------------------------------------------------------
# JSON contract (AGENT_READINESS §2.1 R3/R4) and error envelopes (§2.2)
# --------------------------------------------------------------------------


def test_json_mode_suppresses_stderr_warn_note_finding() -> None:
    handle, out, err = output_pair(json_mode=True)
    handle.warn("degraded mode")
    handle.note("no git identity")
    handle.finding(
        Finding(code="E-CYCLE", severity="E", subject="RE-1", message="cycle")
    )
    assert err.getvalue() == ""
    assert out.getvalue() == ""


def test_json_writes_stdout_even_when_quiet() -> None:
    handle, out, err = output_pair(json_mode=True, quiet=True)
    handle.json({"a": 1})
    assert out.getvalue() == canonical_json({"a": 1})
    assert err.getvalue() == ""


def test_error_envelope_usage_exit_2() -> None:
    envelope = error_envelope(
        "E-USAGE",
        2,
        "unrecognised arguments",
        details={"usage": "gregraph new TYPE"},
    )
    assert envelope == {
        "error": {
            "code": "E-USAGE",
            "exit_code": 2,
            "message": "unrecognised arguments",
            "finding": None,
            "details": {"usage": "gregraph new TYPE"},
        }
    }


def test_error_envelope_environment_exit_3_defaults_empty_details() -> None:
    envelope = error_envelope("E-NO-REPOSITORY", 3, "not a gregraph repository")
    assert envelope == {
        "error": {
            "code": "E-NO-REPOSITORY",
            "exit_code": 3,
            "message": "not a gregraph repository",
            "finding": None,
            "details": {},
        }
    }


def test_error_envelope_environment_exit_3_path_details() -> None:
    envelope = error_envelope(
        "E-ENV", 3, "unreadable sidecar", details={"path": "documents/x.json"}
    )
    assert envelope["error"]["details"] == {"path": "documents/x.json"}


def test_error_envelope_refusal_exit_4_mirrors_finding_details() -> None:
    finding = Finding(
        code="E-CYCLE",
        severity="E",
        subject="RE-B",
        message="adding RE-A refines RE-B creates a cycle",
        fix="gregraph link RE-B refines RE-A",
        details={"cycle": ["RE-B", "RE-A", "RE-B"]},
    )
    envelope = error_envelope("E-CYCLE", 4, finding.message, finding=finding)
    assert envelope == {
        "error": {
            "code": "E-CYCLE",
            "exit_code": 4,
            "message": "adding RE-A refines RE-B creates a cycle",
            "finding": {
                "code": "E-CYCLE",
                "severity": "E",
                "id": "RE-B",
                "message": "adding RE-A refines RE-B creates a cycle",
                "fix": "gregraph link RE-B refines RE-A",
                "details": {"cycle": ["RE-B", "RE-A", "RE-B"]},
            },
            "details": {"cycle": ["RE-B", "RE-A", "RE-B"]},
        }
    }


def test_error_envelope_refusal_without_details_yields_empty_details() -> None:
    finding = Finding(
        code="E-ID-UNKNOWN", severity="E", subject="RE-9", message="unknown id"
    )
    envelope = error_envelope("E-ID-UNKNOWN", 4, finding.message, finding=finding)
    assert envelope["error"]["finding"] == {
        "code": "E-ID-UNKNOWN",
        "severity": "E",
        "id": "RE-9",
        "message": "unknown id",
    }
    assert envelope["error"]["details"] == {}


def test_error_envelope_explicit_details_override_finding_details() -> None:
    finding = Finding(
        code="E-X", severity="E", subject="RE-1", message="m", details={"a": 1}
    )
    envelope = error_envelope("E-X", 4, "m", finding=finding, details={"b": 2})
    assert envelope["error"]["details"] == {"b": 2}


def test_error_envelope_internal_exit_5() -> None:
    envelope = error_envelope("E-INTERNAL", 5, "unexpected failure", details={})
    assert envelope == {
        "error": {
            "code": "E-INTERNAL",
            "exit_code": 5,
            "message": "unexpected failure",
            "finding": None,
            "details": {},
        }
    }
