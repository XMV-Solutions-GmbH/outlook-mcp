# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""ol_email_create_draft — create a new mail draft in the user's Drafts folder.

Wraps `POST /me/messages`. Microsoft Graph treats a direct POST to
`/me/messages` as a draft (`isDraft: true` is the implicit default
for that endpoint), so the message lands in the Drafts folder
without ever leaving for delivery.

**This server NEVER sends mail.** There is no `send_email`, no
`send_draft`, and never will be. The agent's reach ends at "draft
saved"; the human reviews the draft in Outlook and clicks Send.

Body shape: `body=...` is Markdown (rendered to HTML server-side via
the safe-mode `outlook_mcp.markdown` helper) and `body_html=...` is
raw HTML used as-is. The two are mutually exclusive.

Drafts created via this tool are tracked in the per-profile
DraftRegistry so `ol_status` and the future `ol_email_update_draft` /
`ol_email_discard_draft` tools can identify which drafts belong to
this MCP profile (defensive against accidentally mutating a
hand-typed draft the user is composing).
"""

from __future__ import annotations

from typing import Any

import httpx

from outlook_mcp.auth import get_token
from outlook_mcp.draft_registry import DraftEntry, DraftRegistry, now
from outlook_mcp.markdown import markdown_to_html
from outlook_mcp.tools._common import GRAPH_BASE, auth_headers


def create_draft(
    to: list[str],
    subject: str,
    *,
    body: str | None = None,
    body_html: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> dict[str, Any]:
    """Create a new mail draft in the signed-in user's Drafts folder.

    Returns a dict with `draft_id` (Graph message id, used by
    `ol_email_update_draft` / `ol_email_discard_draft`) and `web_url`
    (the Outlook web URL where the human reviews and clicks Send).

    Body rules:
        - Pass `body` (Markdown, rendered to HTML server-side) OR
          `body_html` (raw HTML used as-is). Not both.
        - Pass neither for an empty draft body.

    Recipient rules:
        - `to` is required and must be a non-empty list of email
          addresses (strings). `cc` and `bcc` are optional lists with
          the same shape.

    Raises:
        ValueError: empty `to` list, empty subject, both body kinds set.
        httpx.HTTPStatusError: non-2xx response from Graph (e.g. 403
            if the cached token doesn't have `Mail.ReadWrite` consented;
            re-run `mcp-server-outlook login` to refresh consent).
        outlook_mcp.auth.AuthRequiredError: no usable cached token.
    """
    if body is not None and body_html is not None:
        raise ValueError(
            "ol_email_create_draft: pass `body` (Markdown) OR `body_html` (raw HTML), not both",
        )
    if not to:
        raise ValueError(
            "ol_email_create_draft: `to` must be a non-empty list of recipient addresses",
        )
    if not subject or not subject.strip():
        raise ValueError("ol_email_create_draft: `subject` must be non-empty")

    if body_html is not None:
        content_type = "html"
        content = body_html
    elif body is not None:
        content_type = "html"
        content = markdown_to_html(body)
    else:
        content_type = "text"
        content = ""

    payload: dict[str, Any] = {
        "subject": subject,
        "body": {"contentType": content_type, "content": content},
        "toRecipients": [_to_recipient(addr) for addr in to],
    }
    if cc:
        payload["ccRecipients"] = [_to_recipient(addr) for addr in cc]
    if bcc:
        payload["bccRecipients"] = [_to_recipient(addr) for addr in bcc]

    token = get_token(profile)
    headers = {**auth_headers(token), "Content-Type": "application/json"}
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        response = client.post(
            f"{GRAPH_BASE}/me/messages",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        message = response.json()
    finally:
        if http is None:
            client.close()

    draft_id = str(message["id"])
    web_url_raw = message.get("webLink")
    web_url = str(web_url_raw) if web_url_raw else None

    DraftRegistry(profile=profile).add(
        DraftEntry(
            kind="email",
            graph_id=draft_id,
            web_url=web_url,
            subject=subject,
            created_at=now(),
        )
    )

    return {"draft_id": draft_id, "web_url": web_url}


def _to_recipient(addr: str) -> dict[str, Any]:
    """Wrap a flat email address into Graph's `{emailAddress: {address}}` shape."""
    return {"emailAddress": {"address": addr}}
