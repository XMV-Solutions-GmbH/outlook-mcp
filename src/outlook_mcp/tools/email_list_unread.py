# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""ol_email_list_unread — list unread mails in a mail folder.

Wraps `GET /me/mailFolders/{folder}/messages` with the documented
filter `isRead eq false`, sorted by `receivedDateTime desc`. Read-only,
idempotent. The well-known folder name `Inbox` is the default; any
other Graph well-known folder (`Drafts`, `SentItems`, etc.) or a
folder-id works too.
"""

from __future__ import annotations

from typing import Any

import httpx

from outlook_mcp.auth import get_token
from outlook_mcp.tools._common import GRAPH_BASE, auth_headers, mailbox_path


def list_unread(
    *,
    folder: str = "Inbox",
    limit: int = 50,
    mailbox: str | None = None,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """List unread messages in `folder`, newest first.

    `mailbox=None` (default): the signed-in user's mailbox (`/me/...`).
    `mailbox="<upn>"`: a shared mailbox the signed-in user has
    FullAccess on (`/users/{upn}/...`). The MCP-tool wrapper enforces
    that `mailbox` is only usable when
    `OUTLOOK_ALLOW_SHARED_MAILBOXES=true`.

    Returns at most `limit` entries with the same shape as
    `ol_email_search`. Empty list is valid (zero unread).

    Raises:
        ValueError: non-positive limit, empty folder, or empty mailbox.
        httpx.HTTPStatusError: 404 if `folder` doesn't exist; 403 if
            `mailbox` is set but the signed-in user has no FullAccess
            on it; other non-2xx as raised by Microsoft.
        outlook_mcp.auth.AuthRequiredError: no cached token.
    """
    if not folder or not folder.strip():
        raise ValueError("ol_email_list_unread requires a non-empty folder")
    if limit <= 0:
        raise ValueError(f"limit must be positive, got {limit}")

    box = mailbox_path(mailbox)
    url = f"{GRAPH_BASE}/{box}/mailFolders/{folder}/messages"
    params: dict[str, str | int] = {
        "$filter": "isRead eq false",
        "$orderby": "receivedDateTime desc",
        "$top": limit,
        "$select": "id,subject,from,receivedDateTime,bodyPreview,webLink,hasAttachments",
    }

    token = get_token(profile)
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        response = client.get(url, headers=auth_headers(token), params=params)
        response.raise_for_status()
        return _extract(response.json())
    finally:
        if http is None:
            client.close()


def _extract(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("value", [])
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for message in raw:
        if not isinstance(message, dict):
            continue
        out.append(
            {
                "id": message.get("id"),
                "subject": message.get("subject"),
                "from": _extract_address(message.get("from")),
                "received_at": message.get("receivedDateTime"),
                "snippet": message.get("bodyPreview"),
                "web_url": message.get("webLink"),
                "has_attachments": bool(message.get("hasAttachments", False)),
            }
        )
    return out


def _extract_address(raw: dict[str, Any] | None) -> dict[str, str | None] | None:
    if not isinstance(raw, dict):
        return None
    inner = raw.get("emailAddress")
    if not isinstance(inner, dict):
        return None
    return {
        "name": inner.get("name"),
        "address": inner.get("address"),
    }
