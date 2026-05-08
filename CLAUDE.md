<!--
SPDX-License-Identifier: MIT OR Apache-2.0
SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
SPDX-FileContributor: David Koller <david.koller@xmv.de>
-->

# Project conventions — mcp-server-outlook

**Read [ENGINEERING_PRINCIPLES.md](ENGINEERING_PRINCIPLES.md) first.** It is the project-agnostic baseline (language rule, status workflow, AI-as-developer test-harness requirement, source-control rules, documentation baseline). This file only adds notes specific to this repository.

---

## What this repo is

A Model Context Protocol server that lets AI coding agents read and draft email and calendar items in Microsoft 365 Outlook — **without ever auto-sending and without breaking audit attribution**.

Sister project to [`mcp-server-sharepoint`](https://github.com/XMV-Solutions-GmbH/sharepoint-mcp). Same authorship pattern, same OSS template, same auth shape — different surface (mail + calendar instead of files).

Full vision and tool surface in [docs/app-concept.md](docs/app-concept.md). Read it before changing anything that touches the public MCP tool surface.

## Project-specific docs

| Doc | Purpose |
|---|---|
| [docs/app-concept.md](docs/app-concept.md) | Vision, MVP scope, MCP tool surface, auth model, safety semantics, open tech-spike questions |
| [docs/testconcept.md](docs/testconcept.md) | Test-harness strategy for AI-assisted development |
| [docs/howto-oss.md](docs/howto-oss.md) | OSS-template setup notes inherited from the template; trim once they no longer apply |
| [README.md](README.md) | Quickstart for end users (install via `uvx`, configure `.mcp.json`) |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contribution flow |
| [SECURITY.md](SECURITY.md) | Vulnerability disclosure |
| [CHANGELOG.md](CHANGELOG.md) | Keep-a-changelog history |

## Project-specific tracking

**Authoritative tracker: GitHub Issues + GitHub Projects** at <https://github.com/XMV-Solutions-GmbH/outlook-mcp/issues>.

- Labels:
  - `type:feat` / `type:fix` / `type:chore` / `type:docs` / `type:test`
  - `area:auth` / `area:tools` / `area:ci` / `area:packaging` / `area:docs`
  - `priority:p0` / `p1` / `p2`
  - `agent:claude` when an AI agent is the executor.
- Issue body convention: **Context** · **Acceptance criteria** (checkbox list) · **Out of scope** · **Links**.
- Milestones map to releases: `v0.1.0 — MVP`, `v0.2.0`, etc.

The legacy `docs/todo.md` is a frozen artefact from the OSS template; do not extend it. New work goes into Issues.

## Tech stack (in scope for this repo)

- **Python 3.11+**, packaged for `uvx` / `pipx`.
- **Microsoft Graph via raw `httpx`** — same call-shape as `mcp-server-sharepoint`. No msgraph-sdk-python dependency.
- **MCP Python SDK** for the protocol layer.
- **Auth**: OAuth Device Code flow, token cache via OS keyring with plain-file fallback (mode 0600), encrypted-file opt-in.
- **Tests**: pytest + a dedicated Microsoft 365 test tenant. CI runs in GitHub Actions; secrets injected from repo secrets.
- **Lint/format**: ruff, mypy.

## The never-auto-send rule

This repo's defining design constraint, in three layers:

1. **The default install never sends.** Without `OUTLOOK_ALLOW_SEND=true` in the MCP client config, no `ol_email_send_draft` tool is registered AND `Mail.Send` is not in the OAuth scope request. The consent prompt does NOT read "this app can send mail as you" out of the box. This is the compliance posture that lets cautious tenant admins approve the tool.
2. **Send is opt-in, not auto-on.** Setting `OUTLOOK_ALLOW_SEND=true` is a deliberate per-deployment choice in the MCP client config. The opt-in extends the consent screen — the user has to actively approve `Mail.Send` at the next sign-in.
3. **No autonomous send, ever.** Even with the opt-in active, the agent never sends mail without explicit instruction. The send tool requires a `draft_id` referencing a draft already in the user's Drafts folder (written by an earlier `ol_email_create_draft` / `ol_email_update_draft` call). The human reviewer reads the draft in Outlook between create and send.

**Calendar invitations follow the same shape**: events are created with `responseRequested=false` so Microsoft Graph never auto-emails attendees. There is no `send_invitation` tool; the human clicks Send Invitation in Outlook manually if they want to notify attendees.

If a future feature request asks for "auto-send when X" — say no. The opt-in path covers explicit-send use cases; autonomous-send breaks the audit-trail story this server is built around.

For changes around scope handling: see `auth/flow.py:resolve_scopes()` for the lazy-scope semantic that gates `Mail.Send` on the env flag, and `docs/spikes/2026-05-08-v02-drafts-spikes.md` § 1 (revised) for the design discussion.

## License & attribution (this project)

Per [ENGINEERING_PRINCIPLES.md](ENGINEERING_PRINCIPLES.md) §§ 11–12:

- **License**: dual-licensed **MIT OR Apache-2.0** — see [LICENSE-MIT](LICENSE-MIT), [LICENSE-APACHE](LICENSE-APACHE).
- **Copyright holder**: XMV Solutions GmbH.
- **SPDX license identifier** for file headers: `MIT OR Apache-2.0`.

### Header to add to every new source file

For Python, Shell, YAML, TOML, and most languages with `#` line comments:

```text
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: <year> XMV Solutions GmbH
# SPDX-FileContributor: <git user.name> <<git user.email>>
```

For languages with `//` line comments (Go, Rust, JS/TS, Java, …):

```text
// SPDX-License-Identifier: MIT OR Apache-2.0
// SPDX-FileCopyrightText: <year> XMV Solutions GmbH
// SPDX-FileContributor: <git user.name> <<git user.email>>
```

For HTML / Markdown:

```html
<!--
SPDX-License-Identifier: MIT OR Apache-2.0
SPDX-FileCopyrightText: <year> XMV Solutions GmbH
SPDX-FileContributor: <name> <<email>>
-->
```

Read `git config user.name` / `user.email` for the contributor line — that's the human author per German *Urheberrecht*. The line is never overwritten by later editors; new substantial contributors append additional `SPDX-FileContributor` lines.

### What NOT to do

- Never add `Co-Authored-By: Claude …` (or any AI tool) to commit messages.
- Never put AI tool names or versions into source comments.
- Never list an AI as a `SPDX-FileContributor`.

## Project-specific overrides of the engineering baseline

- **PR workflow already triggered (per § 13).** As soon as the package is published to PyPI / installable via `uvx`, the project has external users. Treat `main` as deployable trunk from that moment: feature branches + PRs, branch protection on `main`, CI green required for merge. Until the first published release, direct commits to `main` are acceptable for chores and docs.
- **Test environment (per § 5).** A dedicated Microsoft 365 test mailbox is required for harness tests. Credentials live in GitHub Actions secrets for CI and in a developer-local `.env` (git-ignored) for iterative work. Document the tenant/mailbox in `docs/testconcept.md` once provisioned.
- **No proprietary headers.** This repo is OSS — every header uses `SPDX-License-Identifier: MIT OR Apache-2.0`. The proprietary template variants from sister repos do not apply here.
- **Env var prefix.** Environment variables use the `OUTLOOK_*` prefix (`OUTLOOK_PROFILE`, `OUTLOOK_CLIENT_ID`, `OUTLOOK_TENANT_ID`, `OUTLOOK_AUTH_MODE`, `OUTLOOK_CLIENT_SECRET`, `OUTLOOK_TOKEN_STORE`, `OUTLOOK_TOKEN_PASSPHRASE`, `OUTLOOK_ALLOW_DRAFTS`). The sister project uses `SP_*`; we do not share env vars to avoid accidental cross-contamination when both servers run in the same shell.
