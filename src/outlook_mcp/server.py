# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""MCP server: registers the `ol_*` tools with FastMCP and runs on stdio.

Each tool is wrapped with explicit `ToolAnnotations` so MCP clients
(notably Claude Code's permission system) can render the right
prompt — read-only tools get a different treatment from draft-creating
ones. The annotations are part of our security story: if we lie
here, the client can't make sensible safety decisions.

**Read-only by default in v0.1.** Draft tools are not implemented in
v0.1; v0.2 will add them gated by `OUTLOOK_ALLOW_DRAFTS=true`. The
gating constant is exposed here so downstream tooling can import it
without the registration plumbing changing shape.

**No `send` tools — anywhere, ever.** Sending mail or sending an
event invitation is exclusively a human action in Outlook. This is
structural to the project and is NOT config-flag-able. Even with
draft tools enabled in v0.2, no `send_*` tool will be added.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from outlook_mcp.auth.flow import (
    ALLOW_DRAFTS_ENV as _AUTH_FLOW_ALLOW_DRAFTS_ENV,
)
from outlook_mcp.auth.flow import (
    OutlookConsentNotConfiguredError,
    validate_consent_config,
)
from outlook_mcp.tools.calendar_create_event_draft import (
    create_event_draft as _do_calendar_create_event_draft,
)
from outlook_mcp.tools.calendar_discard_event_draft import (
    discard_event_draft as _do_calendar_discard_event_draft,
)
from outlook_mcp.tools.calendar_list_events import list_events as _do_calendar_list_events
from outlook_mcp.tools.calendar_search import search as _do_calendar_search
from outlook_mcp.tools.email_create_draft import create_draft as _do_email_create_draft
from outlook_mcp.tools.email_delete import delete_message as _do_email_delete
from outlook_mcp.tools.email_discard_draft import discard_draft as _do_email_discard_draft
from outlook_mcp.tools.email_list_drafts import list_drafts as _do_email_list_drafts
from outlook_mcp.tools.email_list_unread import list_unread as _do_email_list_unread
from outlook_mcp.tools.email_read import read_email as _do_email_read
from outlook_mcp.tools.email_search import search as _do_email_search
from outlook_mcp.tools.email_send_draft import send_draft as _do_email_send_draft
from outlook_mcp.tools.email_update_draft import update_draft as _do_email_update_draft
from outlook_mcp.tools.login_begin import login_begin as _do_login_begin
from outlook_mcp.tools.login_status import login_status as _do_login_status
from outlook_mcp.tools.status import status as _do_status

PROFILE_ENV = "OUTLOOK_PROFILE"
DEFAULT_PROFILE = "default"
# Re-exported here for backwards-compat with v0.3.x importers.
ALLOW_DRAFTS_ENV = _AUTH_FLOW_ALLOW_DRAFTS_ENV


def _get_profile() -> str:
    return os.environ.get(PROFILE_ENV, DEFAULT_PROFILE)


def drafts_enabled() -> bool:
    """True iff `OUTLOOK_ALLOW_DRAFTS` is set to exactly `"true"`.

    Strict parser since v0.4 — raises `OutlookConsentNotConfiguredError`
    if the env var is unset, empty, or has a value other than `true`
    or `false`. There is no implicit default; the operator must
    consciously decide. See issue #37 for the user-side rationale.
    """
    return validate_consent_config().drafts


def shared_mailboxes_enabled() -> bool:
    """True iff `OUTLOOK_ALLOW_SHARED_MAILBOXES=true`.

    Optional flag (v0.5, #45): unset/empty = False; existing installs
    keep their /me-only behaviour. When True, the email read tools
    accept an optional `mailbox` argument that routes calls to
    `/users/{upn}/...`, and the OAuth scope adds Mail.ReadWrite.Shared.
    """
    return validate_consent_config().shared_mailboxes


def delete_enabled() -> bool:
    """True iff `OUTLOOK_ALLOW_DELETE=true`.

    Optional flag (v0.5, #45): unset/empty = False. When True, the
    `ol_email_delete` tool is registered. Independent of the other
    three consent flags — an operator can enable delete on the
    signed-in mailbox without shared-mailbox access, or read shared
    mailboxes without enabling delete.
    """
    return validate_consent_config().delete


def _guard_mailbox(mailbox: str | None) -> None:
    """Refuse a non-None `mailbox` arg when shared mailboxes are disabled.

    Centralised so each email-tool wrapper just calls this; the runtime
    error message is consistent across tools. The MCP schema still
    advertises the `mailbox` parameter on every tool — agents see it
    and may try to use it. Without this guard the impl would route to
    `/users/{upn}/...` and Microsoft Graph would 403 with a confusing
    error; the explicit refusal here tells the operator that it's an
    XMV-side opt-in flag rather than a Microsoft permission issue.
    """
    if mailbox is not None and not shared_mailboxes_enabled():
        raise PermissionError(
            "The `mailbox` parameter is only available when "
            "OUTLOOK_ALLOW_SHARED_MAILBOXES=true. Set the flag in your "
            ".mcp.json env block (and re-sign-in to grant "
            "Mail.ReadWrite.Shared on the consent screen) to enable "
            "shared-mailbox access.",
        )


def register_read_tools(mcp_instance: FastMCP) -> None:
    """Register the unconditionally-available read tools on `mcp_instance`."""

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="Search Outlook Email",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "Search a mailbox via Microsoft Graph $search. Returns "
            "matching mails with id, subject, from, received-at, "
            "snippet, web URL, has-attachments. Read-only. Filter args: "
            "folder (well-known name like 'Inbox'/'Drafts' or folder id), "
            "from_address (sender email), modified_after (ISO date), "
            "has_attachment (bool). "
            "`mailbox` (optional, default None) targets a shared mailbox "
            "via its UPN (e.g. 'sekretariat@xmv.de'). Only usable when "
            "OUTLOOK_ALLOW_SHARED_MAILBOXES=true; otherwise raises. The "
            "signed-in user must have FullAccess on the target mailbox "
            "(typically granted via Exchange Add-MailboxPermission)."
        ),
    )
    def ol_email_search(
        query: str,
        folder: str | None = None,
        from_address: str | None = None,
        modified_after: str | None = None,
        has_attachment: bool | None = None,
        limit: int = 25,
        mailbox: str | None = None,
    ) -> list[dict[str, Any]]:
        _guard_mailbox(mailbox)
        return _do_email_search(
            query,
            folder=folder,
            from_address=from_address,
            modified_after=modified_after,
            has_attachment=has_attachment,
            limit=limit,
            mailbox=mailbox,
            profile=_get_profile(),
        )

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="List Unread Outlook Email",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "List unread mails in `folder` (default 'Inbox'), newest "
            "first, up to `limit`. Returns each mail with id, subject, "
            "from, received-at, snippet, web URL, has-attachments. "
            "Read-only — does NOT mark any mail read; the user does that "
            "in Outlook. "
            "`mailbox` (optional, default None) targets a shared mailbox "
            "via its UPN. Only usable when "
            "OUTLOOK_ALLOW_SHARED_MAILBOXES=true; otherwise raises."
        ),
    )
    def ol_email_list_unread(
        folder: str = "Inbox",
        limit: int = 50,
        mailbox: str | None = None,
    ) -> list[dict[str, Any]]:
        _guard_mailbox(mailbox)
        return _do_email_list_unread(
            folder=folder,
            limit=limit,
            mailbox=mailbox,
            profile=_get_profile(),
        )

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="Read Outlook Email",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "Fetch a single mail by Graph id with full body (text + "
            "html), all headers (to/cc/bcc/from/replyTo/conversationId/"
            "internetMessageId), and attachment list. Read-only — does "
            "NOT mark the mail read. Pass `include_attachments=True` "
            "to include attachment metadata (id, name, content_type, "
            "size, is_inline); attachment bytes are NOT downloaded "
            "(deferred to v0.2 ol_email_get_attachment). "
            "`mailbox` (optional, default None) targets a shared mailbox "
            "via its UPN. Only usable when "
            "OUTLOOK_ALLOW_SHARED_MAILBOXES=true; otherwise raises."
        ),
    )
    def ol_email_read(
        message_id: str,
        include_attachments: bool = False,
        mailbox: str | None = None,
    ) -> dict[str, Any]:
        _guard_mailbox(mailbox)
        return _do_email_read(
            message_id,
            include_attachments=include_attachments,
            mailbox=mailbox,
            profile=_get_profile(),
        )

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="Search Outlook Calendar",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "Search calendar events by free-text query against the "
            "signed-in user's calendar. Returns matching events with "
            "id, subject, organizer, start, end, location, attendees, "
            "web URL, is_all_day, is_cancelled. Read-only. Optional "
            "`calendar` (well-known or id, default primary), "
            "`from_date` / `to_date` (ISO 8601). For windowed listing "
            "ordered by start time, prefer ol_calendar_list_events."
        ),
    )
    def ol_calendar_search(
        query: str,
        calendar: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        return _do_calendar_search(
            query,
            calendar=calendar,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            profile=_get_profile(),
        )

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="List Outlook Calendar Events",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "List events on `calendar` (default 'primary') between "
            "`from_date` and `to_date` (ISO 8601 datetimes), sorted by "
            "start ascending. Recurring events are expanded into their "
            "individual occurrences within the window. Returns each "
            "event with id, subject, organizer, start, end, location, "
            "attendees, web URL, is_all_day, is_cancelled. Read-only."
        ),
    )
    def ol_calendar_list_events(
        from_date: str,
        to_date: str,
        calendar: str = "primary",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return _do_calendar_list_events(
            from_date=from_date,
            to_date=to_date,
            calendar=calendar,
            limit=limit,
            profile=_get_profile(),
        )

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="List Outlook Drafts Created by this Profile",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "List drafts (mails + calendar events) this MCP profile has "
            "created. Each entry has kind ('email' or 'event'), "
            "graph_id, web_url, subject, created_at. Read-only. "
            "In v0.1 this is always an empty list — the draft-creating "
            "tools land in v0.2 (gated by OUTLOOK_ALLOW_DRAFTS=true)."
        ),
    )
    def ol_status() -> list[dict[str, Any]]:
        return _do_status(profile=_get_profile())

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="List Outlook Email Drafts",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "List drafts in the user's Drafts folder. With "
            "`profile_only=True` (default): only drafts this MCP "
            "profile created (sourced from the local registry, no "
            "Graph call). With `profile_only=False`: all drafts in "
            "the Drafts folder via Graph, including hand-typed ones; "
            "each entry's `created_by_this_profile` flag tells the "
            "agent whether it owns that draft (i.e. whether "
            "ol_email_update_draft / ol_email_discard_draft will "
            "accept the id). Read-only."
        ),
    )
    def ol_email_list_drafts(
        profile_only: bool = True,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return _do_email_list_drafts(
            profile_only=profile_only,
            limit=limit,
            profile=_get_profile(),
        )

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="Outlook Login Status",
            readOnlyHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "Return the current Microsoft 365 sign-in status for "
            "this profile. Three states: `signed_in` (a usable token "
            "exists, regardless of how it got there — CLI login, "
            "ol_login_begin tool, even days ago), `pending` (a "
            "Device Code flow is in flight from a recent "
            "ol_login_begin call; the response carries `user_code` + "
            "`verification_url` so the agent can re-display the "
            "prompt), or `none` (no token, no flow — the agent "
            "should call ol_login_begin). Read-only: actively probes "
            "the token store + does at most one `/me` round-trip on "
            "a fresh signed_in to learn the UPN. "
            "AGENT_INSTRUCTIONS: When status='pending', present the verification "
            "code to the user inside a fenced code block (so it can be copied "
            "with one click) and present the verification URL as a plain "
            "markdown link on its own line. Do not paraphrase, do not embed "
            "the code inside prose, do not wrap the URL in bold. Same format "
            "as ol_login_begin."
        ),
    )
    def ol_login_status() -> dict[str, Any]:
        return _do_login_status(profile=_get_profile())

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="Outlook Login Begin",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "Drive the OAuth Device Code flow as an MCP tool. "
            "Surfaces `user_code` + `verification_url` to the agent "
            "(and via the agent to the user) and polls Microsoft "
            "Identity in the background until the user completes "
            "sign-in OR the device code expires (~15 min cap). "
            "Idempotent: a non-expired pending session for the "
            "profile is returned as-is unless `force=True`. "
            "`force=True` cancels the in-flight session and starts a "
            "fresh flow. On the way, the tool streams progress "
            "notifications (time-remaining countdown) when the MCP "
            "client advertises the progress capability — bonus "
            "channel; clients without skip silently. Returns the "
            "session's public view: `session_id`, `user_code`, "
            "`verification_url`, `verification_url_complete`, "
            "`expires_at`, `time_remaining_s`, `status`, "
            "`signed_in_user_upn`, `error`. "
            "AGENT_INSTRUCTIONS: Present the verification code to the user "
            "inside a fenced code block (so it can be copied with one click) "
            "and present the verification URL as a plain markdown link on "
            "its own line. Do not paraphrase, do not embed the code inside "
            "prose, do not wrap the URL in bold. Example:\n\n"
            "    Code:\n"
            "    ```\n"
            "    ABCD-1234\n"
            "    ```\n\n"
            "    Sign-in URL: https://login.microsoftonline.com/...\n\n"
            "Rationale: in a chat UI, a code inside a fenced block gets a "
            "one-click copy button; a bare URL becomes clickable; bold-wrapped "
            "links and inline codes do not."
        ),
    )
    async def ol_login_begin(
        force: bool = False,
        ctx: Context[Any, Any] | None = None,
    ) -> dict[str, Any]:
        return await _do_login_begin(
            profile=_get_profile(),
            force=force,
            ctx=ctx,
        )


