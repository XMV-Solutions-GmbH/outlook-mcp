# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""ol_email_search — free-text search over the user's mailbox.

Wraps `GET /me/messages` with `$search` for full-text matching plus
optional `$filter` clauses for sender / received-after / has-attachment
narrowing. Read-only, idempotent.

Microsoft Graph note: when `$search` is used on /messages, Graph
disallows `$orderby` and `$count` (it ranks by relevance and caps
results internally). Folder narrowing is therefore done by switching
the URL path to `/me/mailFolders/{folder}/messages` rather than via
`$filter parentFolderId`. Combining `$search` with `$filter` requires
the `Prefer: outlook.body-content-type` header in some forms; we keep
to the documented union and let Graph do the work.
"""

from __future__ import annotations

from typing import Any

import httpx

from outlook_mcp.auth import get_token
from outlook_mcp.tools._common import GRAPH_BASE, auth_headers


def search(
    query: str,
    *,
    folder: str | None = None,
    from_address: str | None = None,
    modified_after: str | None = None,
    has_attachment: bool | None = None,
    limit: int = 25,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Search messages in the signed-in user's mailbox.

    Returns at most `limit` hits, each a dict with `id`, `subject`,
    `from` (display + email), `received_at` (ISO 8601), `snippet`
    (the Graph `bodyPreview`), `web_url` (the Outlook web URL),
    `has_attachments`. An empty list is a valid result (no matches).

    Filter args:

    - `folder="Inbox"` — narrows to that mail folder by well-known
      name (Inbox, Drafts, SentItems, DeletedItems, Junk, Outbox,
      Archive). Pass a Graph folder-id if the well-known name doesn't
      cover your case.
    - `from_address="alice@example.com"` — only mails from that sender.
    - `modified_after="2024-01-01T00:00:00Z"` — ISO 8601 cutoff.
    - `has_attachment=True` — only mails with attachments.

    Raises:
        ValueError: empty query / non-positive limit.
        httpx.HTTPStatusError: on a non-2xx response from Graph.
        outlook_mcp.auth.AuthRequiredError: no usable cached token
            for `profile`.
    """
    if not query or not query.strip():
        raise ValueError("ol_email_search requires a non-empty query")
    if limit <= 0:
        raise ValueError(f"limit must be positive, got {limit}")

    base = (
        f"{GRAPH_BASE}/me/mailFolders/{folder}/messages" if folder else f"{GRAPH_BASE}/me/messages"
    )
    params: dict[str, str | int] = {
        "$search": f'"{query.strip()}"',
        "$top": limit,
        "$select": "id,subject,from,receivedDateTime,bodyPreview,webLink,hasAttachments",
    }

    filter_parts: list[str] = []
    if from_address:
        filter_parts.append(f"from/emailAddress/address eq '{from_address}'")
    if modified_after:
        filter_parts.append(f"receivedDateTime ge {modified_after}")
    if has_attachment is not None:
        filter_parts.append(f"hasAttachments eq {'true' if has_attachment else 'false'}")
    if filter_parts:
        params["$filter"] = " and ".join(filter_parts)

    token = get_token(profile)
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        response = client.get(base, headers=auth_headers(token), params=params)
        response.raise_for_status()
        return _extract_hits(response.json())
    finally:
        if http is None:
            client.close()


def _extract_hits(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert Graph's `/messages` response into flat hit dicts."""
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
    """Flatten Graph's nested {emailAddress: {name, address}} structure."""
    if not isinstance(raw, dict):
        return None
    inner = raw.get("emailAddress")
    if not isinstance(inner, dict):
        return None
    return {
        "name": inner.get("name"),
        "address": inner.get("address"),
    }
