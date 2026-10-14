"""argparse tree and exit-code mapping (spec §13, §16.1).

One subparser per §13 command; global options (``--repo``, ``--no-input``,
``--json``, ``-q``, ``-v``, ``--version``) work before or after the command.
Exit codes (spec §13): ``0`` success, ``1`` validation errors or blocked,
``2`` usage error, ``3`` no repository found / environment error, ``4``
operation refused (the refusal finding is printed), ``5`` internal error.

Command-module contract: ``gregraph.cli.commands.<module>`` exposes
``run(args: argparse.Namespace, app: App) -> int``. Modules that later
subtasks own (S18/S19) are not present yet; dispatching to a missing module
reports "not implemented" (exit 5). ``gregraph link refresh`` is routed to
``gregraph.cli.commands.refresh`` (spec §13.5); ``gregraph undeprecate``
serves from ``gregraph.cli.commands.deprecate`` (spec §13.15).
``--help``/``--version`` exit via ``SystemExit`` as argparse does (S0
contract, tests/test_scaffold.py); every other outcome is an ``int`` return.
"""

from __future__ import annotations

import argparse
import importlib
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import NoReturn

from pydantic import ValidationError

from gregraph import __version__
from gregraph.cli import webui
from gregraph.cli.output import Output
from gregraph.core.config import read_config
from gregraph.core.git import GitAdapter, NoteSuppressor, NullGitAdapter
from gregraph.core.models import OperationRefused
from gregraph.core.storage import config_path
from gregraph.core.workspace import Workspace, find_root

EXIT_OK = 0
EXIT_VALIDATION = 1
EXIT_USAGE = 2
EXIT_ENV = 3
EXIT_REFUSED = 4
EXIT_INTERNAL = 5

#: command key → module providing ``run(args, app)`` (spec §16.1 layout).
_COMMAND_MODULES: dict[str, str] = {
    "init": "gregraph.cli.commands.init",
    "new": "gregraph.cli.commands.new",
    "link": "gregraph.cli.commands.link",
    "link-refresh": "gregraph.cli.commands.refresh",
    "unlink": "gregraph.cli.commands.unlink",
    "set": "gregraph.cli.commands.set",
    "sync": "gregraph.cli.commands.sync",
    "check": "gregraph.cli.commands.check",
    "validate": "gregraph.cli.commands.validate",
    "list": "gregraph.cli.commands.list",
    "show": "gregraph.cli.commands.show",
    "edit": "gregraph.cli.commands.edit",
    "status": "gregraph.cli.commands.status",
    "graph": "gregraph.cli.commands.graph",
    "supersede": "gregraph.cli.commands.supersede",
    "deprecate": "gregraph.cli.commands.deprecate",
    "undeprecate": "gregraph.cli.commands.deprecate",
    "migrate": "gregraph.cli.commands.migrate",
    "template": "gregraph.cli.commands.template",
    "cr": "gregraph.cli.commands.cr",
    "repair": "gregraph.cli.commands.repair",
    "term": "gregraph.cli.commands.term",
    "baseline": "gregraph.cli.commands.baseline",
    "hooks": "gregraph.cli.commands.hooks",
    "hook": "gregraph.cli.commands.hook",
    "serve": "gregraph.cli.commands.serve",
}


class UsageError(Exception):
    """Bad or missing command-line input — exit code 2 (spec §13)."""

    def __init__(self, message: str, *, usage: str | None = None) -> None:
        super().__init__(message)
        self.usage = usage


class _Parser(argparse.ArgumentParser):
    """``ArgumentParser`` whose usage errors raise :class:`UsageError`."""

    def error(self, message: str) -> NoReturn:
        raise UsageError(message, usage=self.format_usage())


