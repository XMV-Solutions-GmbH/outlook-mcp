<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->

# mcp-server-outlook

[![PyPI version](https://img.shields.io/pypi/v/mcp-server-outlook?color=0E7EE0)](https://pypi.org/project/mcp-server-outlook/)
[![Python versions](https://img.shields.io/pypi/pyversions/mcp-server-outlook?color=0E7EE0)](https://pypi.org/project/mcp-server-outlook/)
[![Downloads](https://img.shields.io/pypi/dm/mcp-server-outlook?label=downloads%2Fmonth&color=0E7EE0)](https://pypi.org/project/mcp-server-outlook/)
[![Licence](https://img.shields.io/badge/licence-MIT%20OR%20Apache--2.0-blue.svg)](https://github.com/XMV-Solutions-GmbH/outlook-mcp/blob/main/LICENSE)
[![CI](https://github.com/XMV-Solutions-GmbH/outlook-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/XMV-Solutions-GmbH/outlook-mcp/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/codecov/c/github/XMV-Solutions-GmbH/outlook-mcp/main)](https://codecov.io/gh/XMV-Solutions-GmbH/outlook-mcp)
[![Contributions welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg)](https://github.com/XMV-Solutions-GmbH/outlook-mcp/issues)

> **In one sentence:** an [MCP](https://modelcontextprotocol.io) server that lets AI coding agents like Claude Code read your Microsoft 365 inbox and calendar — and **draft** emails and meetings on your behalf — **without ever auto-sending and without breaking audit attribution**.

## What is this for?

You're a consultant, contractor, or operator working across multiple Microsoft 365 tenants. You'd love to let AI agents triage your inbox, summarise calendar conflicts, and draft replies — but every existing option is bad:

- **Account-bound claude.ai connectors** force one tenant per connector — useless if you're in three tenants at once with the same Claude account.
- **IMAP/SMTP scrapers** lose calendar context, lose attribution (mail appears as "anonymous client"), bypass modern auth.
- **Auto-sending agents** are scary in regulated environments — one wrong tool call and you've sent an email "as you" that you never wrote.

**`mcp-server-outlook` fixes all three:**

- **Local process per tenant, multi-profile** — run one MCP entry per customer / mailbox; tokens are namespaced.
- **Microsoft Graph for full attribution** — drafts and reads carry the signed-in user's identity in the audit log.
- **Drafts only, send is human-only** — there is no `send_email` tool, anywhere. The agent's reach ends at "draft saved".

Concretely, the agent gets these tools:

| Tool | What the agent does | What ends up in Outlook |
|---|---|---|
| `ol_email_search`, `ol_email_list_unread`, `ol_email_read` | finds and reads inbox | nothing changes |
| `ol_calendar_search`, `ol_calendar_list_events` | reads calendar | nothing changes |
| `ol_status` | shows pending drafts created by this profile | nothing changes |
| *(v0.2)* `ol_email_create_draft`, `ol_email_update_draft` | creates drafts in your Drafts folder | a draft appears — **you** review and click Send |
| *(v0.2)* `ol_calendar_create_event_draft` | creates a tentative event with `responseRequested=False` | a draft event sits on your calendar — **you** send invites |

Every action is attributed to the human who signed in once via Microsoft's standard Device Code login. No service-account "robot" identity. **No `Mail.Send` permission ever requested** — the consent prompt explicitly does NOT include "this app can send mail as you", which is the line tenant admins (and your auditor) actually care about.

## Installation

```bash
pip install mcp-server-outlook
# or, with uv (recommended):
uv tool install mcp-server-outlook
# or, on the fly without installing globally:
uvx mcp-server-outlook --help
```

Requires Python 3.11+. Works on Linux, macOS, Windows.

## Quickstart

### 1. Sign in once (out of band)

```bash
uvx mcp-server-outlook login
```

Output looks like:

```text
Sign in to mcp-server-outlook via the Device Code flow:
Open the URL in a browser and type the code.

     URL:   https://login.microsoft.com/device
     Code:  D2LKUY4AV

Waiting for sign-in...
```

Open the URL in any browser, type the code, sign in with your M365 account. Your refresh token is cached locally — see [Token storage](#token-storage). The MCP server itself never blocks for human interaction afterwards.

### 2. Wire it into Claude Code

In your project's `.mcp.json`:

```json
{
  "mcpServers": {
    "outlook": {
      "command": "uvx",
      "args": ["mcp-server-outlook"]
    }
  }
}
```

Restart Claude Code. The agent now has the `ol_*` read tools available — **read-only by default**.

### 3. Try it

```text
You:    What unread mails do I have today that look actionable?
Agent:  [calls ol_email_list_unread → reads recent ones with ol_email_read]
        Three threads need a reply:
        - Anna (XMV) — asking about your availability for a Friday call
        - Markus (Customer Y) — needs sign-off on the SLA addendum
        - Calendar Bot — confirms tomorrow's standup at 10:00

You:    Read Anna's mail and check my Friday calendar.
Agent:  [calls ol_email_read + ol_calendar_list_events]
        Anna proposes Fri 14:00–15:00. You have a hard conflict 14:30–15:30
        with the Customer Y review. Suggest 13:00 or after 16:00.
```

In v0.2, draft tools become available so the agent can write the reply email or the counter-proposal event for you. **You always click Send.**

## What it can do, in detail

### Read tools (always available)

| Tool | Purpose |
|---|---|
| `ol_email_search(query, folder?, from?, modified_after?, has_attachment?)` | Free-text search over the user's mailbox using Microsoft Graph `$search`. Returns hits with id, subject, from, received-at, snippet, web URL. |
| `ol_email_list_unread(folder="Inbox", limit=50)` | Unread mails in the named folder, newest first. |
| `ol_email_read(id, include_attachments=False)` | Full body (text + html) + headers + attachments-list for a single mail. |
| `ol_calendar_search(query, calendar?, from_date?, to_date?)` | Events matching a free-text query. |
| `ol_calendar_list_events(from_date, to_date, calendar="primary")` | Events in a date range with attendees and location. |
| `ol_status()` | Pending drafts created by this MCP profile (empty in v0.1; populated once draft tools land in v0.2). |

### Write tools — **deferred to v0.2** (opt-in via `OUTLOOK_ALLOW_DRAFTS=true`)

| Tool | Purpose |
|---|---|
| `ol_email_create_draft(to, subject, body, in_reply_to?, cc?, bcc?, attachments?)` | Creates a draft in the user's Drafts folder. Returns `draft_id` + `web_url`. |
| `ol_email_update_draft(draft_id, …)` | Updates a draft created by this profile. |
| `ol_email_list_drafts(profile_only=True)` | Lists drafts created by this profile. |
| `ol_email_discard_draft(draft_id)` | Deletes a draft created by this profile. |
| `ol_calendar_create_event_draft(subject, start, end, attendees?, body?, location?)` | Creates a tentative event with `responseRequested=False` so no invites auto-send. |
| `ol_calendar_discard_event_draft(event_id)` | Removes an event draft created by this profile. |

### Explicitly NOT exposed (by design)

- `send_email` / `send_draft` — human-only action, perform in Outlook UI.
- `send_calendar_invitation` — same.
- `delete_email` / `archive_email` — read-only on inbox; user manages their own mailbox state.
- Bulk operations on mails the user did not author or did not create as drafts via this MCP — defensive against fat-finger mass changes.

### Authentication

- **OAuth 2.0 Device Code flow** against Microsoft Identity (default). You sign in once; the refresh token is cached locally and silently renewed (~60–90 days until full re-login).
- **Bring-your-own-app or use ours.** XMV publishes a multi-tenant Entra app registration that's baked in as the default — same pattern as Azure CLI / GitHub CLI. Tenants with strict app-allowlisting can override via `OUTLOOK_CLIENT_ID` and `OUTLOOK_TENANT_ID` env vars.
- **Token storage** is auto-detected at first use: OS keyring (macOS Keychain / Windows Credential Locker / Linux Secret Service) when available, mode-0600 plain JSON file as fallback (same convention as `gh auth`, `aws configure`). Optional encryption with `OUTLOOK_TOKEN_PASSPHRASE` for paranoid setups or CI.
- **Multi-customer / multi-tenant**: separate `OUTLOOK_PROFILE` per tenant, each with its own token cache.

#### Required Microsoft Graph scopes (delegated, v0.1)

- `Mail.Read` — read inbox + folders
- `Calendars.Read` — read events
- `User.Read` — basic profile (signed-in user identification)
- `offline_access` — refresh tokens

In v0.2 (drafts), `Mail.ReadWrite` and `Calendars.ReadWrite` are added. **`Mail.Send` is never requested**, ever — sends remain a human action in Outlook.

#### Service-principal mode (unattended automation)

For CI / scheduled jobs where no human is in the loop, run with `OUTLOOK_AUTH_MODE=service-principal` (or just set `OUTLOOK_CLIENT_SECRET` — auto-detected). Required env vars: `OUTLOOK_CLIENT_ID`, `OUTLOOK_CLIENT_SECRET`, `OUTLOOK_TENANT_ID`. The app registration must have **Application** Microsoft Graph permissions with admin consent recorded.

Tradeoff: every action is attributed to the *application* principal, NOT a real user. The compliance-friendly default stays delegated user auth — only switch when no human is in the loop.

### Safety model

Three layers of "don't accidentally do something irreversible":

1. **Your MCP client (Claude Code) prompts before each tool call by default.** Read tools are flagged read-only; draft tools are flagged "creates draft (no send)" — you see the difference at the prompt.
2. **Drafts opt-in via env (v0.2).** Without `OUTLOOK_ALLOW_DRAFTS=true`, the draft-creation tools aren't even registered. The agent literally can't draft.
3. **No send tools — anywhere.** Sending is exclusively a human action in Outlook. This is structural, not config-flag-able. Even with `OUTLOOK_ALLOW_DRAFTS=true`, sends remain manual.

The threat model is "your local OS account is trusted" — same as `~/.ssh/id_rsa`, `gh` tokens, `aws` config. The tool isn't designed to defend against host compromise; it's designed to keep audit trails honest under normal use.

## Roadmap

| Version | Status | Theme | Highlights |
|---|---|---|---|
| **v0.1** | 🛠️ in progress | Read-only inbox + calendar | The six `ol_*` read tools, three-layer test harness, Trusted-Publisher PyPI release pipeline, branch-protected `main`. |
| **v0.2** | 📋 planned | Drafts | `ol_email_create_draft` / `ol_email_update_draft` / `ol_email_list_drafts` / `ol_email_discard_draft`, `ol_calendar_create_event_draft` / `ol_calendar_discard_event_draft`, attachment access, per-profile draft registry. |
| **v1.0** | 🎯 stability lock-in | "API stable, production-tested" | After v0.x has been used in real customer environments for ~3–6 months without breaking changes. |

The full ticket-by-ticket plan lives at the [issues page](https://github.com/XMV-Solutions-GmbH/outlook-mcp/issues).

## Multi-profile pattern

For consultancy workflows with multiple Microsoft 365 tenants, give each its own profile so the token caches don't collide:

```json
{
  "mcpServers": {
    "outlook-acme": {
      "command": "uvx",
      "args": ["mcp-server-outlook"],
      "env": { "OUTLOOK_PROFILE": "acme" }
    },
    "outlook-globex": {
      "command": "uvx",
      "args": ["mcp-server-outlook"],
      "env": { "OUTLOOK_PROFILE": "globex" }
    }
  }
}
```

Sign each one in separately:

```bash
uvx mcp-server-outlook login --profile acme
uvx mcp-server-outlook login --profile globex
```

Tools appear in Claude as `mcp__outlook-acme__ol_email_search` etc. Cross-tenant accidents don't happen because the tokens are namespaced.

## BYO Entra app registration

Tenants with strict app-allowlisting can override the bundled multi-tenant default:

```json
{
  "mcpServers": {
    "outlook": {
      "command": "uvx",
      "args": ["mcp-server-outlook"],
      "env": {
        "OUTLOOK_TENANT_ID": "<your-tenant-guid>",
        "OUTLOOK_CLIENT_ID": "<your-app-registration-guid>"
      }
    }
  }
}
```

The app registration must be: multi-tenant or single-tenant, public client (no secret), Device Code flow allowed, with delegated permissions `Mail.Read`, `Calendars.Read`, `User.Read`, `offline_access` (plus `Mail.ReadWrite`, `Calendars.ReadWrite` once v0.2 ships drafts). **Do not grant `Mail.Send`** — this MCP never sends.

## Token storage

Three backends, auto-detected at first use:

| Tier | Backend | When | Setup |
|---|---|---|---|
| 1 | OS keyring | macOS Keychain / Windows Credential Locker / Linux with Secret Service | none |
| 2 | Plain file `~/.cache/outlook-mcp/<profile>/token.json` mode 0600 | Headless Linux default | none |
| 3 | Encrypted file (Fernet, Scrypt KDF) | When `OUTLOOK_TOKEN_PASSPHRASE` is set | env var |

Force a specific backend with `OUTLOOK_TOKEN_STORE=keyring|file|encrypted-file`.

## Troubleshooting

### "No usable credentials"

The cached token expired (refresh tokens last ~60–90 days) or never existed. Run:

```bash
uvx mcp-server-outlook login --profile <name>
```

### Linux: keyring fails / "Secret Service unavailable"

The plain-file backend kicks in automatically — no action needed. If you'd rather have encryption at rest:

```bash
export OUTLOOK_TOKEN_PASSPHRASE='<some-strong-passphrase>'
uvx mcp-server-outlook login --profile <name>
```

## Development

```bash
git clone https://github.com/XMV-Solutions-GmbH/outlook-mcp.git
cd outlook-mcp
uv sync --extra dev

# Unit + integration (no real Microsoft Graph), with coverage reporting
./tests/run_tests.sh

# Harness (real Microsoft 365 sandbox; requires harness-profile login)
./tests/run_tests.sh harness
```

| Document | What's in it |
|---|---|
| [`docs/app-concept.md`](https://github.com/XMV-Solutions-GmbH/outlook-mcp/blob/main/docs/app-concept.md) | Vision, MVP scope, MCP tool surface, auth, safety model |
| [`docs/testconcept.md`](https://github.com/XMV-Solutions-GmbH/outlook-mcp/blob/main/docs/testconcept.md) | Three-layer test strategy (unit / integration / harness) |
| [`ENGINEERING_PRINCIPLES.md`](https://github.com/XMV-Solutions-GmbH/outlook-mcp/blob/main/ENGINEERING_PRINCIPLES.md) | Project-agnostic engineering baseline |
| [`CLAUDE.md`](https://github.com/XMV-Solutions-GmbH/outlook-mcp/blob/main/CLAUDE.md) | Project-specific overrides |

## Sister project

- [`mcp-server-sharepoint`](https://github.com/XMV-Solutions-GmbH/sharepoint-mcp) — same authorship pattern, audit-preserving SharePoint document edits with checkout/checkin.

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](https://github.com/XMV-Solutions-GmbH/outlook-mcp/blob/main/CONTRIBUTING.md) and the [Code of Conduct](https://github.com/XMV-Solutions-GmbH/outlook-mcp/blob/main/CODE_OF_CONDUCT.md) first.

Bug reports and feature requests go to [GitHub Issues](https://github.com/XMV-Solutions-GmbH/outlook-mcp/issues).

## Licence

Dual-licensed under either of:

- Apache License, Version 2.0 ([LICENSE-APACHE](https://github.com/XMV-Solutions-GmbH/outlook-mcp/blob/main/LICENSE-APACHE) or <http://www.apache.org/licenses/LICENSE-2.0>)
- MIT licence ([LICENSE-MIT](https://github.com/XMV-Solutions-GmbH/outlook-mcp/blob/main/LICENSE-MIT) or <http://opensource.org/licenses/MIT>)

at your option.

Unless you explicitly state otherwise, any contribution intentionally submitted for inclusion in this project by you, as defined in the Apache-2.0 license, shall be dual licensed as above, without any additional terms or conditions.

## Contact

- **Organisation**: XMV Solutions GmbH
- **Email**: <oss@xmv.de>
- **Website**: <https://xmv.de/en/oss/>
- **GitHub**: [@XMV-Solutions-GmbH](https://github.com/XMV-Solutions-GmbH)
