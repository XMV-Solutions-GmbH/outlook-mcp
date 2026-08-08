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
from outlook_mcp.tools._common import (
    GRAPH_BASE,
    auth_headers,
    is_group_mailbox,
    mailbox_path,
)
from outlook_mcp.tools._groups import search_threads


def search(
    query: str,
    *,
    folder: str | None = None,
    from_address: str | None = None,
    modified_after: str | None = None,
    has_attachment: bool | None = None,
    limit: int = 25,
    mailbox: str | None = None,
    to_address: str | None = None,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Search messages in the signed-in user's mailbox.

    `mailbox=None` (default): the signed-in user's mailbox (`/me/...`).
    `mailbox="<upn>"`: a shared mailbox the signed-in user has
    FullAccess on (`/users/{upn}/...`). The MCP-tool wrapper enforces
    that `mailbox` is only usable when
    `OUTLOOK_ALLOW_SHARED_MAILBOXES=true`.
    `mailbox="group:<group-id>"`: a Microsoft 365 group mailbox, gated
    on `OUTLOOK_ALLOW_GROUP_MAILBOXES=true`.

    **The group path matches differently.** Graph offers no `$search`
    over group conversations, so the query is matched client-side
    against each thread's topic, preview and sender names — it never
    sees message bodies. Treat a group search as a subject-level search,
    not the full-text one the mailbox path performs.

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
    - `to_address="box+case@example.com"` — only mails delivered to that
      address. On a group mailbox this is resolved from the MAPI
      property `PidTagDisplayTo`, which is the only place the delivered
      recipient survives — useful for plus-addressed conventions where
      the address identifies the sender's purpose.
    - `modified_after="2024-01-01T00:00:00Z"` — ISO 8601 cutoff.
    - `has_attachment=True` — only mails with attachments.

    Raises:
        ValueError: empty query, non-positive limit, or empty mailbox.
        httpx.HTTPStatusError: 403 if `mailbox` is set but the signed-in
            user has no FullAccess on it; other non-2xx propagate.
        outlook_mcp.auth.AuthRequiredError: no usable cached token
            for `profile`.
    """
    if not query or not query.strip():
        raise ValueError("ol_email_search requires a non-empty query")
    if limit <= 0:
        raise ValueError(f"limit must be positive, got {limit}")

    if is_group_mailbox(mailbox):
        assert mailbox is not None  # narrowed by is_group_mailbox
        if folder is not None:
            raise ValueError(
                "folder narrowing is not available on group mailboxes — a "
                "group's conversations are not organised into mail folders",
            )
        token = get_token(profile)
        client = http if http is not None else httpx.Client(timeout=30.0)
        try:
            return search_threads(
                mailbox,
                query,
                token=token,
                client=client,
                limit=limit,
                from_address=from_address,
                modified_after=modified_after,
                has_attachment=has_attachment,
                to_address=to_address,
            )
        finally:
            if http is None:
                client.close()

    box = mailbox_path(mailbox)
    base = (
        f"{GRAPH_BASE}/{box}/mailFolders/{folder}/messages"
        if folder
        else f"{GRAPH_BASE}/{box}/messages"
    )
    params: dict[str, str | int] = {
        "$search": f'"{query.strip()}"',
        "$top": limit,
        "$select": "id,subject,from,receivedDateTime,bodyPreview,webLink,hasAttachments",
    }

    filter_parts: list[str] = []
    if from_address:
        filter_parts.append(f"from/emailAddress/address eq '{from_address}'")
    if to_address:
        filter_parts.append(
            f"toRecipients/any(r: r/emailAddress/address eq '{to_address}')",
        )
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