def register_write_tools(mcp_instance: FastMCP) -> None:
    """Register the gated draft-creating tools on `mcp_instance`.

    Only invoked when `OUTLOOK_ALLOW_DRAFTS` is truthy. The functions
    themselves are real implementations; the gating is purely about
    whether the agent is offered them at tools/list time.

    None of these tools sends mail or sends a calendar invitation.
    `Mail.Send` is not a permission this server ever requests.
    """

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="Create Outlook Email Draft",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
        description=(
            "Create a new mail draft in the user's Drafts folder. The "
            "draft is NOT sent — the human reviews it in Outlook and "
            "clicks Send manually. Returns {draft_id, web_url, "
            "attachments?}. "
            "Body input: pass `body` (Markdown, rendered to HTML "
            "server-side via a safe-mode renderer that strips "
            "javascript: links and inline HTML) OR `body_html` (raw "
            "HTML used as-is). The two are mutually exclusive. "
            "Recipients: `to` is required (non-empty list of email "
            "addresses); `cc` and `bcc` are optional. Attachments "
            "(optional): list of dicts, each with `name` (filename in "
            "mail) and exactly one of `content_path` (local file path), "
            "`content_bytes_b64` (already-base64-encoded raw bytes), "
            "or `content_url` (http/https URL — server downloads). "
            "Optional `content_type` (MIME) on each; inferred from "
            "filename extension if absent. Files >3 MiB use Graph's "
            "resumable upload session automatically. The draft is "
            "tracked in this profile's draft registry — visible via "
            "ol_status."
        ),
    )
    def ol_email_create_draft(
        to: list[str],
        subject: str,
        body: str | None = None,
        body_html: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return _do_email_create_draft(
            to=to,
            subject=subject,
            body=body,
            body_html=body_html,
            cc=cc,
            bcc=bcc,
            attachments=attachments,
            profile=_get_profile(),
        )

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="Update Outlook Email Draft",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "Patch fields on a draft this MCP profile created. Only "
            "drafts whose draft_id is in this profile's draft registry "
            "can be updated — hand-typed drafts in Outlook are off-limits. "
            "Field semantics: pass `subject` / `body` / `body_html` to "
            "set; pass None or omit to leave unchanged. `to` / `cc` / "
            "`bcc`: None = unchanged, [] = clear, non-empty list = set. "
            "`body` and `body_html` are mutually exclusive per call. "
            "`add_attachments` (optional): same shape as the "
            "ol_email_create_draft `attachments` parameter — additive, "
            "doesn't replace existing attachments. `remove_attachment_ids` "
            "(optional): list of attachment ids to delete (ids come back "
            "from create / from the result of an earlier "
            "ol_email_update_draft). Returns {draft_id, web_url, "
            "added_attachments?, removed_attachment_ids?}. Marked "
            "destructive because the PATCH overwrites the previous "
            "draft state on Graph."
        ),
    )
    def ol_email_update_draft(
        draft_id: str,
        subject: str | None = None,
        body: str | None = None,
        body_html: str | None = None,
        to: list[str] | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        add_attachments: list[dict[str, Any]] | None = None,
        remove_attachment_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return _do_email_update_draft(
            draft_id,
            subject=subject,
            body=body,
            body_html=body_html,
            to=to,
            cc=cc,
            bcc=bcc,
            add_attachments=add_attachments,
            remove_attachment_ids=remove_attachment_ids,
            profile=_get_profile(),
        )

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="Discard Outlook Email Draft",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "Delete a draft this MCP profile created. Refuses to "
            "delete drafts not in this profile's draft registry — "
            "hand-typed drafts in Outlook are off-limits. Idempotent: "
            "re-deleting a draft already gone server-side is a "
            "silent no-op (the registry entry is cleaned up either "
            "way). Returns no value on success."
        ),
    )
    def ol_email_discard_draft(draft_id: str) -> None:
        _do_email_discard_draft(draft_id, profile=_get_profile())

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="Create Outlook Calendar Event Draft",
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
        description=(
            "Create a tentative event on the user's calendar with "
            "responseRequested=False (Microsoft Graph does NOT email "
            "any invitations). The event lands as a tentative plan; "
            "the human reviews it in Outlook and clicks Send "
            "Invitation manually if attendees should be notified. "
            "Returns {event_id, web_url, warnings}. `warnings` is a "
            "list of overlap warnings — events already on the user's "
            "calendar that intersect [start, end]. The draft is "
            "created regardless of overlaps; the agent decides "
            "whether to keep, edit, or roll back via "
            "ol_calendar_discard_event_draft. Body input mirrors "
            "ol_email_create_draft (Markdown via `body` or raw HTML "
            "via `body_html`, mutually exclusive)."
        ),
    )
    def ol_calendar_create_event_draft(
        subject: str,
        start: str,
        end: str,
        time_zone: str = "UTC",
        attendees: list[str] | None = None,
        body: str | None = None,
        body_html: str | None = None,
        location: str | None = None,
    ) -> dict[str, Any]:
        return _do_calendar_create_event_draft(
            subject=subject,
            start=start,
            end=end,
            time_zone=time_zone,
            attendees=attendees,
            body=body,
            body_html=body_html,
            location=location,
            profile=_get_profile(),
        )

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="Discard Outlook Calendar Event Draft",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "Delete a calendar event this MCP profile created. "
            "Refuses to delete events not in this profile's draft "
            "registry — hand-created events in Outlook are off-limits. "
            "Idempotent: re-deleting an event already gone "
            "server-side is a silent no-op (the registry entry is "
            "cleaned up either way). Returns no value on success."
        ),
    )
    def ol_calendar_discard_event_draft(event_id: str) -> None:
        _do_calendar_discard_event_draft(event_id, profile=_get_profile())


