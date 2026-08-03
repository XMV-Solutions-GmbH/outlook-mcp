<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->

# mcp-server-outlook — App Concept

A Model Context Protocol server that lets AI coding agents read and draft email and calendar items in Microsoft 365 Outlook **without ever auto-sending and without breaking audit attribution**.

Sister project to [`mcp-server-sharepoint`](https://github.com/XMV-Solutions-GmbH/sharepoint-mcp). Same authorship pattern, same OSS template, same auth shape — different surface (mail + calendar instead of files).

---

## Why this exists

For operators in multi-tenant consultancy / customer-engagement contexts (the "I'm in three different companies' Microsoft tenants this quarter" reality), the existing options are bad:

- **Account-bound claude.ai connectors** force one tenant per connector — useless if you're in three tenants at once with the same Claude account.
- **IMAP/SMTP scrapers** lose calendar context, lose attribution (mail appears as "anonymous client"), and bypass Microsoft's modern auth.
- **Auto-sending agents** are scary in regulated environments — one wrong tool call and you've sent an email "as you" that you never wrote.

This MCP fixes all three: **local process per tenant, multi-profile**, **Microsoft Graph for full attribution**, **drafts only, send is human-only**.

---

## Core use cases

1. **Read-only triage** — agent scans the user's inbox for actionable mails (questions, tasks, deadlines), surfaces them in a digest. No mutations.
2. **Calendar awareness** — agent reads the user's calendar to know what's coming today/tomorrow, what conflicts exist, where free slots are.
3. **Draft writing** — agent drafts replies or new emails based on the user's instruction (and reads of relevant SharePoint / Linear context). Drafts land in the user's Outlook drafts folder. **The user reviews and sends manually in Outlook.**
4. **Calendar-event drafts** — agent prepares a tentative event (title, attendees, body) as a draft on the user's calendar. User reviews + sends invitation manually.

---

## Non-goals

- **Never autonomous send.** The default install does not register any `send_*` tool and does not request `Mail.Send`. Sending is opt-in via `OUTLOOK_ALLOW_SEND=true` (v0.3+); when enabled, the new `ol_email_send_draft(draft_id)` tool requires an explicit per-draft tool call after the human reviews the draft in Outlook. There is no path where the agent makes a sending decision autonomously. There is no `send_invitation` tool — calendar event drafts are created with `responseRequested=false` so Microsoft Graph never auto-emails attendees; the human clicks Send Invitation in Outlook manually.
- **Not a sync engine.** No local IMAP mirror, no offline cache. Each call hits Microsoft Graph live.
- **Not a Teams / Files / OneNote MCP.** OneDrive personal works incidentally (overlap with sharepoint-mcp's surface). Teams chat, OneNote, Tasks: out of scope. Sibling MCPs if needed.
- **Not an admin tool.** No mailbox provisioning, no permission management, no transport rules.

---

## Tools exposed (MCP surface)

### Read tools (always available)

```text
ol_email_search(query, folder?, from?, modified_after?, has_attachment?)
    → list of (id, subject, from, received_at, snippet, web_url)

ol_email_list_unread(folder="Inbox", limit=50)
    → unread mails sorted by received-at desc

ol_email_list_recent(folder, since, until?)
    → mails in date range

ol_email_read(id, include_attachments=False)
    → full body (text + html), headers, attachments-list

ol_email_get_attachment(message_id, attachment_id)
    → attachment bytes to a local temp file

ol_calendar_search(query, calendar?, from?, to?)
    → events matching query

ol_calendar_list_events(from, to, calendar="primary")
    → events in a date range with attendees, location

ol_calendar_get_event(id, include_attachments=False)
    → full event details

ol_status()
    → list of currently-pending drafts created by this MCP profile
```

### Write tools (opt-in via `OL_ALLOW_DRAFTS=true`)

```text
ol_email_create_draft(to, subject, body, in_reply_to?, cc?, bcc?, attachments?)
    → creates a new draft in the user's Drafts folder; returns draft_id + web_url

ol_email_update_draft(draft_id, subject?, body?, to?, cc?, bcc?, attachments?)
    → updates an existing draft (only those created by this MCP profile)

ol_email_list_drafts(profile_only=True)
    → list drafts created by this MCP profile (or all drafts if profile_only=False)

ol_email_discard_draft(draft_id)
    → deletes a draft created by this MCP profile

ol_email_send_draft(draft_id)
    → sends a draft created by this MCP profile. **Opt-in via OUTLOOK_ALLOW_SEND=true.**
       NOT registered in the default install. NOT autonomous: the draft must already
       exist in Drafts (from an earlier ol_email_create_draft call) and the human can
       review it in Outlook between create and send. v0.3+.

ol_calendar_create_event_draft(subject, start, end, attendees?, body?, location?)
    → creates a tentative event on the user's calendar; sets responseRequested=False
       so no invitations are auto-sent. The user can review and either send invites
       or convert the draft into a proper event manually in Outlook.

ol_calendar_discard_event_draft(event_id)
    → removes an event draft (only those created by this MCP profile)
```

### Explicitly NOT exposed (by design)

- `send_email` / `send_draft` (autonomous) — see `ol_email_send_draft` above for the explicit-send opt-in path; nothing in this server's tool surface sends without an explicit per-draft tool call.
- `send_calendar_invitation` — calendar drafts use `responseRequested=false`, so no auto-emailing. The human clicks Send Invitation in Outlook manually.
- `delete_email` / `archive_email` — read-only on inbox; user manages their own mailbox state.
- Bulk operations on emails the user did not author or did not create as drafts via this MCP — defensive against fat-finger mass changes.

---

## Architecture

```text
┌──────────────────┐      stdio JSON-RPC      ┌─────────────────────┐
│   Claude Code    │ ◄──────────────────────► │  mcp-server-outlook │
│   (or any        │                          │  (Python process,   │
│    MCP client)   │                          │   one per tenant)   │
└──────────────────┘                          └──────────┬──────────┘
                                                         │ Microsoft Graph
                                                         │ (HTTPS + OAuth)
                                                         ▼
                                              ┌────────────────────┐
                                              │    M365 mailbox    │
                                              │      + calendar    │
                                              └────────────────────┘
```

**Runtime:** single Python process per tenant, stdio transport, started via the consuming repo's `.mcp.json`. Stateless except for token cache and the per-profile registry of drafts created by this MCP (so `ol_email_list_drafts(profile_only=True)` works).

**Language:** Python 3.11+. Same dependency stack as `mcp-server-sharepoint`: `httpx`, `keyring`, `cryptography`, `mcp`. No msgraph-sdk-python heavyweight.

**No working directory by default** — drafts live server-side in the user's Drafts folder. Optional `WORKING_DIR` env can be set if a use-case wants attachment staging locally.

---

## Login UX from MCP clients (v0.3, shipped)

> **Replaces the original 4-tool RFC.** An earlier version of this section proposed four tools (`ol_login_begin` / `ol_login_status` / `ol_login_cancel` / `ol_logout`) and a `status="none"` semantic that conflated "never logged in" with "logged in days ago via CLI". Review pass identified two simplifications:
>
> 1. `force=True` on `ol_login_begin` covers the cancel-and-restart case — `ol_login_cancel` was redundant choice for the agent.
> 2. Agents proactively logging users out is a footgun (an agent that decides "session looks stale, let me reset" surprises the user). `ol_logout` is intentionally NOT an MCP tool; logout stays CLI-only.
> 3. `ol_login_status` should *actively probe* the token cache so a user who logged in via CLI hours ago shows as `signed_in`, not `none`.
>
> This section reflects the agreed final 2-tool design that ships in v0.3. See `docs/spikes/2026-05-08-v02-drafts-spikes.md` for the broader v0.2/v0.3 design discussion. Original 4-tool variant is **superseded**; do not re-derive it.

### Design goal

From the AI agent's point of view, the login flow looks like any other tool sequence:

1. Agent calls `ol_login_status()` → if `signed_in`, proceed; if `none`, fall through.
2. Agent calls `ol_login_begin()` → receives the user_code + verification_url, surfaces them to the human, polls Microsoft Identity in the background, blocks until terminal status.
3. After `ol_login_begin` returns `success`, the token is in the same cache CLI-login writes to, ready for any tool call.

No shell-out. No stdout parsing. No separate terminal. Works for headless CLI Claude Code, browser-based MCP clients, and mobile-app clients alike.

### Tool surface (final, v0.3)

```text
ol_login_begin(force=False)  → async
    Drive the OAuth Device Code flow. Returns the session's public_view
    (session_id, user_code, verification_url, verification_url_complete,
    expires_at, time_remaining_s, status, signed_in_user_upn, error)
    after the polling task reaches a terminal state. Streams MCP
    progress notifications during the wait when the client advertises
    the progress capability — bonus channel.

    Idempotent: a non-expired pending session for the profile is
    joined, not duplicated. Concurrent same-profile callers receive
    the same session_id.

    force=True cancels any in-flight session for the profile and
    starts fresh.

ol_login_status()
    Three states the agent can act on:
      "signed_in" — a usable token exists for this profile, regardless
                    of how it got there (CLI login hours ago, tool
                    login just now). Includes signed_in_user_upn.
                    Found via active probe of the token store.
      "pending"  — a Device Code session is in flight from a recent
                    ol_login_begin call. Includes user_code +
                    verification_url + time_remaining_s so the agent
                    can re-display the prompt.
      "none"     — no token, no flow. Agent should call ol_login_begin.
                    Terminal session statuses (failed/expired/cancelled)
                    fold into "none" + a structured error field for
                    diagnostics, keeping the agent's decision tree
                    uniform.
```

Both tools mutate only local state (token cache + in-process registry). Neither touches mailbox state.

### Server-side mechanics

- `ol_login_begin` allocates a `LoginSession` from `mcp-microsoft-graph-auth.LoginSessionRegistry` (process-singleton). Fields: `session_id` (uuid4), `device_code` (server-only — `public_view` strips it before returning), `user_code`, `verification_url`, `verification_url_complete`, `expires_at`, `status`, `signed_in_user_upn`, `error`, `task` (asyncio handle), `started_at`.
- The polling task runs the lib's sync `poll_for_token` via `asyncio.to_thread`. On success: writes token via the configured `TokenStore`, populates the per-profile UPN cache, sets `status=success`. On expiry: sets `status=expired`. On user denial: `failed`.
- `ol_login_status` first calls `outlook_mcp.auth.get_token(profile)` (silent refresh-token round-trip if cached access token is stale). If a token is obtained, returns `signed_in` plus `signed_in_user_upn` (one `/me?$select=userPrincipalName` round-trip on first detection, cached thereafter). Only when no token is obtainable does it fall through to the registry lookup.

### Concurrent / repeat calls

- Two `ol_login_begin` calls for the same profile within the device-code window: return the same in-flight session, do **not** start a second poller.
- `force=True` allows explicitly starting fresh — useful if the human let the code expire and wants a new one immediately.
- Two paths writing to the token cache simultaneously (CLI `login` AND a running MCP server's `ol_login_begin`): "last writer wins" — the lib does NOT file-lock. In practice both paths produce a valid token, so the worst outcome is one of them losing its write. Documented as a caveat in the README; users who want strict correctness run only one path at a time.

### Persistence + restart-mid-flow

Pending sessions live in the MCP server process. If the server restarts before the user completes the Device Code prompt (Claude Code session ends, container redeployed, …), the in-flight session is lost. The agent calls `ol_login_begin` again — the Microsoft side cleans up the abandoned device code automatically. Persisting pending sessions to disk is non-trivial (the asyncio polling task can't be serialised; resuming from a fresh process would need to start a new poll against the original device code) and is deferred. In practice this rarely matters — Device Code flows take 30–60 seconds when the user is active.

### Progress notifications

When the calling MCP client advertises the progress capability, `ol_login_begin` streams periodic `time_remaining_s` countdown updates via the MCP server `Context.report_progress`. Clients without the capability skip silently — bonus channel, not load-bearing. A broken progress channel never fails the tool; the implementation suppresses progress-emit exceptions broadly.

### UX guidance for relaying user_code + verification_url

When surfacing the result to the user, render `user_code` FIRST in its own code block (no labels, no whitespace) and `verification_url` SECOND as a plain auto-link (not in a code block). The user copies the code first, then clicks the link, and pastes into the page that opens — minimises app-switching on mobile. This phrasing is baked into both tools' MCP descriptions.

### Backward compatibility

- The CLI `login` and `logout` subcommands stay. They're documented as the "manual" path; the token cache format is identical between CLI and tool flows.
- A user can `uvx mcp-server-outlook login --profile foo` once and immediately use the MCP server's tools in Claude Code without re-authing.
- Sister project `mcp-server-sharepoint` follows the same 2-tool shape (`sp_login_begin` / `sp_login_status`). The shared `mcp-microsoft-graph-auth` library provides the primitives both projects use.

---

## Authentication

**OAuth 2.0 Device Code Flow** against Microsoft Identity. Same shape as `mcp-server-sharepoint`:

1. First run: `uvx mcp-server-outlook login --profile <name>`
2. Server prints device code + URL → user opens browser, signs in with M365 account
3. Refresh token cached locally via OS keyring (Keychain / Credential Locker / Secret Service); plain JSON file fallback (mode 0600) for headless boxes without keyring
4. Subsequent invocations use the cached refresh token; full re-login every 60–90 days

**Default Entra app (multi-tenant, public client):** XMV publishes one. End users do not need their tenant admin to register a separate app — same pattern as `mcp-server-sharepoint`'s shipped `client_id`. Both MCPs CAN share the same Entra app registration if scopes are unified, but separate registrations is cleaner for per-MCP consent screens.

**Required Microsoft Graph scopes (delegated):**

- `Mail.Read` — read inbox + folders
- `Mail.ReadWrite` — create / update / discard drafts (v0.2)
- `Calendars.Read` — read events
- `Calendars.ReadWrite` — create event drafts (v0.2)
- `User.Read` — basic profile (signed-in user identification)
- `offline_access` — refresh tokens

**Lazy / opt-in scope:**

- `Mail.Send` — added to the OAuth scope request only when `OUTLOOK_ALLOW_SEND=true` is set in the MCP client config (v0.3+). The default install does NOT request this scope; the consent prompt stays drafts-only. Even with the opt-in active, the agent never auto-sends; sending requires an explicit `ol_email_send_draft(draft_id)` call referencing a draft the human has already reviewed.

**Explicitly NOT requested:**

- Anything in the `admin.*` Graph namespace.

**BYO override (Enterprise tenants with strict app allowlisting):**

```bash
OUTLOOK_TENANT_ID=<guid>
OUTLOOK_CLIENT_ID=<guid>
```

Default routing via `common` endpoint when neither is set.

---

## Multi-profile pattern (multi-tenant consultancy)

Same as `mcp-server-sharepoint`. One MCP entry per tenant, namespace via `OUTLOOK_PROFILE`:

```json
{
  "mcpServers": {
    "outlook-anqer": {
      "command": "uvx",
      "args": ["mcp-server-outlook"],
      "env": {
        "OUTLOOK_PROFILE": "anqer",
        "OL_ALLOW_DRAFTS": "true"
      }
    },
    "outlook-xmv": {
      "command": "uvx",
      "args": ["mcp-server-outlook"],
      "env": {
        "OUTLOOK_PROFILE": "xmv"
      }
    }
  }
}
```

Token caches and draft-registries are namespaced by `OUTLOOK_PROFILE`. A second customer = a second `mcpServers` entry. Tools surface as `mcp__outlook-anqer__ol_email_search` etc.

---

## Safety model

Three layers of "don't accidentally do something irreversible":

1. **MCP client confirmation prompts.** Read tools flagged read-only; draft tools flagged "creates draft (no send)" so user sees the difference at the consent prompt.
2. **Drafts opt-in via env.** Without `OL_ALLOW_DRAFTS=true`, the draft-creation tools aren't even registered. The agent literally can't draft.
3. **No send tools — anywhere.** Sending is exclusively a human action in Outlook. This is structural, not config-flag-able. Even with `OL_ALLOW_DRAFTS=true`, sends remain manual.

Plus an architectural defensive: the MCP only updates / discards drafts that *its own profile* created (tracked in the per-profile registry). It cannot accidentally delete a hand-written draft the user is composing.

---

## MVP scope (v0.1)

- Tools: `ol_email_search`, `ol_email_list_unread`, `ol_email_read`, `ol_calendar_search`, `ol_calendar_list_events`, `ol_status`. (Read-only; no draft tools yet.)
- Device code auth, keyring token cache, per-profile separation.
- Python 3.11+, packaged for `uvx` install on PyPI (`mcp-server-outlook`).
- Tests: integration tests against a dedicated test M365 tenant in CI (env-var-injected creds).

Shipped after v0.1 (were originally deferred to v0.2):

- Draft tools (`ol_email_create_draft`, `ol_email_update_draft`, `ol_email_discard_draft`, `ol_email_list_drafts`, `ol_calendar_create_event_draft`, `ol_calendar_discard_event_draft`) — v0.2.
- Resumable upload for large attachments (drafts) — v0.5.
- Attachment download (`ol_email_get_attachment`) — writes one file attachment to a local file. Shipped in the current release.

Deferred / out of scope:

- Send tools — never.
- Search-folder management, mailbox rules, automatic categorisation.
- Teams chat, Tasks (To Do), Planner — separate sibling MCPs if the demand emerges.

---

## Why XMV OSS

- Same arguments as `mcp-server-sharepoint`: Linux-native AI dev workflows that touch M365 are common, the existing tooling is bad, the audit-trail concern is universal.
- Multi-profile pattern reuses the design we already settled on for `sharepoint-mcp`. Lower invention cost.
- Forces internal discipline: "we let agents draft, but never send" is a usable governance line for letting customers (with their own compliance teams) accept agent-assisted email workflows.

---

## Open questions for the tech spike

> **Resolved 2026-05-08 — see [`docs/spikes/2026-05-08-v02-drafts-spikes.md`](spikes/2026-05-08-v02-drafts-spikes.md).** Summary:
>
> 1. **Two Entra apps** (already provisioned). Outlook: `5df367d9-…`. SharePoint: `cb7cf68d-…`. Independent consent, scopes, revocation.
> 2. **Audit attribution** — automatic via `ClientAppId` + `AppDisplayName`; we additionally set `User-Agent: mcp-server-outlook/<version>` on every Graph request.
> 3. **Calendar conflict** — warn-and-create. Response carries a `warnings` array; the human reviews in Outlook.
> 4. **Body format** — Markdown by default, `body_html` opt-in for raw HTML. Conversion server-side via `mistune` in safe mode.
