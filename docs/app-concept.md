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

- **Never auto-send.** No tool exposes `send_email` or `send_invitation` directly. The agent's reach ends at "draft saved". Human is always in the send-loop.
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

ol_calendar_create_event_draft(subject, start, end, attendees?, body?, location?)
    → creates a tentative event on the user's calendar; sets responseRequested=False
       so no invitations are auto-sent. The user can review and either send invites
       or convert the draft into a proper event manually in Outlook.

ol_calendar_discard_event_draft(event_id)
    → removes an event draft (only those created by this MCP profile)
```

### Explicitly NOT exposed (by design)

- `send_email` / `send_draft` — human-only action, perform in Outlook UI.
- `send_calendar_invitation` — same.
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

## Authentication

**OAuth 2.0 Device Code Flow** against Microsoft Identity. Same shape as `mcp-server-sharepoint`:

1. First run: `uvx mcp-server-outlook login --profile <name>`
2. Server prints device code + URL → user opens browser, signs in with M365 account
3. Refresh token cached locally via OS keyring (Keychain / Credential Locker / Secret Service); plain JSON file fallback (mode 0600) for headless boxes without keyring
4. Subsequent invocations use the cached refresh token; full re-login every 60–90 days

**Default Entra app (multi-tenant, public client):** XMV publishes one. End users do not need their tenant admin to register a separate app — same pattern as `mcp-server-sharepoint`'s shipped `client_id`. Both MCPs CAN share the same Entra app registration if scopes are unified, but separate registrations is cleaner for per-MCP consent screens.

**Required Microsoft Graph scopes (delegated):**

- `Mail.Read` — read inbox + folders
- `Mail.ReadWrite` — create / update / discard drafts (does NOT include send permission — that's `Mail.Send`, intentionally excluded)
- `Calendars.Read` — read events
- `Calendars.ReadWrite` — create event drafts
- `User.Read` — basic profile (signed-in user identification)
- `offline_access` — refresh tokens

**Explicitly NOT requested:**

- `Mail.Send` — not needed; we don't send. Excluding it makes the consent prompt more reassuring (no "this app can send mail as you").
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

Deferred to v0.2:

- Draft tools (`ol_email_create_draft`, `ol_email_update_draft`, `ol_email_discard_draft`, `ol_email_list_drafts`, `ol_calendar_create_event_draft`, `ol_calendar_discard_event_draft`).
- Attachment access (`ol_email_get_attachment`).
- Resumable upload for large attachments.

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

1. **Single Entra app or two** — share the multi-tenant client_id with `mcp-server-sharepoint` (one consent prompt covering both surfaces) or keep separate (clearer per-app scopes)? Trade-off: UX vs cleanliness.
2. **Draft attribution.** Drafts created via Graph appear with the signed-in user's identity. Confirm in audit log that "drafted via mcp-server-outlook user-agent" is visible, so a compliance reviewer can distinguish AI-mediated drafts from hand-typed ones.
3. **Calendar-conflict detection.** Should `ol_calendar_create_event_draft` refuse to create an event that overlaps an existing busy block, or just warn? Probably warn-and-create.
4. **Body format** for drafts: HTML vs Markdown vs plain. Probably support both, default Markdown→HTML rendering server-side via a known-safe converter (`mistune` or similar with whitelist).