def register_send_tools(mcp_instance: FastMCP) -> None:
    """Register the send tool. Only invoked when both
    `OUTLOOK_ALLOW_DRAFTS` AND `OUTLOOK_ALLOW_SEND` are truthy.

    Send is opt-in. The default install does NOT register this tool
    and does NOT request `Mail.Send` at OAuth time. See
    `auth/flow.py:resolve_scopes` for the lazy-scope semantic and
    `docs/spikes/2026-05-08-v02-drafts-spikes.md` § 1 (revised) for
    the design discussion.

    Even with the opt-in active, the agent never auto-sends. The
    tool requires a `draft_id` from this profile's DraftRegistry —
    a draft the human can review in Outlook between the
    create-draft call and this send call.
    """

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="Send Outlook Email Draft",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        ),
        description=(
            "Send a draft this MCP profile created. Refuses to send "
            "drafts not in this profile's draft registry. Sending is "
            "irreversible — the draft moves from Drafts to Sent Items "
            "and is delivered to recipients. Only registered when the "
            "MCP client config sets OUTLOOK_ALLOW_SEND=true (in "
            "addition to OUTLOOK_ALLOW_DRAFTS=true). The agent does "
            "NOT send autonomously: the human reviews the draft in "
            "Outlook after ol_email_create_draft / "
            "ol_email_update_draft, then asks the agent to call this "
            "tool with the specific draft_id. Returns "
            "{draft_id, sent_at}."
        ),
    )
    def ol_email_send_draft(draft_id: str) -> dict[str, Any]:
        return _do_email_send_draft(draft_id, profile=_get_profile())