@dataclass
class App:
    """Per-invocation context handed to every command module."""

    out: Output
    repo: Path | None = None
    no_input: bool = False
    notes: NoteSuppressor = field(default_factory=NoteSuppressor)

    @property
    def interactive(self) -> bool:
        """Prompts only on a TTY and without ``--no-input``."""
        return not self.no_input and _stdin_isatty()

    def open_workspace(self) -> Workspace:
        """Open the repository: ``--repo`` is the root, else discover.

        Raises ``FileNotFoundError`` when there is no repository — mapped to
        exit code 3 by :func:`main`.
        """
        if self.repo is not None:
            base = self.repo.resolve()
            root = find_root(base)
            if root is None or root != base:
                raise FileNotFoundError(
                    f"not a gregraph repository (no .gregraph/config.toml): {base}"
                )
        else:
            base = Path.cwd()
            root = find_root(base)
            if root is None:
                raise FileNotFoundError(
                    "no gregraph repository (no .gregraph/config.toml) "
                    f"at or above {base}"
                )
        config = read_config(config_path(root))
        probe = GitAdapter(root)
        if probe.is_repo():
            return Workspace(root=root, config=config, git=probe)
        return Workspace(root=root, config=config, git=NullGitAdapter())

    def note(self, feature: str) -> None:
        """Degraded-mode note, at most once per invocation."""
        message = self.notes.take(feature)
        if message is not None:
            self.out.note(message.removeprefix("note: "))


def _stdin_isatty() -> bool:
    isatty = getattr(sys.stdin, "isatty", None)
    return bool(isatty()) if callable(isatty) else False


# --------------------------------------------------------------------------
# parser tree
# --------------------------------------------------------------------------


def _global_parent() -> _Parser:
    """Global options (spec §13), suppressed defaults so either position wins."""
    parent = _Parser(add_help=False)
    parent.add_argument(
        "--repo",
        metavar="PATH",
        default=argparse.SUPPRESS,
        help="repository root (default: discovered from the current directory)",
    )
    parent.add_argument(
        "--no-input",
        action="store_true",
        default=argparse.SUPPRESS,
        help="never prompt; missing required inputs are usage errors",
    )
    parent.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="machine-readable output for list/show/status/validate/check/graph",
    )
    parent.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        default=argparse.SUPPRESS,
        help="suppress non-essential output",
    )
    parent.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=argparse.SUPPRESS,
        help="extra detail",
    )
    return parent


def _add_command(
    subparsers: argparse._SubParsersAction[_Parser],
    parents: list[_Parser],
    name: str,
    help_text: str,
    *,
    hidden: bool = False,
) -> _Parser:
    command = subparsers.add_parser(name, parents=parents, help=help_text)
    if hidden:
        for pseudo in list(subparsers._choices_actions):
            if pseudo.dest == name:
                subparsers._choices_actions.remove(pseudo)
    return command


def _loopback_host(text: str) -> str:
    """``--host`` values: loopback only, no remote serving (spec §21.3)."""
    if text not in webui.LOOPBACK_HOSTS:
        allowed = ", ".join(webui.LOOPBACK_HOSTS)
        raise argparse.ArgumentTypeError(
            f"host must be one of {allowed} (remote serving is not supported)"
        )
    return text


