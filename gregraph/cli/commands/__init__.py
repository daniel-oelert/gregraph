"""Shared command-module helpers (spec §16.1: thin parse → core → format).

Every command module exposes ``run(args: argparse.Namespace, app: App) -> int``
(contract of :mod:`gregraph.cli.main`). Interactive selection happens before
the core call (spec §16.2); the picker rows here carry the (ID, type, title,
status) columns of spec §13.
"""

from __future__ import annotations

from typing import cast

from gregraph.cli.prompts import PickRow
from gregraph.core.config import Config
from gregraph.core.models import LinkType
from gregraph.core.status import compute_status
from gregraph.core.workspace import Workspace


def document_pick_rows(workspace: Workspace) -> list[PickRow]:
    """Picker rows over all documents: ID, type, title, derived status (spec §13)."""
    report = compute_status(workspace)
    rows: list[PickRow] = []
    for key in sorted(workspace.index.documents):
        document = workspace.index.documents[key].model
        item = report.documents.get(key)
        rows.append(
            PickRow(
                key=key,
                type=document.type,
                title=document.title,
                status=item.status if item is not None else "unknown",
            )
        )
    return rows


def type_pick_rows(config: Config) -> list[PickRow]:
    """Picker rows over the configured document types (``new``, spec §13.2)."""
    return [
        PickRow(key=name, type=spec.kind, title=spec.template, status="")
        for name, spec in sorted(config.types.items())
    ]


def parse_link_spec(text: str) -> tuple[LinkType, str]:
    """Parse ``TYPE:TARGET`` (``new --link``, spec §13.2).

    Raises ``ValueError`` on malformed input.
    """
    edge_type, separator, target = text.partition(":")
    if not separator or not edge_type.strip() or not target.strip():
        raise ValueError(f"expected TYPE:TARGET, got {text!r}")
    return cast("LinkType", edge_type.strip()), target.strip()