def register_delete_tools(mcp_instance: FastMCP) -> None:
    """Register `ol_email_delete`. Only invoked when `OUTLOOK_ALLOW_DELETE=true`.

    Independent of the drafts/send chain (closes outlook-mcp #45): an
    operator might want to delete received messages without enabling
    drafts at all, or vice versa. The `mailbox` parameter inside the
    tool has its own guard (`OUTLOOK_ALLOW_SHARED_MAILBOXES`), so the
    four flags combine cleanly:

      DRAFTS  SEND  SHARED_MAILBOXES  DELETE   → what registers
      ------- ----- ----------------- -------- --------------------
      false   *     *                 *        read tools only
      true    false *                 *        + drafts (no send)
      true    true  *                 *        + send
      *       *     true              *        read tools accept mailbox=
      *       *     *                 true     + ol_email_delete
    """

    @mcp_instance.tool(
        annotations=ToolAnnotations(
            title="Delete Outlook Email",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
            openWorldHint=False,
        ),
        description=(
            "Delete a message by Graph id. Destructive — moves the "
            "message to Deleted Items by default, or to Recoverable "
            "Items (purges) when `permanent=true`. The user (or admin) "
            "can restore from Deleted Items via the Outlook web UI "
            "within the tenant's retention window; permanent=true "
            "skips that and goes straight to the purges subfolder.\n\n"
            "Only registered when OUTLOOK_ALLOW_DELETE=true. The "
            "`mailbox` parameter additionally requires "
            "OUTLOOK_ALLOW_SHARED_MAILBOXES=true. Idempotent: "
            "re-deleting an already-deleted message is a no-op "
            "(Graph 404 swallowed).\n\n"
            "Returns `{message_id, mailbox, permanent}` for "
            "audit-trail correlation.\n\n"
            "Tip: to discard a draft you created via "
            "ol_email_create_draft, use ol_email_discard_draft "
            "instead — it enforces per-profile draft ownership."
        ),
    )
    def ol_email_delete(
        message_id: str,
        mailbox: str | None = None,
        permanent: bool = False,
    ) -> dict[str, Any]:
        _guard_mailbox(mailbox)
        return _do_email_delete(
            message_id,
            mailbox=mailbox,
            permanent=permanent,
            profile=_get_profile(),
        )


