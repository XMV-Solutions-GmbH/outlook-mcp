# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""ol_email_update_draft — patch fields on a draft this profile created.

Wraps `PATCH /me/messages/{id}`. Only mutates drafts whose `graph_id`
is present in the per-profile `DraftRegistry` — defensive against
accidentally rewriting a hand-typed draft the user is composing in
Outlook.

Field semantics (designed for clean JSON / agent round-tripping):

- `subject` / `body` / `body_html`: `None` (or omit) = leave
  unchanged. Set to a non-None value to update.
- `to` / `cc` / `bcc`: `None` (or omit) = leave unchanged. Pass an
  **empty list** to clear the field. Pass a non-empty list to set.

Body and recipient parameters mirror `ol_email_create_draft` where
sensible; the same body-vs-body_html mutual-exclusion rule applies.

Like the create tool, this NEVER sends. There is no path from this
tool to a delivered email.
"""

from __future__ import annotations

from typing import Any

import httpx

from outlook_mcp.auth import get_token
from outlook_mcp.draft_registry import DraftEntry, DraftRegistry
from outlook_mcp.markdown import markdown_to_html
from outlook_mcp.tools._common import GRAPH_BASE, auth_headers


class DraftNotOwnedError(RuntimeError):
    """The given `draft_id` is not in this profile's draft registry.

    The MCP server only mutates drafts it created itself. Hand-typed
    drafts the user is composing in Outlook never appear in the
    registry, and operations like update / discard refuse to touch
    them.
    """

    def __init__(self, draft_id: str, profile: str) -> None:
        super().__init__(
            f"Draft {draft_id!r} was not created by profile {profile!r} "
            "(not in the per-profile DraftRegistry). The MCP server "
            "only mutates drafts it has created itself; hand-typed "
            "drafts in Outlook are off-limits.",
        )
        self.draft_id = draft_id
        self.profile = profile


def update_draft(
    draft_id: str,
    *,
    subject: str | None = None,
    body: str | None = None,
    body_html: str | None = None,
    to: list[str] | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> dict[str, Any]:
    """Update a draft this profile created. Returns `{ draft_id, web_url }`.

    Field semantics:

    - `subject`, `body`, `body_html`: `None` = leave unchanged.
      Non-None = set. `body` and `body_html` are mutually exclusive
      per call (same rule as create).
    - `to`, `cc`, `bcc`: `None` = leave unchanged. Empty list `[]` =
      clear the field. Non-empty list = set.

    Raises:
        ValueError: empty `draft_id`, both body kinds set, or no
            updatable parameter passed (nothing to change).
        DraftNotOwnedError: `draft_id` not in this profile's
            DraftRegistry. The MCP server refuses to touch drafts
            it didn't create.
        httpx.HTTPStatusError: non-2xx Graph response (404 if the
            draft was deleted server-side; 403 if `Mail.ReadWrite`
            isn't consented).
        outlook_mcp.auth.AuthRequiredError: no usable cached token.
    """
    if not draft_id or not draft_id.strip():
        raise ValueError("ol_email_update_draft requires a non-empty draft_id")
    if body is not None and body_html is not None:
        raise ValueError(
            "ol_email_update_draft: pass `body` (Markdown) OR `body_html` (raw HTML), not both",
        )

    payload: dict[str, Any] = {}
    if subject is not None:
        payload["subject"] = subject
    if body_html is not None:
        payload["body"] = {"contentType": "html", "content": body_html}
    elif body is not None:
        payload["body"] = {"contentType": "html", "content": markdown_to_html(body)}
    if to is not None:
        payload["toRecipients"] = _to_recipients(to)
    if cc is not None:
        payload["ccRecipients"] = _to_recipients(cc)
    if bcc is not None:
        payload["bccRecipients"] = _to_recipients(bcc)

    if not payload:
        raise ValueError(
            "ol_email_update_draft: nothing to update — pass at least one of "
            "subject / body / body_html / to / cc / bcc",
        )

    registry = DraftRegistry(profile=profile)
    existing = registry.get(draft_id)
    if existing is None:
        raise DraftNotOwnedError(draft_id, profile)

    token = get_token(profile)
    headers = {**auth_headers(token), "Content-Type": "application/json"}
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        response = client.patch(
            f"{GRAPH_BASE}/me/messages/{draft_id}",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        message = response.json()
    finally:
        if http is None:
            client.close()

    web_url_raw = message.get("webLink") or existing.web_url
    web_url = str(web_url_raw) if web_url_raw else None

    # Refresh registry entry if anything user-visible changed (subject
    # appears in ol_status; web_url is the click target). created_at
    # stays at the original creation moment — update is not create.
    if subject is not None or web_url != existing.web_url:
        registry.add(
            DraftEntry(
                kind="email",
                graph_id=draft_id,
                web_url=web_url,
                subject=subject if subject is not None else existing.subject,
                created_at=existing.created_at,
            )
        )

    return {"draft_id": draft_id, "web_url": web_url}


def _to_recipients(addrs: list[str]) -> list[dict[str, Any]]:
    """Map a flat email-address list to the Graph payload shape."""
    return [{"emailAddress": {"address": addr}} for addr in addrs]