def _port_number(text: str) -> int:
    """``--port`` values: integers 1..65535 (spec §21.3)."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "port must be an integer from 1 to 65535"
        ) from None
    if not 1 <= value <= 65535:
        raise argparse.ArgumentTypeError("port must be an integer from 1 to 65535")
    return value


def _add_serve(
    subparsers: argparse._SubParsersAction[_Parser], parents: list[_Parser]
) -> None:
    """``serve`` exists only when gregraph-webui is installed (spec §21.2–21.3)."""
    serve = _add_command(
        subparsers, parents, "serve", "serve the optional local web UI"
    )
    serve.add_argument(
        "--host",
        type=_loopback_host,
        default=webui.DEFAULT_HOST,
        metavar="HOST",
        help="loopback address: 127.0.0.1, localhost or ::1 (default: 127.0.0.1)",
    )
    serve.add_argument(
        "--port",
        type=_port_number,
        default=webui.DEFAULT_PORT,
        metavar="PORT",
        help="TCP port, 1-65535 (default: 8765)",
    )


def build_parser() -> argparse.ArgumentParser:
    parents = [_global_parent()]
    parser = _Parser(
        prog="gregraph",
        description="Local, Git-aware requirements management",
        parents=parents,
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", metavar="command")

    init = _add_command(subparsers, parents, "init", "create a requirements repository")
    init.add_argument("path", nargs="?", default=".", help="directory to initialise")
    init.add_argument("--prefix", default="RE", metavar="RE", help="document ID prefix")
    init.add_argument(
        "--baseline-branch",
        default="main",
        metavar="BRANCH",
        help="baseline branch name",
    )
    init.add_argument(
        "--templates",
        choices=["all", "minimal"],
        default="all",
        help="built-in templates to copy",
    )
    init.add_argument(
        "--no-git", action="store_true", help="skip git init and hook installation"
    )

    new = _add_command(subparsers, parents, "new", "create a document")
    new.add_argument("type", nargs="?", default=None, help="document type")
    new.add_argument(
        "--title", default=None, metavar="T", help="document title (the H1)"
    )
    new.add_argument(
        "--template", default=None, metavar="NAME", help="template name override"
    )
    new.add_argument(
        "--template-version",
        type=int,
        default=None,
        metavar="N",
        help="pin this template version",
    )
    new.add_argument(
        "--allow-deprecated",
        action="store_true",
        help="allow a deprecated template version",
    )
    new.add_argument(
        "--tag",
        action="append",
        default=[],
        metavar="TAG",
        help="add a tag (repeatable)",
    )
    new.add_argument(
        "--link",
        action="append",
        default=[],
        metavar="TYPE:TARGET",
        help="initial link (repeatable)",
    )
    new.add_argument(
        "--cr", default=None, metavar="CR", help="record as introduced by this CR"
    )
    new.add_argument(
        "--edit", action="store_true", help="open the document in $VISUAL/$EDITOR"
    )

    link = _add_command(subparsers, parents, "link", "add an edge")
    link.add_argument("source", nargs="?", default=None, help="source document ID")
    link.add_argument("type", nargs="?", default=None, help="edge type")
    link.add_argument("target", nargs="?", default=None, help="target document ID")
    link.epilog = (
        "edge guidelines:\n"
        '- Ask "if the target were deleted, would the source still make sense '
        'as written?" If no and the source is a more concrete version of the '
        "target -> refines. If no and the source is a different requirement "
        "caused by it -> derives-from. If yes but the source cannot be built "
        "first -> depends-on.\n"
        "- Never model quality attributes as children. Use constrains.\n"
        "- A design node never refines a requirement; it satisfies it.\n"
        "- A verification node only ever verifies.\n"
        "- relates-to is the last resort.\n"
        "\n"
        "see `gregraph link refresh --help` for refreshing link versions "
    )
    link.formatter_class = argparse.RawDescriptionHelpFormatter

    refresh = _add_command(
        subparsers, parents, "link-refresh", "link refresh", hidden=True
    )
    refresh.add_argument("source", nargs="?", default=None, help="source document ID")
    refresh.add_argument("type", nargs="?", default=None, help="edge type")
    refresh.add_argument("target", nargs="?", default=None, help="target document ID")
    refresh.add_argument(
        "--from",
        dest="from_id",
        default=None,
        metavar="ID",
        help="all outbound links of ID",
    )
    refresh.add_argument(
        "--to", dest="to_id", default=None, metavar="ID", help="all inbound links of ID"
    )
    refresh.add_argument("--all", action="store_true", help="every link")
    refresh.add_argument(
        "--follow", action="store_true", help="re-point stale links to successors"
    )
    refresh.add_argument("--dry-run", action="store_true", help="report only")

    unlink = _add_command(subparsers, parents, "unlink", "remove an edge")
    unlink.add_argument("source", nargs="?", default=None, help="source document ID")
    unlink.add_argument("type", nargs="?", default=None, help="edge type")
    unlink.add_argument("target", nargs="?", default=None, help="target document ID")

    set_command = _add_command(subparsers, parents, "set", "set tags or extra fields")
    set_command.add_argument("id", nargs="?", default=None, help="document ID")
    set_command.add_argument(
        "assignments",
        nargs="*",
        default=[],
        metavar="key=value",
        help="tags=…/tags+=…/tags-=…/extra.name=…",
    )

    sync = _add_command(subparsers, parents, "sync", "reconcile all")
    sync.add_argument(
        "--bump", action="store_true", help="bump versions of modified documents"
    )

    _add_command(subparsers, parents, "check", "simulate the pre-commit hook")

    validate = _add_command(subparsers, parents, "validate", "run validation")
    validate.add_argument(
        "--strict", action="store_true", help="treat warnings as errors"
    )
    validate.add_argument(
        "--only-errors", action="store_true", help="report errors only"
    )

    list_command = _add_command(subparsers, parents, "list", "list documents")
    list_command.add_argument(
        "--type",
        action="append",
        default=[],
        metavar="T",
        help="filter by type (repeatable)",
    )
    list_command.add_argument(
        "--kind",
        action="append",
        default=[],
        metavar="K",
        help="filter by kind (repeatable)",
    )
    list_command.add_argument(
        "--status",
        action="append",
        default=[],
        metavar="S",
        help="filter by status (repeatable)",
    )
    list_command.add_argument(
        "--tag",
        action="append",
        default=[],
        metavar="t",
        help="filter by tag (repeatable)",
    )
    list_command.add_argument(
        "--roots", action="store_true", help="root documents only"
    )
    list_command.add_argument(
        "--orphans", action="store_true", help="orphan documents only"
    )
    list_command.add_argument(
        "--outdated", action="store_true", help="documents with outdated outbound links"
    )
    list_command.add_argument(
        "--stale", action="store_true", help="documents with stale outbound links"
    )
    list_command.add_argument(
        "--deprecated-templates",
        action="store_true",
        help="documents pinned to deprecated template versions",
    )
    list_command.add_argument(
        "--sort",
        choices=["id", "title", "created", "version"],
        default="id",
        help="sort key",
    )

    show = _add_command(subparsers, parents, "show", "show one document")
    show.add_argument("id", nargs="?", default=None, help="document (or CR) ID")
    show.add_argument(
        "--body", action="store_true", help="also print the Markdown body"
    )
    show.add_argument(
        "--depth",
        type=int,
        default=None,
        metavar="N",
        help="downstream tree depth limit",
    )

    edit = _add_command(
        subparsers,
        parents,
        "edit",
        "open the Markdown in $VISUAL/$EDITOR",
    )
    edit.add_argument("id", nargs="?", default=None, help="document ID")

    _add_command(subparsers, parents, "status", "repository status")

    graph = _add_command(subparsers, parents, "graph", "export a Mermaid graph")
    graph.add_argument(
        "--root",
        action="append",
        default=[],
        metavar="ID",
        help="root of the exported scope (repeatable)",
    )
    graph.add_argument(
        "--depth",
        type=int,
        default=None,
        metavar="N",
        help="depth limit from the roots",
    )
    graph.add_argument(
        "--types", default=None, metavar="t,…", help="comma-separated type filter"
    )
    graph.add_argument(
        "--edges", default=None, metavar="e,…", help="comma-separated edge-type filter"
    )
    graph.add_argument(
        "--include-superseded",
        action="store_true",
        help="include superseded/deprecated nodes",
    )
    graph.add_argument(
        "--direction", choices=["TD", "LR"], default="TD", help="flowchart direction"
    )
    graph.add_argument(
        "-o",
        dest="output",
        default=None,
        metavar="FILE",
        help="write to FILE instead of stdout",
    )

    supersede = _add_command(subparsers, parents, "supersede", "replace documents")
    supersede.add_argument(
        "old", nargs="*", default=[], metavar="OLD", help="document(s) to supersede"
    )
    supersede.add_argument(
        "--title", default=None, metavar="T", help="title of the new document"
    )
    supersede.add_argument(
        "--type", default=None, metavar="TYPE", help="type of the new document"
    )
    supersede.add_argument(
        "--copy-body",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="copy the old body",
    )
    supersede.add_argument(
        "--copy-links",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="copy outbound links",
    )
    supersede.add_argument(
        "--cr", default=None, metavar="CR", help="record as introduced by this CR"
    )
    supersede.add_argument(
        "--edit", action="store_true", help="open the new document in $VISUAL/$EDITOR"
    )

    deprecate = _add_command(subparsers, parents, "deprecate", "deprecate a document")
    deprecate.add_argument("id", nargs="?", default=None, help="document ID")
    deprecate.add_argument(
        "--reason", default=None, metavar="R", help="deprecation reason"
    )

    undeprecate = _add_command(subparsers, parents, "undeprecate", "undo a deprecation")
    undeprecate.add_argument("id", nargs="?", default=None, help="document ID")

    migrate = _add_command(subparsers, parents, "migrate", "migrate template versions")
    migrate.add_argument(
        "ids", nargs="*", default=[], metavar="ID", help="documents to migrate"
    )
    migrate.add_argument("--all", action="store_true", help="every pinned document")
    migrate.add_argument(
        "--template",
        default=None,
        metavar="NAME",
        help="documents pinned to this template",
    )
    migrate.add_argument(
        "--to",
        dest="to_version",
        type=int,
        default=None,
        metavar="VERSION",
        help="target template version",
    )
    migrate.add_argument(
        "--supersede", action="store_true", help="force superseding migration"
    )
    migrate.add_argument("--dry-run", action="store_true", help="print the plan only")

    template = _add_command(subparsers, parents, "template", "manage templates")
    template_cmds = template.add_subparsers(dest="template_cmd", metavar="subcommand")
    template_cmds.add_parser("list", parents=parents, help="list template versions")
    template_add = template_cmds.add_parser(
        "add", parents=parents, help="copy a built-in template in"
    )
    template_add.add_argument(
        "builtin", metavar="BUILTIN", help="built-in template name"
    )
    template_bump = template_cmds.add_parser(
        "bump", parents=parents, help="copy the latest version forward"
    )
    template_bump.add_argument("name", metavar="NAME", help="template name")
    template_bump.add_argument(
        "--breaking", action="store_true", help="mark the new version as breaking"
    )
    template_show = template_cmds.add_parser(
        "show", parents=parents, help="show a template version"
    )
    template_show.add_argument("name", metavar="NAME", help="template name")
    template_show.add_argument(
        "--version", type=int, default=None, metavar="N", help="version to show"
    )

    cr = _add_command(subparsers, parents, "cr", "change requests")
    cr_cmds = cr.add_subparsers(dest="cr_cmd", metavar="subcommand")
    cr_new = cr_cmds.add_parser("new", parents=parents, help="create a change request")
    cr_new.add_argument("--title", default=None, metavar="T", help="CR title")
    cr_new.add_argument(
        "--scope",
        action="append",
        default=[],
        metavar="TARGET[:INTENT]",
        help="scope entry (repeatable)",
    )
    cr_new.add_argument(
        "--external-ref", default=None, metavar="R", help="external reference"
    )
    cr_new.add_argument(
        "--edit", action="store_true", help="open the CR in $VISUAL/$EDITOR"
    )
    cr_scope = cr_cmds.add_parser("scope", parents=parents, help="edit CR scope")
    scope_cmds = cr_scope.add_subparsers(dest="scope_cmd", metavar="subcommand")
    scope_add = scope_cmds.add_parser("add", parents=parents, help="add a scope entry")
    scope_add.add_argument("cr", metavar="CR", help="change request ID")
    scope_add.add_argument("target", metavar="TARGET", help="document ID")
    scope_add.add_argument(
        "--intent",
        choices=["modify", "supersede", "deprecate"],
        default="modify",
        help="scope intent",
    )
    scope_remove = scope_cmds.add_parser(
        "remove", parents=parents, help="remove a scope entry"
    )
    scope_remove.add_argument("cr", metavar="CR", help="change request ID")
    scope_remove.add_argument("target", metavar="TARGET", help="document ID")
    cr_set = cr_cmds.add_parser("set", parents=parents, help="set CR fields")
    cr_set.add_argument("cr", metavar="CR", help="change request ID")
    cr_set.add_argument(
        "assignments",
        nargs="*",
        default=[],
        metavar="key=value",
        help="status=…/branch=…/external_ref=…/tags…/extra.…",
    )
    cr_reaffirm = cr_cmds.add_parser(
        "reaffirm", parents=parents, help="reaffirm decisions"
    )
    cr_reaffirm.add_argument("cr", metavar="CR", help="change request ID")
    cr_reanalyze = cr_cmds.add_parser(
        "reanalyze", parents=parents, help="re-analyse scope targets"
    )
    cr_reanalyze.add_argument("cr", metavar="CR", help="change request ID")
    cr_reanalyze.add_argument(
        "targets", nargs="*", default=[], metavar="TARGET", help="targets to re-analyse"
    )
    cr_list = cr_cmds.add_parser("list", parents=parents, help="list change requests")
    cr_list.add_argument(
        "--status", action="append", default=[], metavar="S", help="filter by status"
    )
    cr_list.add_argument(
        "--effective", action="store_true", help="filter on effective status"
    )
    cr_list.add_argument(
        "--pending", action="store_true", help="proposed status differs from effective"
    )
    cr_list.add_argument("--drift", action="store_true", help="CRs with drift")
    cr_show = cr_cmds.add_parser("show", parents=parents, help="show a change request")
    cr_show.add_argument("cr", metavar="CR", help="change request ID")

    repair = _add_command(subparsers, parents, "repair", "repair damaged data")
    repair_cmds = repair.add_subparsers(dest="repair_cmd", metavar="subcommand")
    repair_cmds.add_parser(
        "versions", parents=parents, help="recompute versions of conflicted sidecars"
    )
    repair_id = repair_cmds.add_parser(
        "regenerate-id", parents=parents, help="regenerate a colliding ID"
    )
    repair_id.add_argument("path", metavar="PATH", help="path of the document to fix")
    repair_cmds.add_parser(
        "cache", parents=parents, help="delete and rebuild the cache"
    )

    term = _add_command(subparsers, parents, "term", "glossary terms")
    term_cmds = term.add_subparsers(dest="term_cmd", metavar="subcommand")
    term_add = term_cmds.add_parser("add", parents=parents, help="add a term")
    term_add.add_argument("term", metavar="Term", help="term text")
    term_add.add_argument(
        "--alias", action="append", default=[], metavar="A", help="alias (repeatable)"
    )
    term_add.add_argument(
        "--edit", action="store_true", help="open the term body in $VISUAL/$EDITOR"
    )
    term_cmds.add_parser("list", parents=parents, help="list terms")
    term_show = term_cmds.add_parser("show", parents=parents, help="show a term")
    term_show.add_argument("slug", metavar="SLUG", help="term slug")
    term_usage = term_cmds.add_parser(
        "usage", parents=parents, help="list documents mentioning a term"
    )
    term_usage.add_argument("slug", metavar="SLUG", help="term slug")
    term_rename = term_cmds.add_parser("rename", parents=parents, help="rename a term")
    term_rename.add_argument("slug", metavar="SLUG", help="term slug")
    term_rename.add_argument("new_term", metavar="New term", help="new term text")
    term_deprecate = term_cmds.add_parser(
        "deprecate", parents=parents, help="deprecate a term"
    )
    term_deprecate.add_argument("slug", metavar="SLUG", help="term slug")
    term_deprecate.add_argument(
        "--reason", default=None, metavar="R", help="deprecation reason"
    )

    baseline = _add_command(subparsers, parents, "baseline", "baseline tags")
    baseline_cmds = baseline.add_subparsers(dest="baseline_cmd", metavar="subcommand")
    baseline_create = baseline_cmds.add_parser(
        "create", parents=parents, help="create a baseline tag"
    )
    baseline_create.add_argument("name", metavar="NAME", help="baseline name")
    baseline_create.add_argument(
        "-m", dest="message", default="", metavar="MSG", help="tag message"
    )
    baseline_cmds.add_parser("list", parents=parents, help="list baseline tags")

    hooks = _add_command(subparsers, parents, "hooks", "manage Git hooks")
    hooks_cmds = hooks.add_subparsers(dest="hooks_cmd", metavar="subcommand")
    hooks_cmds.add_parser(
        "install", parents=parents, help="install the pre-commit hook"
    )
    hooks_cmds.add_parser(
        "uninstall", parents=parents, help="remove the pre-commit hook"
    )
    hooks_cmds.add_parser(
        "status", parents=parents, help="report hook installation state"
    )

    hook = _add_command(
        subparsers,
        parents,
        "hook",
        "internal hook entry points",
        hidden=True,
    )
    hook_cmds = hook.add_subparsers(dest="hook_cmd", metavar="subcommand")
    hook_cmds.add_parser(
        "pre-commit", parents=parents, help="pre-commit hook body (internal)"
    )

    if webui.find_serve_entry_point() is not None:
        _add_serve(subparsers, parents)

    return parser


# --------------------------------------------------------------------------
# argv routing
# --------------------------------------------------------------------------


def _command_index(argv: list[str]) -> int | None:
    """Index of the command token (first non-option, skipping option values)."""
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--":
            return None
        if token == "--repo":
            index += 2
            continue
        if token.startswith("--repo="):
            index += 1
            continue
        if token in ("-h", "--help", "--version"):
            return None
        if token.startswith("-") and token != "-":
            index += 1
            continue
        return index
    return None


def _route_link_refresh(argv: list[str]) -> list[str]:
    """Route ``link refresh …`` (the §13.5 subcommand) to its own parser."""
    index = _command_index(argv)
    if (
        index is not None
        and argv[index] == "link"
        and index + 1 < len(argv)
        and argv[index + 1] == "refresh"
    ):
        return [*argv[:index], "link-refresh", *argv[index + 2 :]]
    return argv


# --------------------------------------------------------------------------
# dispatch and exit codes
# --------------------------------------------------------------------------


def _load_command(key: str) -> ModuleType:
    module_name = _COMMAND_MODULES[key]
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            label = key.replace("-", " ")
            raise NotImplementedError(
                f"`gregraph {label}` is not implemented yet"
            ) from exc
        raise


def _dispatch(args: argparse.Namespace, app: App) -> int:
    key = str(args.command)
    module = _load_command(key)
    run = getattr(module, "run", None)
    if run is None:
        label = key.replace("-", " ")
        raise NotImplementedError(f"`gregraph {label}` is not implemented yet")
    return int(run(args, app))


def _serve_install_hint(argv: list[str], out: Output) -> None:
    """Point at the optional distribution when ``serve`` was asked for but absent."""
    index = _command_index(argv)
    if index is None or argv[index] != "serve":
        return
    if webui.find_serve_entry_point() is None:
        out.note("serve needs the optional web UI: pip install gregraph-webui")


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``gregraph`` console script and ``python -m gregraph``.

    Returns the exit code; ``--help``/``--version`` raise
    ``SystemExit`` as argparse does.
    """
    raw = list(sys.argv[1:]) if argv is None else list(argv)
    parser = build_parser()
    out = Output()
    try:
        args = parser.parse_args(_route_link_refresh(raw))
    except UsageError as exc:
        if exc.usage:
            print(exc.usage, end="", file=out.stderr)
        out.error(str(exc))
        _serve_install_hint(raw, out)
        return EXIT_USAGE

    out.json_mode = bool(getattr(args, "json", False))
    out.quiet = bool(getattr(args, "quiet", False))
    out.verbose = bool(getattr(args, "verbose", False))
    app = App(
        out=out,
        repo=Path(args.repo) if getattr(args, "repo", None) else None,
        no_input=bool(getattr(args, "no_input", False)),
    )
    if args.command is None:
        parser.print_help(file=out.stdout)
        return EXIT_USAGE

    try:
        return _dispatch(args, app)
    except UsageError as exc:
        if exc.usage:
            print(exc.usage, end="", file=out.stderr)
        out.error(str(exc))
        return EXIT_USAGE
    except OperationRefused as exc:
        out.finding(exc.finding)
        return EXIT_REFUSED
    except ValidationError as exc:
        out.error(f"invalid data: {exc}")
        return EXIT_ENV
    except FileNotFoundError as exc:
        out.error(str(exc))
        return EXIT_ENV
    except ValueError as exc:
        out.error(str(exc))
        return EXIT_USAGE
    except NotImplementedError as exc:
        out.error(str(exc))
        return EXIT_INTERNAL
    except OSError as exc:
        out.error(str(exc))
        return EXIT_ENV
    except Exception as exc:
        if out.verbose:
            traceback.print_exc(file=out.stderr)
        out.error(f"internal error: {exc}")
        return EXIT_INTERNAL
