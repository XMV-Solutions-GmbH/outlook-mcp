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

import logging
import os
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from outlook_mcp.auth.flow import send_enabled
from outlook_mcp.tools.calendar_create_event_draft import (
    create_event_draft as _do_calendar_create_event_draft,
)
from outlook_mcp.tools.calendar_discard_event_draft import (
    discard_event_draft as _do_calendar_discard_event_draft,
)
from outlook_mcp.tools.calendar_list_events import list_events as _do_calendar_list_events
from outlook_mcp.tools.calendar_search import search as _do_calendar_search
from outlook_mcp.tools.email_create_draft import create_draft as _do_email_create_draft
from outlook_mcp.tools.email_discard_draft import discard_draft as _do_email_discard_draft
from outlook_mcp.tools.email_list_drafts import list_drafts as _do_email_list_drafts
from outlook_mcp.tools.email_list_unread import list_unread as _do_email_list_unread
from outlook_mcp.tools.email_read import read_email as _do_email_read
from outlook_mcp.tools.email_search import search as _do_email_search
from outlook_mcp.tools.email_send_draft import send_draft as _do_email_send_draft
from outlook_mcp.tools.email_update_draft import update_draft as _do_email_update_draft
from outlook_mcp.tools.status import status as _do_status

PROFILE_ENV = "OUTLOOK_PROFILE"
DEFAULT_PROFILE = "default"
ALLOW_DRAFTS_ENV = "OUTLOOK_ALLOW_DRAFTS"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def _get_profile() -> str:
    return os.environ.get(PROFILE_ENV, DEFAULT_PROFILE)


def drafts_enabled() -> bool:
    """True iff `OUTLOOK_ALLOW_DRAFTS` is set to a recognised truthy value.

    Default (unset / empty / anything else): drafts are NOT enabled,
    matching the read-only-default policy. In v0.1 there are no draft
    tools regardless; this hook exists for v0.2.
    """
    return os.environ.get(ALLOW_DRAFTS_ENV, "").strip().lower() in _TRUE_VALUES


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
            "Search the signed-in user's mailbox via Microsoft Graph "
            "$search. Returns matching mails with id, subject, from, "
            "received-at, snippet, web URL, has-attachments. Read-only "
            "— does not modify any mailbox state. Filter args: folder "
            "(well-known name like 'Inbox'/'Drafts' or folder id), "
            "from_address (sender email), modified_after (ISO date), "
            "has_attachment (bool)."
        ),
    )
    def ol_email_search(
        query: str,
        folder: str | None = None,
        from_address: str | None = None,
        modified_after: str | None = None,
        has_attachment: bool | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        return _do_email_search(
            query,
            folder=folder,
            from_address=from_address,
            modified_after=modified_after,
            has_attachment=has_attachment,
            limit=limit,
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
            "in Outlook."
        ),
    )
    def ol_email_list_unread(
        folder: str = "Inbox",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return _do_email_list_unread(
            folder=folder,
            limit=limit,
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
            "(deferred to v0.2 ol_email_get_attachment)."
        ),
    )
    def ol_email_read(
        message_id: str,
        include_attachments: bool = False,
    ) -> dict[str, Any]:
        return _do_email_read(
            message_id,
            include_attachments=include_attachments,
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
            "clicks Send manually. Returns {draft_id, web_url}. "
            "Body input: pass `body` (Markdown, rendered to HTML "
            "server-side via a safe-mode renderer that strips "
            "javascript: links and inline HTML) OR `body_html` (raw "
            "HTML used as-is). The two are mutually exclusive. "
            "Recipients: `to` is required (non-empty list of email "
            "addresses); `cc` and `bcc` are optional. The draft is "
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
    ) -> dict[str, Any]:
        return _do_email_create_draft(
            to=to,
            subject=subject,
            body=body,
            body_html=body_html,
            cc=cc,
            bcc=bcc,
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
            "Returns {draft_id, web_url}. Marked destructive because the "
            "PATCH overwrites the previous draft state on Graph."
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
    ) -> dict[str, Any]:
        return _do_email_update_draft(
            draft_id,
            subject=subject,
            body=body,
            body_html=body_html,
            to=to,
            cc=cc,
            bcc=bcc,
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


def _build_server() -> FastMCP:
    """Build and return a FastMCP server with the right tools registered."""
    server = FastMCP("mcp-server-outlook")
    register_read_tools(server)
    if drafts_enabled():
        register_write_tools(server)
        if send_enabled():
            register_send_tools(server)
    else:
        # One-line note on stderr so users running uvx interactively
        # see why drafts are absent. Quiet by default to avoid noise
        # in MCP-client-launched contexts (Claude Code captures
        # stderr but doesn't surface it loudly).
        logging.getLogger("outlook-mcp").info(
            "OUTLOOK_ALLOW_DRAFTS not set — read-only mode "
            "(ol_email_create_draft etc. not registered). "
            "Set OUTLOOK_ALLOW_DRAFTS=true to enable drafts.",
        )
        if send_enabled():
            # Send-without-drafts is invalid configuration; warn so the
            # user knows their flag is doing nothing.
            logging.getLogger("outlook-mcp").warning(
                "OUTLOOK_ALLOW_SEND is set but OUTLOOK_ALLOW_DRAFTS is "
                "not — ol_email_send_draft requires drafts to be "
                "enabled (you can't send what you can't draft). The "
                "send tool will NOT be registered.",
            )
    return server


mcp: FastMCP = _build_server()


def run() -> None:
    """Start the MCP server on stdio.

    Blocks until stdin closes.
    """
    mcp.run()


# Suppress the "imported but unused" hint for the sys import — it's
# kept for future stderr-printing use that we may need cross-module.
_ = sys
