# GREGraph

Local, Git-aware requirements management. GREGraph stores requirements as
Markdown files with JSON sidecars in a dedicated Git repository, links them
into a typed traceability graph, tracks which document version each link was
confirmed against, and gives change requests, glossary terms and baselines a
first-class home — all offline, all plain text, all through one CLI.

- **Documents are Markdown.** Readable in any editor, reviewable in any Git
  host; the tool adds IDs, versions and structure, never a database.
- **The graph is typed.** `refines`, `derives-from`, `depends-on`,
  `satisfies`, `verifies`, `constrains`, `supersedes`, `conflicts-with` —
  with kind rules and cycle rejection keeping it honest.
- **Links carry versions.** Every link records the target version it was
  confirmed against; the pre-commit hook blocks commits that would silently
  outdate links, and `link refresh` is the review act that re-confirms them.
- **Change control included.** Change requests sit outside the graph with
  scope, base versions, a decision history and drift detection; acceptance
  is the merge into the baseline branch.
- **No server, no network.** A CLI, a Git repository and (optionally) the
  `git` binary. Works in degraded mode without Git. The optional web UI
  (`gregraph serve`) is the one exception: a foreground process that listens on
  loopback only and is never remote.

GREGraph v0.1.0 implements the design in [`docs/design.md`](docs/design.md).

## Requirements

- Python >= 3.12
- Git (optional but recommended — without it the tool runs in degraded mode)

## Install

GREGraph ships as distributions built from this repository's `packages/`
directory, released in lockstep (same version number):

- `gregraph-core` — the library (`gregraph.core`).
- `gregraph-cli` — the `gregraph` command; depends on `gregraph-core`.
- `gregraph-webui` — **optional**: the local web UI behind `gregraph serve`;
  depends on `gregraph-core` and `gregraph-cli`, and adds FastAPI and uvicorn.
  Not needed for the command line. See [`docs/webui.md`](docs/webui.md).

From a checkout, install the two baseline distributions:

```
python -m pip install ./packages/core ./packages/cli
```

This provides the `gregraph` command (`python -m gregraph` also works).
Installing only `./packages/core` gives the library without the command.

To add the optional web UI, install the third distribution as well:

```
python -m pip install ./packages/core ./packages/cli ./packages/webui
```

Then `gregraph serve` starts the UI on `http://127.0.0.1:8765/` (see
`docs/webui.md`). Without `gregraph-webui`, `serve` is not a command.
Installing the web UI needs no Node.js: the frontend is shipped compiled.

The distributions are not yet published to an index. Once they are, the
same install is `pip install gregraph-cli`, or `pipx install gregraph-cli`
for an isolated CLI, `pip install gregraph-core` gives the library only, and
`pip install gregraph-webui` adds the web UI.

## Quickstart

```
gregraph init my-requirements        # create a requirements repository
cd my-requirements

gregraph new user-story --title "As a user I can reset my password"
gregraph new feature --title "Password reset" --link refines:RE-XXXXXX
gregraph link RE-XXXXXX depends-on RE-YYYYYY

gregraph show RE-XXXXXX              # fields, links, impact
gregraph status                      # WIP, drafts, outdated links, CRs
gregraph validate                    # full check (CI: gregraph validate --strict)
gregraph graph -o graph.md           # Mermaid flowchart export

git add . && git commit              # hook bumps versions, blocks broken links
gregraph baseline create 0.1.0       # tag a named accepted state
```

Run without arguments or with `--help` for the full command tree. Most
commands prompt for missing arguments when on a terminal and accept flag
equivalents for scripting (`--no-input` disables prompting entirely).

## Documentation

| Document | What it covers |
|---|---|
| [`docs/design.md`](docs/design.md) | The specification — source of truth (§21 covers the optional web UI). |
| [`docs/cli.md`](docs/cli.md) | Every command, flag, exit code and interactive behaviour. |
| [`docs/webui.md`](docs/webui.md) | The optional local web UI: install, `serve`, security model, saving, development. |
| [`docs/concepts.md`](docs/concepts.md) | The model for humans: documents, the graph, versions, status, change requests. |
| [`docs/decisions.md`](docs/decisions.md) | Design decision log and implementation decisions. |
| [`docs/backlog.md`](docs/backlog.md) | Open spec questions and v0.2 ideas. |
| [`AGENTS.md`](AGENTS.md) | Contributor guide for working on the tool itself. |

## Development

```
python -m venv .venv && . .venv/bin/activate
python -m pip install --upgrade pip        # pip >= 25.1 is needed for --group
python -m pip install --group dev -e packages/core -e packages/cli -e packages/webui
ruff check . && ruff format --check . && mypy --strict -p gregraph && pytest
ruff check . && ruff format --check . && mypy --strict -p gregraph -p gregraph.cli -p gregraph.webui && pytest
```

The first gate line is the required gate and stays unchanged. The second line is
the explicit form that CI also runs. It names the optional `gregraph.cli` and
`gregraph.webui` packages, which `-p gregraph` alone does not reach through the
shared namespace. Run both. The full check needs all three distributions
installed, which the editable install above provides. The third editable install
(`-e packages/webui`) brings in FastAPI and uvicorn for the web UI.

Packaging is verified with `python tests/packaging_check.py`, which CI also runs.
It builds the three wheels, checks their contents, and installs them in clean
virtual environments (see `docs/design.md` §21.9).

To build the distributions into `dist/`:

```
python -m pip wheel --no-build-isolation --no-deps ./packages/core ./packages/cli ./packages/webui -w dist
```

The root `pyproject.toml` is tooling-only (dependency groups and tool
configuration); the packages are built from `packages/core`, `packages/cli`
and `packages/webui`. Packaging and layout are described in `docs/design.md`
§16.1, §16.4 and §21.2.

### Web UI frontend

The web UI's frontend lives in `packages/webui/frontend` (React, TypeScript,
Tailwind CSS, Vite). Its compiled output is checked in under
`packages/webui/src/gregraph/webui/static/`. Node.js 22.12 or later (Node 22 LTS or Node 24 recommended) is needed only
when you change the frontend:

```
cd packages/webui/frontend
npm ci && npm run test && npm run typecheck && npm run build
```

Commit the rebuilt `static/` together with the source change; CI fails if the
bundle is out of date (see `docs/webui.md`).

The quality gate must pass before every commit; see
[`AGENTS.md`](AGENTS.md) for the ground rules and layout.
