# AGENTS.md — GREGraph

## What this is
GREGraph is a local, Git-aware requirements management CLI. The full specification is
`docs/design.md`. Read it before writing code. When the spec and this file disagree,
the spec wins; open an issue noting the discrepancy.

## Ground rules
- Python >= 3.12. Runtime deps: pydantic, jinja2, markdown-it-py (+ mdit-py-plugins). Nothing else
  without a note in docs/decisions.md explaining why.
- `core` never prints and never imports `cli`. `cli` never touches the filesystem directly.
- Every CLI command maps to one function in `packages/core/src/gregraph/core/operations.py`.
- Findings are data (`Finding`), not exceptions. Refusals raise `OperationRefused(finding)`.
- All Git access goes through `packages/core/src/gregraph/core/git.py` via subprocess. No Git libraries.
- Canonical JSON: `indent=2, ensure_ascii=False, sort_keys=True`, trailing newline, links sorted.
- Paths in models are repository-relative `pathlib.Path`; only `storage.py` makes them absolute.

## Workflow
- Test first: write the failing test, then the code. Every validation code in spec §14 has a test.
- Run `ruff check . && ruff format --check . && mypy --strict -p gregraph && pytest` before every commit.
- One commit per coherent change; commit message subject <= 72 chars, body explains why.
  Reference the spec section touched, e.g. "graph: reject cross-type cycles (spec §6.2)".
- Milestones are in spec §18. Finish and tag a milestone before starting the next.
- Do not add features not in the spec. Record ideas in docs/backlog.md instead.
- Windows matters: use `pathlib`, never string paths; normalise line endings on read.

## Layout
See spec §16.1 and §16.4. Two distributions live under `packages/` (`gregraph-core`,
`gregraph-cli`) sharing the `gregraph` import package; the root `pyproject.toml` is
tooling-only. Tests live in `tests/` mirroring `packages/core/src/gregraph/core/` (`tests/core/`)
and `packages/cli/src/gregraph/cli/` (`tests/cli/`); CLI tests invoke
`gregraph.cli.main.main([...])` and use the `tmp_repo` fixture. Dev setup is in README.md.
Human docs: `README.md` (overview/install), `docs/cli.md` (command reference — keep in
sync with `packages/cli/src/gregraph/cli/main.py`), `docs/concepts.md` (the model for users),
`docs/decisions.md` (decision record), `docs/backlog.md` (spec questions, v0.2 ideas).

## Definition of done for v0.1
All milestones M1–M5 tagged, CI green on Linux/macOS/Windows, coverage >= 90% for core,
`docs/cli.md` and `docs/concepts.md` written, both distributions installed
(`python -m pip install ./packages/core ./packages/cli`; published `pip`/`pipx install gregraph-cli`) verified,
and the tool has been used to initialise the `gregraph-requirements` repository (M6).
