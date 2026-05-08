<!--
SPDX-License-Identifier: MIT OR Apache-2.0
SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
SPDX-FileContributor: David Koller <david.koller@xmv.de>
-->

# Spike: v0.2 drafts — resolutions to the four open tech-spike questions

**Date**: 2026-05-08
**Issue**: [#9](https://github.com/XMV-Solutions-GmbH/outlook-mcp/issues/9)
**Decision summary**:

1. **Two Entra apps**, not one shared with `mcp-server-sharepoint` (de facto already implemented).
2. **Audit-log attribution** is automatic via the Entra app's `appId` + display name; we additionally set a `User-Agent: mcp-server-outlook/<version>` HTTP header for diagnostic traceability.
3. **Calendar conflicts** → **warn-and-create**. The draft is created regardless; the response carries a `warnings` array describing overlaps.
4. **Body format** for drafts → **Markdown by default with HTML opt-in**. Markdown→HTML conversion server-side via `mistune` in safe mode.

The four were carried over from `docs/app-concept.md` § "Open questions for the tech spike" so v0.2 (drafts) had a documented foundation. None of them require code changes in v0.1; #2 has a small follow-up (User-Agent header), and #3 + #4 land alongside the v0.2 draft tools (#8).

---

## 1. Single Entra app or two?

### Question

Should `mcp-server-outlook` and `mcp-server-sharepoint` share a single multi-tenant Entra app registration (one consent screen covering both surfaces), or stay as two separate registrations (per-surface consent)?

### Trade-off

| Path | Win | Cost |
|---|---|---|
| **Shared app** | One consent prompt for users who run both servers. Single `client_id` to refresh. | Bundled scopes (`Mail.Read` + `Files.ReadWrite.All` + `Sites.ReadWrite.All` + `Calendars.Read` …) on every consent screen, even for users who only run one server. Tenant admins are more likely to scrutinise / refuse a single broad-scope app than two narrow ones. Revocation couples both servers. |
| **Two apps** | Clear per-server scopes on each consent screen. Independent revocation. Independent audit trails. Independent BYO override (`OUTLOOK_CLIENT_ID` vs `SP_CLIENT_ID`). | Two consent prompts the first time a user runs both servers. Two app registrations to maintain (renewal, publisher info, …). |

### Decision: **Two apps.**

Already provisioned:

- `mcp-server-outlook` → `appId 5df367d9-4c9b-44fd-9f84-0b4fb1f1268a`, multi-tenant public client, scopes `Mail.Read`, `Mail.ReadWrite`, `Calendars.Read`, `Calendars.ReadWrite`, `User.Read`, `offline_access`.
- `mcp-server-sharepoint` → `appId cb7cf68d-90d5-4841-90a7-de3a40be280b` (existing).

### Rationale

The compliance friction of bundling SharePoint write scopes into an Outlook consent (or vice versa) outweighs the ergonomic cost of a second consent prompt. The two server processes are independently deployable and independently consumed — most users will run one without the other. Coupling them would propagate every reviewability concern about one onto the other.

### Consequences

- The Microsoft Entra publisher-info pages (`https://www.xmv.de/oss/<repo>/{privacy,terms}`) are per-server — already done.
- `scripts/bootstrap-azure-app.sh` in each repo creates its own app — no shared bootstrap.
- A future shared library for the auth helpers (if we factor one out) does **not** mean a shared app registration. The auth code can be shared while the registrations stay separate.

---

## 2. Draft attribution in the audit log

### Question

When an agent creates a draft via `ol_email_create_draft` (or any v0.2 draft tool), can a compliance reviewer of the Microsoft 365 audit log distinguish "drafted via mcp-server-outlook" from "hand-typed in Outlook by the same user"?

### What the audit log already provides

Microsoft 365 audit log entries (`Audit.Exchange` / `Mailbox` workload) for `Update-InboxRule`, `Send`, `Create item`, etc. carry — at minimum:

- `UserId` — the signed-in user (delegated mode) or the application principal (service-principal mode).
- `ClientAppId` — the GUID of the Entra app registration that issued the token. For us: `5df367d9-…`.
- `ClientApplication` / `AppDisplayName` — the human-readable app display name. For us: `mcp-server-outlook`.
- `OperationProperties` — sometimes carries the `User-Agent` HTTP header from the originating request, depending on the Graph endpoint.

So a reviewer looking at the log can already filter `ClientAppId == 5df367d9-…` to see exactly the actions taken via this MCP server. No further work needed for the primary channel.

### Decision: **add a User-Agent header to all Graph requests.**

Use case: a reviewer who's pulling raw Graph diagnostics (Entra sign-in logs, Graph activity logs) often sees the User-Agent string before they see the AppDisplayName. Setting it to `mcp-server-outlook/<version>` makes the trail unmistakable.

### Implementation

Add to `outlook_mcp/tools/_common.py`:

```python
from outlook_mcp import __version__

USER_AGENT = f"mcp-server-outlook/{__version__}"

def auth_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
    }
```

Every existing v0.1 tool (and every v0.2 draft tool) goes through `auth_headers()`, so this is a one-line surface change. Tests update accordingly: assert the `User-Agent` header is present on outbound requests.

### Rationale

- Costs nothing operationally; ships with the next minor.
- Improves the diagnostic trail without depending on Microsoft's audit-log shape (which changes across endpoints and beta/v1.0 boundaries).
- Self-identification is industry-standard etiquette for HTTP clients hitting an external API.

### Consequences

- The httpx default User-Agent (`python-httpx/0.x`) gets replaced by ours. Microsoft's API doesn't care about the value beyond logging.
- A future shared auth helper across `mcp-server-outlook` + `mcp-server-sharepoint` should keep the **per-server** User-Agent; don't unify it. Exception: if both servers ship from the same Python package one day, then `mcp-server-{outlook|sharepoint}/<version>` selectable at the call site.

---

## 3. Calendar-conflict detection in `ol_calendar_create_event_draft`

### Question

When `ol_calendar_create_event_draft` is called with `start` / `end` that overlap an existing busy event on the user's calendar, should the tool **refuse** the draft creation, or **warn and create** anyway?

### Options

| Option | Behaviour | Pro | Con |
|---|---|---|---|
| Refuse | Raises a structured error (e.g. `CalendarConflictError`) and does NOT create the draft. Caller can retry with `force=True` or different times. | Strict — agent literally cannot create overlapping drafts without explicit override. | Breaks the "drafts are harmless, the human reviews in Outlook" mental model. Adds an opinionated check that Outlook itself doesn't impose. |
| Warn-and-create | Creates the draft regardless. Returns `{ event_id, web_url, warnings: [{ type: "overlap", with: <existing event summary> }] }`. | Matches Outlook's own UX (Outlook also warns + creates). The human reviewing the draft in Outlook sees both events side by side and decides. | Requires the agent to actually inspect the warnings — agents that ignore the response field could create messy overlapping events. |
| Configurable | Default warn-and-create; `OUTLOOK_CALENDAR_REFUSE_ON_OVERLAP=true` switches to refuse. | Lets ops teams pick the policy without a code change. | More implementation surface; one more env var to document; users disagree on the default. |

### Decision: **warn-and-create.**

### Rationale

- The MCP server's contract is "drafts are non-destructive — the human reviews and clicks Send in Outlook". A draft that sits on the calendar is a plan, not a commitment. Conflicts happen routinely (a quick chat scheduled over a longer block; the user resolves it manually). Drafting through that conflict mirrors how a human PA would work.
- The tool already returns a structured `warnings` array — same channel can carry the overlap flags. Agents that care can act on it; agents that don't are no worse off than a human who ignored the conflict warning in Outlook.
- A configurable env var is over-engineering for a v0.2 ship. Add it later if a real customer has a genuine policy reason.

### Implementation outline

```text
ol_calendar_create_event_draft(subject, start, end, attendees?, body?, location?)
    → 1. Resolve calendar (default primary).
      2. POST /me/events with `responseRequested: false` → captures id, web_url.
      3. GET /me/calendarView?startDateTime=<start>&endDateTime=<end>
         filtered to events that are not the just-created one. Treat any
         result as an overlap.
      4. Build `warnings = [{ type: "overlap", with: { subject, start, end, organizer } } …]`
         if any overlaps found.
      5. Return { event_id, web_url, warnings }.
```

Step 3 costs one extra Graph call per draft creation. Acceptable.

### Consequences

- Tests must cover both "no overlap → empty warnings" and "overlap → warning entries" paths.
- Out of scope for v0.2: detecting overlaps **in other calendars** (e.g. shared group calendars). v0.2 only reads `/me/calendarView`. If a customer asks for cross-calendar conflict detection, that's v0.3.

---

## 4. Body format for drafts: HTML / Markdown / plain

### Question

What body format does `ol_email_create_draft` accept, and what does it write to Microsoft Graph?

### What Microsoft Graph accepts

`POST /me/messages` accepts a `body` object with two fields: `contentType` (`"text"` or `"html"`) and `content` (string). No native Markdown support — agents that want Markdown rendering have to convert before posting.

### Options

| Path | Pro | Con |
|---|---|---|
| HTML only | One source of truth, no conversion, Outlook renders pixel-perfect. | Agents are bad at writing HTML by hand; tool calls become noisy with `<p>` / `<br>` / `<a>` clutter. |
| Plain text only | Bulletproof. | Loses formatting (bold, lists, links). Looks unprofessional in 2026. |
| Markdown only | Agents write Markdown natively and well. | Requires server-side Markdown→HTML conversion; bug surface for the converter. |
| **Markdown by default + HTML opt-in** | Agents have a comfortable default; power users can pass `body_html` directly when they need precise control (e.g. tables, embedded styles). | Two parameters mean two code paths to test. |

### Decision: **Markdown by default + HTML opt-in.** Render server-side via `mistune` in safe mode.

### Tool surface

```text
ol_email_create_draft(
    to: list[str],
    subject: str,
    body: str | None = None,         # Markdown (rendered to HTML server-side)
    body_html: str | None = None,    # raw HTML (used as-is)
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    in_reply_to: str | None = None,
    attachments: list[Attachment] | None = None,
)
```

`body` and `body_html` are mutually exclusive. Passing both is a `ValueError` at the tool boundary. Passing neither produces an empty body.

### Why `mistune`

- Pure-Python, single dependency, no C extensions, MIT-licensed.
- Built-in safe mode (`escape=True`) blocks raw HTML and dangerous URI schemes (`javascript:` etc.) — important because we don't want an agent to accidentally embed a phishing payload.
- Active maintenance, stable API for years.
- ~50 KB installed footprint. Negligible.

Alternative: `markdown` (the de-facto Python lib) has more extensions but a larger surface. `mistletoe`, `markdown-it-py` were considered; both fine; `mistune` wins on minimal-deps + safe-mode-built-in.

### Conversion pipeline

```python
import mistune

_md_renderer = mistune.create_markdown(escape=True, hard_wrap=False)

def markdown_to_html(md: str) -> str:
    return _md_renderer(md)
```

Then in the tool:

```python
if body_html is not None:
    content_type, content = "html", body_html
elif body is not None:
    content_type, content = "html", markdown_to_html(body)
else:
    content_type, content = "text", ""
```

`escape=True` means HTML in the Markdown source gets escaped, not rendered. Agents that want HTML must use `body_html` explicitly — clear separation, no surprises.

### Rationale

- Markdown matches how agents talk. Asking an agent to emit `<p>Hello</p>` is asking for noise.
- `body_html` as an explicit escape valve covers the cases Markdown can't (precise attendee tables, signed footers, branded HTML emails).
- Safe-mode rendering protects against the most common Markdown footguns (raw `<script>`, `javascript:` links).

### Consequences

- `mistune>=3` joins the runtime deps in `pyproject.toml`.
- Unit tests for the Markdown→HTML conversion: cover headings, lists, links (including the `javascript:` reject case), bold/italic, code blocks, line breaks. Tests for `body_html` direct path. Tests for the mutual-exclusion ValueError.
- Update tests: any test that creates a draft via `ol_email_create_draft` should default to Markdown input and assert the resulting `contentType: "html"` outbound payload.

---

## Follow-ups landed by this spike

1. **Bootstrap-Azure-App** is already done with two separate apps; no further Entra-side action needed.
2. **User-Agent header** lands as a tiny PR before #8 starts (or as the first commit of #8).
3. **`ol_calendar_create_event_draft` warn-and-create logic** is part of #8.
4. **`mistune` integration + `body` / `body_html` split** is part of #8.

This spike closes #9. The four bullets above are recorded as acceptance-criteria checkboxes on #8.
