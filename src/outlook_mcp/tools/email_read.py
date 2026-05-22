# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""ol_email_read — fetch a single mail with body + headers + attachment list.

Wraps `GET /me/messages/{id}`. Read-only. The agent gets enough to
quote the mail (text + HTML body), see all the headers it might need
to draft a reply (to/cc/bcc/from/replyTo/conversationId/internetMessageId),
and a list of attachments by name + size + content-type. Attachment
*bytes* are NOT downloaded here — that's the v0.2 `ol_email_get_attachment`
tool. Including bodies inline keeps this a single Graph round-trip.

`include_attachments=False` (default) only fetches the message
metadata + body — fastest, smallest payload. With
`include_attachments=True` we issue a follow-up `GET .../attachments`
to enumerate them; metadata only, no bytes.
"""

from __future__ import annotations

from typing import Any

import httpx

from outlook_mcp.auth import get_token
from outlook_mcp.tools._common import GRAPH_BASE, auth_headers, mailbox_path


def read_email(
    message_id: str,
    *,
    include_attachments: bool = False,
    mailbox: str | None = None,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> dict[str, Any]:
    """Fetch a single mail by Graph id.

    `mailbox=None` (default): the signed-in user's mailbox (`/me/...`).
    `mailbox="<upn>"`: a shared mailbox the signed-in user has
    FullAccess on (`/users/{upn}/...`). The runtime guard that turns
    `mailbox` off when `OUTLOOK_ALLOW_SHARED_MAILBOXES` is unset/false
    lives in the MCP-tool wrapper (server.py), so callers that bypass
    the MCP layer must opt in explicitly via the env var or get a
    Graph-side 403.

    Returns a dict with: id, subject, from, to, cc, bcc, reply_to,
    received_at, sent_at, body_text, body_html, web_url, conversation_id,
    internet_message_id, has_attachments, attachments (list of
    `{id, name, content_type, size, is_inline}` if
    `include_attachments=True`, else None).

    Raises:
        ValueError: empty message_id, or empty `mailbox` (non-None but
            whitespace-only).
        httpx.HTTPStatusError: 404 if the message doesn't exist or is
            not visible; 403 if `mailbox` is set but the signed-in user
            has no FullAccess on it; other non-2xx propagate.
        outlook_mcp.auth.AuthRequiredError: no cached token.
    """
    if not message_id or not message_id.strip():
        raise ValueError("ol_email_read requires a non-empty message_id")

    box = mailbox_path(mailbox)
    token = get_token(profile)
    headers = auth_headers(token)
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        response = client.get(
            f"{GRAPH_BASE}/{box}/messages/{message_id}",
            headers=headers,
            params={
                "$select": (
                    "id,subject,from,toRecipients,ccRecipients,bccRecipients,"
                    "replyTo,receivedDateTime,sentDateTime,body,webLink,"
                    "conversationId,internetMessageId,hasAttachments"
                ),
            },
        )
        response.raise_for_status()
        message = response.json()
        result = _to_result(message)
        if include_attachments and result.get("has_attachments"):
            attachments_response = client.get(
                f"{GRAPH_BASE}/{box}/messages/{message_id}/attachments",
                headers=headers,
                params={"$select": "id,name,contentType,size,isInline"},
            )
            attachments_response.raise_for_status()
            result["attachments"] = _extract_attachments(attachments_response.json())
        else:
            result["attachments"] = None
        return result
    finally:
        if http is None:
            client.close()


def _to_result(message: dict[str, Any]) -> dict[str, Any]:
    body = message.get("body") or {}
    body_content = body.get("content") if isinstance(body, dict) else None
    body_type = body.get("contentType") if isinstance(body, dict) else None
    return {
        "id": message.get("id"),
        "subject": message.get("subject"),
        "from": _extract_address(message.get("from")),
        "to": _extract_addresses(message.get("toRecipients")),
        "cc": _extract_addresses(message.get("ccRecipients")),
        "bcc": _extract_addresses(message.get("bccRecipients")),
        "reply_to": _extract_addresses(message.get("replyTo")),
        "received_at": message.get("receivedDateTime"),
        "sent_at": message.get("sentDateTime"),
        "body_text": body_content if body_type == "text" else None,
        "body_html": body_content if body_type == "html" else None,
        "web_url": message.get("webLink"),
        "conversation_id": message.get("conversationId"),
        "internet_message_id": message.get("internetMessageId"),
        "has_attachments": bool(message.get("hasAttachments", False)),
    }


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


def _extract_addresses(raw: list[Any] | None) -> list[dict[str, str | None]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str | None]] = []
    for item in raw:
        flat = _extract_address(item)
        if flat is not None:
            out.append(flat)
    return out


def _extract_attachments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("value", [])
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for att in raw:
        if not isinstance(att, dict):
            continue
        out.append(
            {
                "id": att.get("id"),
                "name": att.get("name"),
                "content_type": att.get("contentType"),
                "size": att.get("size"),
                "is_inline": bool(att.get("isInline", False)),
            }
        )
    return out
