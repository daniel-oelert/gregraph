# GREGraph web UI

The web UI is an **optional** local browser front end for a GREGraph
repository. It ships in the third distribution `gregraph-webui` (source in
`packages/webui`) and is started with `gregraph serve`. It is a foreground
process that listens on loopback only. It does nothing unless you run it.

This page describes the first version as implemented. The specification is
`docs/design.md` §21 (Amendment A1); the decision is recorded as D-WEBUI in
`docs/decisions.md`. Where this page and §21 differ, §21 wins.

## Contents

- [What it is for](#what-it-is-for)
- [Install](#install)
- [Run](#run)
- [Security model](#security-model)
- [Using the UI](#using-the-ui)
- [Saving changes](#saving-changes)
- [What is not included](#what-is-not-included)
- [Concurrency limits](#concurrency-limits)
- [HTTP API](#http-api)
- [Development and CI](#development-and-ci)

## What it is for

Browsing and filtering the documents of a requirements repository, creating a
document, editing its Markdown, setting its tags, linking documents, checking
status and validation findings, and viewing a graph of up to 300 nodes.

Every action calls the same core operations as the CLI, so the rules are the same:
links are checked for cycles, kind rules and liveness; a body save follows the
versioning rules; and the pre-commit hook and `gregraph sync` still record
versions at commit time.

## Install

The web UI needs the two baseline distributions and `gregraph-webui`, all at
version 0.1.1.

From a checkout:

```
python -m pip install ./packages/core ./packages/cli ./packages/webui
```

Published (intended usage, not yet on an index):

```
pip install gregraph-webui
```

`gregraph-webui` depends on `gregraph-core` and `gregraph-cli` of the same
version, so it also provides the `gregraph` command. It adds `fastapi` and
`uvicorn`. The frontend is shipped compiled inside the wheel, so **Node.js is not
needed to install or run the web UI**.

Without `gregraph-webui`, `gregraph serve` is not a command: it is a usage error
(exit 2) with a hint to install `gregraph-webui`.

## Run

From a repository, or with `--repo PATH`:

```
gregraph serve
```

```
GREGraph UI: http://127.0.0.1:8765/
Press Ctrl-C to stop.
```

Open the URL in a browser yourself; `serve` does not launch a browser. The URL
carries no token.

| Option | Default | Notes |
|---|---|---|
| `--host HOST` | `127.0.0.1` | Exactly `127.0.0.1`, `localhost` or `::1`. Any other value is a usage error (exit 2). |
| `--port PORT` | `8765` | Integer from 1 to 65535. Otherwise a usage error (exit 2). |

- Ctrl-C stops the server and exits 0. Nothing is left running: `serve` is not
  a daemon.
- If the port cannot be bound (for example, it is in use), the command exits 3
  with a message that suggests `--port`.
- Without a repository, the command exits 3.

The web UI is for a **trusted local checkout**, used by the person who runs it.
Do not expose it through a tunnel, a reverse proxy or a container port mapping.

## Security model

- **Loopback only.** The server binds to the address you asked for and accepts
  only loopback names. It makes no outbound network connections.
- **Guards on every HTTP request.** The page, the static assets and every `/api/`
  route pass three checks. A refusal is HTTP 403 with the code `E-REQUEST-REFUSED`.
  - **Host.** Exactly one `Host` header, naming exactly `127.0.0.1`, `localhost`
    (any letter case) or `[::1]`. Other addresses, including other `127.x.x.x`
    addresses, are refused. A header without a port means the HTTP default,
    port 80. When started with `gregraph serve`, the header's effective port (its
    explicit port, or 80 when there is none) must equal the port you started on.
    So a server on port 80 accepts the bare `127.0.0.1` or `localhost` that
    browsers send; a server on the default 8765 accepts only a header that names
    8765.
  - **Origin.** If the request has an `Origin` header, it must equal `http://`
    followed by the request's own `Host` value. Anything else is refused.
  - **Fetch-Site.** If the request has a `Sec-Fetch-Site` header, it must be
    `same-origin` or `none`.
- **Application token.** The application generates a random token when it
  starts. The token is held in memory only and is never printed, logged or put
  in a URL. `GET /api/session` returns it as `csrf_token`. Every mutating request
  (`POST`, `PUT`, `PATCH`, `DELETE`) must send it in the `X-GREGraph-Token`
  header; a missing or wrong value is refused with 403 `E-TOKEN-INVALID`. Reads
  do not need the header.
- **Request framing.** Mutating requests must be `application/json`, must not
  use `Content-Encoding`, and must not exceed 1 MiB.
- **What these guards are for.** They protect you from web pages that your
  browser loads from other origins: cross-site request forgery and DNS
  rebinding. They do **not** protect against other users or programs on the same
  machine. Anything running as your user can already read and change the
  repository directly. This is a browser-origin guard, not a login; there are no
  user accounts.
- **Text only.** Markdown is shown and edited as plain text. The server does not
  render it to HTML. Responses carry a Content-Security-Policy that allows only
  same-origin scripts and styles.

## Using the UI

The header shows the repository name, and a "No Git" badge when Git is not
available. Three tabs follow: **Documents**, **Graph** and **Validation**.

### Documents tab

**Status cards** sit above the list. They show a Git-aware or degraded badge,
the number of findings, one count per derived status as core reports it, and
three lists of clickable link labels: pending changes (edits not yet recorded by a
version bump), outdated links, and stale links.

Each entry is a link label of the form `SOURCE TYPE TARGET`. Clicking an entry
opens its source document. A label that cannot be parsed is shown as plain text
and is not clickable.

**Filters** narrow the list:

- a search box (`q`): case-insensitive text matched against the title or the ID;
- a type select: every type in the repository, the change-request type included
  in the filter list;
- a status select: `draft`, `active`, `superseded`, `deprecated`.

There are no kind or tag filters. Each row shows ID, type, derived status,
version and title; clicking a row opens the document.

**Create** opens a dialog with a type (the change-request type is not offered), a
title and optional tags. The document is created with the type's default
template, the same way `gregraph new` creates one. A new document has no links
until you add some; `validate` reports it as an orphan (warning only).

**Document detail** shows the sidecar fields, the derived status, the tags, the
outbound and inbound links with their freshness, and two editors:

- **Tags** replace the document's tag list as a whole. Tags are lowercase
  `[a-z0-9-]`.
- **Body** is the raw Markdown as plain text (see [Saving changes](#saving-changes)).

**Links.** Choose a link type and a target, then add the link. The target select
lists every other document; it does not filter by kind, cycles or liveness. The
server checks the link when you submit it. A refusal, such as `E-CYCLE` or
`E-EDGE-RULE`, is shown with its finding text. Each outbound link has its own
remove action.

### Graph tab

The graph shows the nodes and edges returned by the graph endpoint: the **first
300 nodes** in ascending ID order, with the edges between them. When the
repository has more nodes, the view shows the notice "Graph truncated: showing N
of M nodes (limit 300)". There is no root or type filter in this version. Clicking
a node opens its document.

### Validation tab

Shows the error and warning counts and each finding with its code, severity,
message and subject. When there are none, the tab says that the repository is
valid.

## Saving changes

A body save sends the new text together with the `base_hash`: the normalised
hash of the body that the editor read from disk. The detail response returns the
current body as `body_text`, and its `body_hash` is the value to send back.

- **Saved.** If the file on disk still matches the `base_hash`, the text is
  stored exactly as you sent it, except that CRLF and CR line endings become LF.
  Hard line breaks, blank lines, trailing spaces and the final newline are kept.
  The response reports `changed`, the new `body_hash`, and any findings. The
  success message says that the change is pending until `gregraph sync` or the
  pre-commit hook records the new version. A save does not bump the version.
- **Findings, not refusals.** A text without a level-1 heading as its first
  non-blank line is still saved. The response carries `E-TITLE-MISSING`. A text
  that starts with `---` is still saved and carries `E-FRONTMATTER-FORBIDDEN`.
  These are problems to fix. With no heading, the title in the sidecar keeps its
  previous value.
- **Title.** When the text has a heading, the sidecar title is updated to match.
  This is a separate write. If your text is unchanged, the body file is not
  rewritten; a title that differs from the heading is still updated, and
  `changed` is then true.
- **Stale (HTTP 409, `E-BODY-STALE`).** The file changed on disk since the editor
  read it, for example because you saved in another tab, or a `git pull` changed
  it. Nothing is written, the draft is kept, and the UI asks you to reload the
  document before saving again.
- **Missing body file (HTTP 409, `E-BODY-MISSING`).** Nothing is written and the
  file is not recreated.
- **Unsafe path (HTTP 400, `E-PATH-UNSAFE`).** A symbolic link, or a Windows
  junction, in the document's path or in a folder above it, or a path that would
  leave the repository. Nothing is written.

The body file is replaced in one step: the new text goes to a temporary file in
the same folder, which then replaces the original. Mode bits are kept. Access
control lists and extended attributes are not. The sidecar title is written
separately and is not part of that step. A crash between the two writes can leave
the title out of date until the next sync or save corrects it. A crash during the
sidecar write can leave a truncated sidecar; `gregraph validate` then reports
`E-SIDECAR-INVALID`, and it must be repaired by hand.

After saving, the normal Git workflow applies. `git commit` runs the pre-commit
hook, which records versions and blocks a commit that would newly outdate links,
exactly as for an edit made in an editor. `gregraph check` shows what the hook
would say.

## What is not included

These are deliberately outside this extension (`docs/design.md` §21.1):

- Git commit, branch, push or pull from the UI.
- Asset upload, or any access to files other than the repository's Markdown and
  sidecars through the core operations.
- Editing change requests, glossary terms, sidecar JSON or configuration.
- Rendering Markdown as HTML.
- Kind or tag filters in the list, and a root or type filter for the graph.
- Remote, shared or multi-user deployment, and authentication beyond the
  browser-origin guard.
- A daemon, a background service, or a watch mode.

## Concurrency limits

- Requests from the web UI run one at a time, serialised in the `serve` process.
- Changes made **outside** that process are not locked. This includes the CLI in
  another terminal, an editor, and Git. The stale check is a best-effort guard:
  it is not one atomic compare-and-swap against other processes, and the body and
  sidecar writes are not atomic with each other. An external change can still
  land between the check and the write. This is an accepted residual risk, not a
  resolved one.
- The practical rule matches the CLI: do not edit the same document in two places
  at once, and reload after a `git pull`.

## HTTP API

Every route below is served by `gregraph serve` and passes the
[guards](#security-model). Mutating routes also need the `X-GREGraph-Token`
header. Request and response bodies are JSON, and Markdown travels as a string.
Errors use one envelope: `{"error": {"code", "severity", "message", "doc_id",
"path", "fix"}}`.

| Method | Path | Token | Purpose |
|---|---|---|---|
| `GET` | `/` | no | The web page (503 `E-ASSETS-MISSING` if the bundle is absent). |
| `GET` | `/assets/*` | no | Static bundle files. |
| `GET` | `/api/session` | no | Repository summary, document types with kinds, link types, version, and `csrf_token`. |
| `GET` | `/api/documents?type=&status=&q=` | no | Document list: `items` with `id`, `type`, `kind`, `status`, `version`, `title`, `tags`, plus `notices`. |
| `POST` | `/api/documents` | yes | Create from `{type, title, tags}`. Returns `201` with `id`, `notices`, `findings`. |
| `GET` | `/api/documents/{doc_id}` | no | Document detail: `type`, `kind`, `status`, `version`, `title`, `tags`, `body_text`, `body_hash`, `outbound`, `inbound`, `notices`. |
| `PUT` | `/api/documents/{doc_id}/body` | yes | Save `{text, base_hash}`. Returns `id`, `body_hash`, `title`, `changed`, `findings`. |
| `PATCH` | `/api/documents/{doc_id}/meta` | yes | Replace the tag list with `{tags}`. Returns `id`, `tags`, `notices`. |
| `POST` | `/api/links` | yes | Create a link `{source, type, target}`. Returns `created` and `notices`. |
| `DELETE` | `/api/links/{source}/{link_type}/{target}` | yes | Remove a link. Returns `removed` and `notices`. |
| `GET` | `/api/status` | no | `counts`, `degraded`, `pending`, `outdated`, `stale` (link labels), `findings`. |
| `GET` | `/api/validate` | no | `findings`, `error_count`, `warning_count`. |
| `GET` | `/api/graph` | no | `nodes` (`id`, `title`, `kind`), `edges` (`source`, `type`, `target`), `truncated`. At most 300 nodes. |

**Status codes**

| Status | When |
|---|---|
| 200 | Success (reads, body save, tags, link create and remove). |
| 201 | Document created. |
| 400 | Invalid request body or parameters (`E-REQUEST-INVALID`), including unknown link types in the path. Also `E-PATH-UNSAFE`. The API does not use 422. |
| 403 | Guard refused (`E-REQUEST-REFUSED`), or missing or wrong token on a mutation (`E-TOKEN-INVALID`). |
| 404 | Unknown document (`E-ID-UNKNOWN`), or unknown route (`E-NOT-FOUND`). |
| 405 | Wrong method (`E-METHOD-NOT-ALLOWED`). |
| 409 | Other core refusals, including `E-BODY-STALE`, `E-BODY-MISSING`, `E-CYCLE`, `E-EDGE-RULE`. |
| 413 | Mutation body over 1 MiB (`E-BODY-TOO-LARGE`). |
| 415 | Mutation not `application/json` (`E-CONTENT-TYPE`), or `Content-Encoding` present (`E-CONTENT-ENCODING`). |
| 500 | Unexpected error (`E-INTERNAL`). No traceback is sent. |
| 503 | The web bundle is not installed (`E-ASSETS-MISSING`). |

Each refusal's finding `code` appears in the envelope, so clients branch on the
code, not on the message text.

## Development and CI

Python side, from the repository root (as in the README):

```
python -m pip install --group dev -e packages/core -e packages/cli -e packages/webui
ruff check . && ruff format --check . && mypy --strict -p gregraph && pytest
ruff check . && ruff format --check . && mypy --strict -p gregraph -p gregraph.cli -p gregraph.webui && pytest
```

The first line is the required gate. The second is the full check that CI runs:
it names the optional CLI and web UI packages explicitly, which `-p gregraph`
alone does not reach through the shared namespace. It needs all three
distributions installed. `python tests/packaging_check.py` verifies the three
wheels in clean virtual environments.

Frontend side, in `packages/webui/frontend` (Node.js 22.12 or later; Node 22 LTS or Node 24 recommended):

```
npm ci
npm run test
npm run typecheck
npm run build
```

- Source: React 19, TypeScript, Tailwind CSS 4, built with Vite 7; unit tests with
  Vitest 4. `package-lock.json` is committed; always use `npm ci`.
- `npm run build` runs the TypeScript check and then writes the bundle into
  `packages/webui/src/gregraph/webui/static/`. That directory is **checked in**.
  Rebuild it after any frontend source change and commit the result with the
  source.
- CI (`.github/workflows/ci.yml`, job `frontend`, `ubuntu-latest`) runs
  `npm run test` and `npm run typecheck` on Node 22 and 24. On Node 22 it also
  runs `npm run build` and the bundle drift check: `git diff --exit-code` on the
  static directory, and a failure if an untracked file appears there.
- The Python job installs `packages/webui` in editable mode and runs the whole
  test suite, including the web tests.

Packaging: `packages/webui/pyproject.toml` (hatchling) builds `gregraph-webui`
with the bundle as package data, lockstep with `gregraph-core` and
`gregraph-cli`.
