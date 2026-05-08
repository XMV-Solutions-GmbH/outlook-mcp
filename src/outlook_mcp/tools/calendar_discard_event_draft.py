# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""ol_calendar_discard_event_draft — delete a calendar event this profile created.

Wraps `DELETE /me/events/{id}`. Same defensive shape as
`ol_email_discard_draft`: only events whose `graph_id` is in this
profile's DraftRegistry can be removed. Hand-created events in
Outlook are off-limits.

Idempotent: 404 from Graph (event already gone) is treated as
success and the registry is cleaned up.
"""

from __future__ import annotations

import httpx

from outlook_mcp.auth import get_token
from outlook_mcp.draft_registry import DraftRegistry
from outlook_mcp.tools._common import GRAPH_BASE, auth_headers
from outlook_mcp.tools.email_update_draft import DraftNotOwnedError


def discard_event_draft(
    event_id: str,
    *,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> None:
    """Delete a calendar event this profile created.

    Returns None on success.

    Raises:
        ValueError: empty event_id.
        DraftNotOwnedError: event_id not in this profile's
            DraftRegistry. The MCP server refuses to touch events
            it didn't create.
        httpx.HTTPStatusError: non-2xx Graph response, EXCEPT 404
            which is treated as already-gone.
        outlook_mcp.auth.AuthRequiredError: no usable cached token.
    """
    if not event_id or not event_id.strip():
        raise ValueError("ol_calendar_discard_event_draft requires a non-empty event_id")

    registry = DraftRegistry(profile=profile)
    if registry.get(event_id) is None:
        raise DraftNotOwnedError(event_id, profile)

    token = get_token(profile)
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        response = client.delete(
            f"{GRAPH_BASE}/me/events/{event_id}",
            headers=auth_headers(token),
        )
        if response.status_code == 404:
            pass
        else:
            response.raise_for_status()
    finally:
        if http is None:
            client.close()

    registry.remove(event_id)
