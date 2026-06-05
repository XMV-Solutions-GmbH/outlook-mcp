<!--
SPDX-License-Identifier: MIT OR Apache-2.0
SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
SPDX-FileContributor: David Koller <david.koller@xmv.de>
-->

# PROJECT_SPECIFICS.md — `mcp-server-outlook`

Project-specific content for `mcp-server-outlook`. Read after `AGENTS.md` per its reading order. Everything in here is specific to this repo; the generic agent rules live in `AGENTS.md` + `ENGINEERING_PRINCIPLES.md` + `PROJECT_MANAGEMENT_PRINCIPLES.md`.

## What this project is

A Model Context Protocol server that lets AI coding agents read and draft email and calendar items in Microsoft 365 Outlook — **without ever auto-sending and without breaking audit attribution**.

Sister project to [`mcp-server-sharepoint`](https://github.com/XMV-Solutions-GmbH/sharepoint-mcp). Same authorship pattern, same OSS template, same auth shape — different surface (mail + calendar instead of files).

Full vision and tool surface in [`docs/app-concept.md`](docs/app-concept.md). Read it before changing anything that touches the public MCP tool surface.

## Project-specific docs

| Doc | Purpose |
|---|---|
| [`docs/app-concept.md`](docs/app-concept.md) | Vision, MVP scope, MCP tool surface, auth model, safety semantics, login UX, open tech-spike questions |
| [`docs/testconcept.md`](docs/testconcept.md) | Test-harness strategy for AI-assisted development |
| [`docs/spikes/`](docs/spikes/) | Spike notes / design discussions (e.g. `2026-05-08-v02-drafts-spikes.md`) |
| [`docs/howto-oss.md`](docs/howto-oss.md) | OSS-template setup notes inherited from the template; trim once they no longer apply |
| [`README.md`](README.md) | Quickstart for end users (install via `uvx`, configure `.mcp.json`) |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Contribution flow |
| [`SECURITY.md`](SECURITY.md) | Vulnerability disclosure |
| [`CHANGELOG.md`](CHANGELOG.md) | Keep-a-changelog history |

The legacy `docs/todo.md` is a frozen artefact from the OSS template; do not extend it. New work goes into Issues.

## Tracker

**GitHub Issues + the repo-bound GitHub Project** at <https://github.com/XMV-Solutions-GmbH/outlook-mcp/issues>. See `ENGINEERING_PRINCIPLES.md` § 2.

- Labels:
  - `type:feat` / `type:fix` / `type:chore` / `type:docs` / `type:test`
  - `area:auth` / `area:tools` / `area:ci` / `area:packaging` / `area:docs`
  - `priority:p0` / `p1` / `p2`
  - `agent:claude` when an AI agent is the executor.
- Issue body convention: `## Context`, `## Acceptance criteria` (checkbox list), `## Out of scope`, `## Links`.
- Milestones map to releases: `v0.1.0 — MVP`, `v0.2.0`, etc.

## Tech stack

- **Python 3.11+**, packaged for `uvx` / `pipx` install on PyPI (`mcp-server-outlook`).
- **Microsoft Graph via raw `httpx`** — same call-shape as `mcp-server-sharepoint`. No `msgraph-sdk-python` dependency.
- **MCP Python SDK** (FastMCP) for the protocol layer; stdio transport, one process per tenant.
- **Auth**: OAuth Device Code flow; token cache via OS keyring with plain-file fallback (mode 0600), encrypted-file opt-in. Shared primitives in the `mcp-microsoft-graph-auth` library (also used by the SharePoint sibling).
- **Tests**: pytest + a dedicated Microsoft 365 test tenant; `respx` for HTTP mocking. CI runs in GitHub Actions; secrets injected from repo secrets.
- **Lint/format**: ruff, mypy.

## MCP tool surface conventions

The public MCP surface is the product. Treat any change to it as a contract change — read `docs/app-concept.md` first.

- **Tool naming.** Every tool is prefixed `ol_` and grouped by domain: `ol_email_*`, `ol_calendar_*`, plus `ol_status`, `ol_login_begin`, `ol_login_status`. When multiple servers run in one client, tools surface namespaced by profile, e.g. `mcp__outlook-anqer__ol_email_search`.
- **Read vs write tiers.** Read tools (`ol_email_search`, `ol_email_list_unread`, `ol_email_read`, `ol_calendar_search`, `ol_calendar_list_events`, `ol_status`, …) are **always registered**. Write/draft tools (`ol_email_create_draft`, `ol_email_update_draft`, `ol_email_discard_draft`, `ol_email_list_drafts`, `ol_calendar_create_event_draft`, `ol_calendar_discard_event_draft`) are **only registered when `OUTLOOK_ALLOW_DRAFTS=true`** (historically `OL_ALLOW_DRAFTS`).
- **Tools that are deliberately NOT exposed.** No autonomous `send_email` / `send_draft`, no `send_calendar_invitation`, no `delete_email` / `archive_email`, no bulk operations on items the user did not author or draft via this MCP. Each omission is a design choice, not a backlog gap.
- **Confirmation hinting.** Read tools are flagged read-only; draft tools are flagged "creates draft (no send)"; send/delete tools (where opted-in) are flagged destructive — so the MCP client's consent prompt shows the difference at call time.

### The never-auto-send rule (defining constraint)

This is the constraint the whole server is built around — three layers:

1. **The default install never sends.** Without `OUTLOOK_ALLOW_SEND=true` in the MCP client config, no `ol_email_send_draft` tool is registered AND `Mail.Send` is not in the OAuth scope request. The consent prompt does NOT read "this app can send mail as you" out of the box — the compliance posture that lets cautious tenant admins approve the tool.
2. **Send is opt-in, not auto-on.** Setting `OUTLOOK_ALLOW_SEND=true` is a deliberate per-deployment choice; the opt-in extends the consent screen and the user actively approves `Mail.Send` at the next sign-in (v0.3+).
3. **No autonomous send, ever.** Even with the opt-in active, the agent never sends without an explicit `ol_email_send_draft(draft_id)` call referencing a draft already in the user's Drafts folder. The human reviews the draft in Outlook between create and send.

**Calendar invitations follow the same shape**: events are created with `responseRequested=false` so Microsoft Graph never auto-emails attendees. There is no `send_invitation` tool; the human clicks Send Invitation in Outlook manually.

If a future feature request asks for "auto-send when X" — say no. The opt-in path covers explicit-send use cases; autonomous-send breaks the audit-trail story. For the scope-gating mechanic see `auth/flow.py:resolve_scopes()` and `docs/spikes/2026-05-08-v02-drafts-spikes.md` § 1 (revised).

## Sign-in / auth flow (login UX from MCP clients)

Two MCP tools drive OAuth from inside the client without shelling out: `ol_login_begin(force=False)` and `ol_login_status()`. The final 2-tool design (v0.3) supersedes the earlier 4-tool RFC — do **not** re-derive `ol_login_cancel` / `ol_logout` as tools (logout stays CLI-only; `force=True` covers cancel-and-restart). See `docs/app-concept.md` § "Login UX from MCP clients".

- `ol_login_begin` runs the Device Code flow, polls Microsoft Identity in the background, and blocks until a terminal status. Idempotent: a non-expired pending session for the profile is joined, not duplicated. `force=True` cancels an in-flight session and starts fresh.
- `ol_login_status` **actively probes** the token store, so a user who logged in via the CLI hours ago shows as `signed_in`, not `none`. Three states: `signed_in` / `pending` / `none` (terminal failures fold into `none` + a structured `error`).

### How the code is emitted on sign-in, and how the markdown link is formed

When surfacing an `ol_login_begin` result to the user, the tool descriptions instruct the agent to:

- render `user_code` **FIRST**, in its own fenced code block, with no labels and no surrounding whitespace (so the user can one-tap copy it); then
- render `verification_url` **SECOND**, as a plain auto-link (a bare URL Markdown auto-links — **not** wrapped in a code block, and never inside backticks).

The user copies the code first, then taps the link and pastes into the page that opens — this ordering minimises app-switching on mobile. This phrasing is baked into both tools' MCP descriptions, so it is part of the tool contract, not just docs.

## Test harness for an MCP server

Three layers (see `docs/testconcept.md` and `tests/run_tests.sh`):

- **unit** — pure logic, no I/O.
- **integration** — Microsoft Graph calls mocked with `respx`; exercises the tool handlers without a live tenant.
- **harness** — runs against a **real Microsoft 365 sandbox tenant**, gated behind a harness-profile login (`./tests/run_tests.sh harness`). A dedicated test mailbox is required; credentials live in GitHub Actions secrets for CI and in a developer-local git-ignored `.env` for iterative work. Document the tenant/mailbox in `docs/testconcept.md` once provisioned.

### MCP-install test: a fresh sub-agent driving only the tool suite

> Note: this practice is recorded here from the Canon migration brief; it is the intended interface-level test for this server but is not yet written up in the repo's own docs. Capture it in `docs/testconcept.md` when the harness work lands.

The strongest end-to-end check of an MCP server is to have it installed and exercised by a **sub-agent that does NOT know the dev environment or operator briefing** — it receives **only the MCP tool suite as its interface**. That way the tool names, descriptions, parameter shapes, error messages, and the sign-in UX (code-then-link rendering above) are tested the way a real LLM client experiences them, with no insider context to paper over a confusing surface. If the naive agent can install, sign in, triage and draft using only the tool descriptions, the surface is good; where it gets stuck is where the surface needs fixing.

## Project-specific overrides of the engineering baseline

- **PR workflow trigger (per EP § 13).** Once the package is published to PyPI / installable via `uvx`, the project has external users — treat `main` as deployable trunk: feature branches + PRs, branch protection, CI green required for merge. Until the first published release, direct commits to `main` are acceptable for chores and docs.
- **Test environment (per EP § 5).** A dedicated Microsoft 365 test mailbox is required for harness tests (see above).
- **OSS licensing, not proprietary.** This repo is OSS: every source-file header uses `SPDX-License-Identifier: MIT OR Apache-2.0` (see `LICENSE-MIT`, `LICENSE-APACHE`), © XMV Solutions GmbH. The proprietary header variants from sister/internal repos do **not** apply here. The `AGENTS.md` / `ENGINEERING_PRINCIPLES.md` / `PROJECT_MANAGEMENT_PRINCIPLES.md` files are the only `LicenseRef-XMV-Proprietary` files in the tree — they are XMV IP carried in verbatim, not relicensed.
- **Env var prefix.** Environment variables use the `OUTLOOK_*` prefix (`OUTLOOK_PROFILE`, `OUTLOOK_CLIENT_ID`, `OUTLOOK_TENANT_ID`, `OUTLOOK_AUTH_MODE`, `OUTLOOK_CLIENT_SECRET`, `OUTLOOK_TOKEN_STORE`, `OUTLOOK_TOKEN_PASSPHRASE`, `OUTLOOK_ALLOW_DRAFTS`, `OUTLOOK_ALLOW_SEND`). The sister project uses `SP_*`; the two do not share env vars, to avoid cross-contamination when both servers run in the same shell.

## Environments + URLs

- **Repository**: <https://github.com/XMV-Solutions-GmbH/outlook-mcp>
- **Distribution**: PyPI package `mcp-server-outlook` (install via `uvx` / `uv tool install` / `pip`).
- **Microsoft Graph**: live per call (no local sync/cache beyond the token cache + per-profile draft registry). Default tenant routing via the `common` endpoint; BYO override with `OUTLOOK_TENANT_ID` + `OUTLOOK_CLIENT_ID`.
- **Entra app (Outlook)**: `5df367d9-…` (multi-tenant public client). SharePoint sibling uses `cb7cf68d-…` — independent consent, scopes, revocation.
- **Harness tenant**: a dedicated Microsoft 365 sandbox mailbox; creds in GitHub Actions secrets (CI) and a local git-ignored `.env` (dev).

### Microsoft Graph scopes (delegated)

`Mail.Read`, `Mail.ReadWrite`, `Calendars.Read`, `Calendars.ReadWrite`, `User.Read`, `offline_access`. Lazy/opt-in: `Mail.Send` (only with `OUTLOOK_ALLOW_SEND=true`). Never requested: anything in the `admin.*` namespace.

## Glossary

- **Profile** — a named per-tenant identity (`OUTLOOK_PROFILE`); namespaces the token cache and the per-profile draft registry. One `mcpServers` entry per tenant in `.mcp.json`.
- **Draft registry** — in-process, per-profile record of drafts this MCP created, so it only ever updates/discards its own drafts and never touches a hand-written draft the user is composing.
- **Device Code flow** — OAuth 2.0 flow against Microsoft Identity: server returns a `user_code` + `verification_url`, the human authenticates in a browser, the refresh token is cached locally.
- **`mcp-microsoft-graph-auth`** — shared library providing the auth primitives (`LoginSessionRegistry`, `TokenStore`, `poll_for_token`) used by both the Outlook and SharePoint MCP servers.
- **Attribution** — every Graph call is made as the signed-in human (no service-account robot identity); the server additionally sets `User-Agent: mcp-server-outlook/<version>` so actions are traceable to this tool.
