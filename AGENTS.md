# AGENTS.md — GREGraph

## What this is
GREGraph is a local, Git-aware requirements management CLI. The full specification is
`docs/design.md`. Read it before writing code. When the spec and this file disagree,
the spec wins; open an issue noting the discrepancy.

## Ground rules
- Python >= 3.12. Runtime deps: pydantic, jinja2, markdown-it-py (+ mdit-py-plugins) for core and
  cli. The optional `gregraph-webui` distribution alone adds fastapi and uvicorn (design §21.2,
  D-WEBUI). Nothing else without a note in docs/decisions.md explaining why.
- `core` never prints and never imports `cli` or `webui`. `cli` never touches the filesystem directly.
  `webui` never touches repository files directly; it calls `operations.py`.
- Every CLI command maps to one function in `packages/core/src/gregraph/core/operations.py`.
  Exception: `serve` is a lifecycle command that launches the optional web UI (design §21.3).
  `serve` is not present unless `gregraph-webui` is installed, and no webui module may be imported
  by `--help` or any other command.
- Findings are data (`Finding`), not exceptions. Refusals raise `OperationRefused(finding)`.
- All Git access goes through `packages/core/src/gregraph/core/git.py` via subprocess. No Git libraries.
- Canonical JSON: `indent=2, ensure_ascii=False, sort_keys=True`, trailing newline, links sorted.
- Paths in models are repository-relative `pathlib.Path`; only `storage.py` makes them absolute.

## Workflow
- Test first: write the failing test, then the code. Every validation code in spec §14 has a test.
- Run `ruff check . && ruff format --check . && mypy --strict -p gregraph && pytest` before every commit.
  CI also runs `mypy --strict -p gregraph -p gregraph.cli -p gregraph.webui` (the explicit namespaces
  cover the optional CLI and web UI, which `-p gregraph` alone does not reach; it needs all three
  distributions installed). Packaging changes also run `python tests/packaging_check.py`.
- Changes under `packages/webui/frontend` also run `npm ci && npm run test && npm run typecheck && npm run build`
  there (Node.js 22.12+, Node 22 LTS or 24 recommended). Commit the rebuilt `packages/webui/src/gregraph/webui/static/` with the source;
  the bundle is checked in and CI rejects drift.
- One commit per coherent change; commit message subject <= 72 chars, body explains why.
  Reference the spec section touched, e.g. "graph: reject cross-type cycles (spec §6.2)".
- Milestones are in spec §18. Finish and tag a milestone before starting the next.
- Do not add features not in the spec. Record ideas in docs/backlog.md instead.
- Windows matters: use `pathlib`, never string paths; normalise line endings on read.

## Layout
See spec §16.1, §16.4 and §21.2. Two baseline distributions live under `packages/` (`gregraph-core`,
`gregraph-cli`) sharing the `gregraph` import package. The optional third distribution `gregraph-webui`
lives in `packages/webui` (Python source `packages/webui/src/gregraph/webui/`, React/TypeScript/Tailwind
frontend in `packages/webui/frontend/`). Its compiled bundle is checked in under
`packages/webui/src/gregraph/webui/static/`. It depends on core and cli of the same version, and nothing
depends on it. The root `pyproject.toml` is tooling-only. Tests live in `tests/` mirroring
`packages/core/src/gregraph/core/` (`tests/core/`), `packages/cli/src/gregraph/cli/` (`tests/cli/`),
and `packages/webui/src/gregraph/webui/` (`tests/webui/`); CLI tests invoke
`gregraph.cli.main.main([...])` and use the `tmp_repo` fixture. Dev setup is in README.md.
Human docs: `README.md` (overview/install), `docs/cli.md` (command reference — keep in
sync with `packages/cli/src/gregraph/cli/main.py`), `docs/webui.md` (optional web UI — keep in sync
with `packages/webui`), `docs/concepts.md` (the model for users), `docs/decisions.md` (decision record),
`docs/backlog.md` (spec questions, v0.2 ideas).

## Definition of done for v0.1
All milestones M1–M5 tagged, CI green on Linux/macOS/Windows, coverage >= 90% for core,
`docs/cli.md` and `docs/concepts.md` written, both distributions installed
(`python -m pip install ./packages/core ./packages/cli`; published `pip`/`pipx install gregraph-cli`) verified,
and the tool has been used to initialise the `gregraph-requirements` repository (M6).
The optional web UI extension (design §21) has its own acceptance and is not part of this definition.
