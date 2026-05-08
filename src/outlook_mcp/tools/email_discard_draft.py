# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""ol_email_discard_draft — delete a draft this profile created.

Wraps `DELETE /me/messages/{id}`. Like `ol_email_update_draft`, only
mutates drafts whose `graph_id` is present in the per-profile
DraftRegistry. Hand-typed drafts in Outlook are off-limits.

Idempotent in two senses:
- Re-deleting a draft already gone server-side is a no-op (Graph
  returns 404; we treat that as success and clean up the registry
  entry).
- Re-calling on an already-removed registry entry produces
  DraftNotOwnedError (same as if the draft had never been ours).
"""

from __future__ import annotations

import httpx

from outlook_mcp.auth import get_token
from outlook_mcp.draft_registry import DraftRegistry
from outlook_mcp.tools._common import GRAPH_BASE, auth_headers
from outlook_mcp.tools.email_update_draft import DraftNotOwnedError


def discard_draft(
    draft_id: str,
    *,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> None:
    """Delete a draft this profile created.

    Returns None on success.

    Raises:
        ValueError: empty draft_id.
        DraftNotOwnedError: draft_id not in this profile's
            DraftRegistry. The MCP server refuses to touch drafts
            it didn't create.
        httpx.HTTPStatusError: non-2xx Graph response, EXCEPT 404
            which is treated as already-gone (success, registry
            entry cleaned up).
        outlook_mcp.auth.AuthRequiredError: no usable cached token.
    """
    if not draft_id or not draft_id.strip():
        raise ValueError("ol_email_discard_draft requires a non-empty draft_id")

    registry = DraftRegistry(profile=profile)
    if registry.get(draft_id) is None:
        raise DraftNotOwnedError(draft_id, profile)

    token = get_token(profile)
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        response = client.delete(
            f"{GRAPH_BASE}/me/messages/{draft_id}",
            headers=auth_headers(token),
        )
        # 204 No Content on success. 404 = already gone — treat as
        # success because the agent's intent ("make this draft go
        # away") is already satisfied.
        if response.status_code == 404:
            pass
        else:
            response.raise_for_status()
    finally:
        if http is None:
            client.close()

    registry.remove(draft_id)