def _build_server() -> FastMCP:
    """Build and return a FastMCP server with the right tools registered.

    Validates all four consent env vars up-front via
    `validate_consent_config()` — if any strictly-required one is
    invalid (DRAFTS, SEND-when-DRAFTS=true) or any optional one has a
    typo (SHARED_MAILBOXES, DELETE), the function raises
    `OutlookConsentNotConfiguredError` with a clear onboarding-help
    message. The exception is allowed to propagate so the operator
    sees it on stderr; no silent read-only fallback.
    """
    cfg = validate_consent_config()
    server = FastMCP("mcp-server-outlook")
    register_read_tools(server)
    if cfg.drafts:
        register_write_tools(server)
        if cfg.send:
            register_send_tools(server)
    if cfg.delete:
        register_delete_tools(server)
    return server


# Build at module-import time so MCP-client launchers (uvx, etc.)
# get the consent-validation error immediately on startup rather
# than mid-protocol-handshake.
try:
    mcp: FastMCP = _build_server()
except OutlookConsentNotConfiguredError as err:
    # Print the help text to stderr so MCP-client log windows show
    # it verbatim — the message IS the onboarding doc. Then re-raise
    # so the process exits non-zero.
    sys.stderr.write(str(err) + "\n")
    sys.stderr.flush()
    raise


def run() -> None:
    """Start the MCP server on stdio.

    Blocks until stdin closes.
    """
    mcp.run()


# Suppress the "imported but unused" hint for the sys import — it's
# kept for future stderr-printing use that we may need cross-module.
_ = sys
