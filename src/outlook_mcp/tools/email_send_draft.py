# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""ol_email_send_draft — send an existing draft this profile created.

Wraps `POST /me/messages/{id}/send`. **Opt-in via OUTLOOK_ALLOW_SEND=true** —
this tool is only registered on the MCP server when that env flag is
truthy AND `OUTLOOK_ALLOW_DRAFTS=true` is also set. The tool is also
gated at the auth layer: when `OUTLOOK_ALLOW_SEND` is not truthy, the
OAuth scope request omits `Mail.Send` and the consent screen does NOT
include "this app can send mail as you". See `auth/flow.py:resolve_scopes`.

**No autonomous send.** The agent must explicitly call this tool with
a `draft_id` referencing a draft already in the user's Drafts folder
(written by an earlier `ol_email_create_draft` or
`ol_email_update_draft` call). The human reviewer can read the draft
in Outlook between those tool calls and the send call.

Defensive: only drafts whose `graph_id` is in this profile's
DraftRegistry can be sent. Hand-typed drafts in Outlook are
off-limits — same defensive shape as `ol_email_update_draft` and
`ol_email_discard_draft`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from outlook_mcp.auth import get_token
from outlook_mcp.draft_registry import DraftRegistry
from outlook_mcp.tools._common import GRAPH_BASE, auth_headers
from outlook_mcp.tools.email_update_draft import DraftNotOwnedError


def send_draft(
    draft_id: str,
    *,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> dict[str, Any]:
    """Send a draft this profile created. Returns `{ draft_id, sent_at }`.

    On success: the draft is moved from Drafts to Sent Items by
    Microsoft, and the registry entry is removed (the agent can find
    the sent mail via `ol_email_search` if it needs to reference it
    later).

    Raises:
        ValueError: empty draft_id.
        DraftNotOwnedError: draft_id not in this profile's
            DraftRegistry. The MCP server refuses to send drafts
            it didn't create.
        httpx.HTTPStatusError: non-2xx Graph response. 403 typically
            means `Mail.Send` consent is missing — re-run
            `mcp-server-outlook login` with `OUTLOOK_ALLOW_SEND=true`
            in the environment to refresh consent.
        outlook_mcp.auth.AuthRequiredError: no usable cached token.
    """
    if not draft_id or not draft_id.strip():
        raise ValueError("ol_email_send_draft requires a non-empty draft_id")

    registry = DraftRegistry(profile=profile)
    if registry.get(draft_id) is None:
        raise DraftNotOwnedError(draft_id, profile)

    token = get_token(profile)
    client = http if http is not None else httpx.Client(timeout=30.0)
    sent_at = datetime.now(UTC).isoformat()
    try:
        response = client.post(
            f"{GRAPH_BASE}/me/messages/{draft_id}/send",
            headers=auth_headers(token),
        )
        # 202 Accepted is the documented success response; some clients
        # observe 204 No Content depending on the path. Treat both as
        # success.
        if response.status_code not in (202, 204):
            response.raise_for_status()
    finally:
        if http is None:
            client.close()

    registry.remove(draft_id)
    return {"draft_id": draft_id, "sent_at": sent_at}
