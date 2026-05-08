# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""ol_email_list_drafts — list drafts visible to this profile.

Two modes:

- `profile_only=True` (default, recommended): returns only drafts
  this MCP profile has created (drafts with a matching entry in the
  per-profile DraftRegistry). No Graph call — the registry is
  authoritative.
- `profile_only=False`: returns ALL drafts in the user's Drafts
  folder via Microsoft Graph, regardless of who created them.
  Includes drafts the human typed by hand in Outlook. Useful when
  the agent is helping the user "look at all your drafts" rather
  than "look at the ones I made for you".

The output shape is identical between the two modes so the agent
can iterate uniformly: each entry has `id`, `subject`,
`received_at` (Graph's lastModifiedDateTime, mapped to the same
field name read tools use), `web_url`, `created_by_this_profile`
(bool — set so the agent knows whether ol_email_update_draft /
ol_email_discard_draft will accept that id).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from outlook_mcp.auth import get_token
from outlook_mcp.draft_registry import DraftRegistry
from outlook_mcp.tools._common import GRAPH_BASE, auth_headers


def list_drafts(
    *,
    profile_only: bool = True,
    limit: int = 100,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """List drafts. Returns at most `limit` entries, newest first.

    With `profile_only=True` (default): drafts created by this
    profile only, sourced from the local DraftRegistry. No Graph
    call.

    With `profile_only=False`: all drafts in the user's Drafts
    folder, sourced from Microsoft Graph. Each entry's
    `created_by_this_profile` flag is True iff its id is also in
    the registry.

    Raises:
        ValueError: non-positive limit.
        httpx.HTTPStatusError: Graph 4xx/5xx (only in
            profile_only=False mode).
        outlook_mcp.auth.AuthRequiredError: no usable cached token
            (only in profile_only=False mode).
    """
    if limit <= 0:
        raise ValueError(f"limit must be positive, got {limit}")

    registry = DraftRegistry(profile=profile)
    owned = {entry.graph_id: entry for entry in registry.list_all()}

    if profile_only:
        # Newest first by created_at (registry-recorded, which is
        # creation time on this machine — close enough for a UI list).
        ordered = sorted(owned.values(), key=lambda e: e.created_at, reverse=True)
        return [
            {
                "id": entry.graph_id,
                "subject": entry.subject,
                "received_at": datetime.fromtimestamp(entry.created_at, tz=UTC).isoformat(),
                "web_url": entry.web_url,
                "created_by_this_profile": True,
            }
            for entry in ordered[:limit]
        ]

    # profile_only=False: hit Graph for the user's full Drafts folder.
    token = get_token(profile)
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        response = client.get(
            f"{GRAPH_BASE}/me/mailFolders/Drafts/messages",
            headers=auth_headers(token),
            params={
                "$orderby": "lastModifiedDateTime desc",
                "$top": limit,
                "$select": "id,subject,lastModifiedDateTime,webLink",
            },
        )
        response.raise_for_status()
        raw = response.json().get("value", []) or []
    finally:
        if http is None:
            client.close()

    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for message in raw:
        if not isinstance(message, dict):
            continue
        msg_id = message.get("id")
        out.append(
            {
                "id": msg_id,
                "subject": message.get("subject"),
                "received_at": message.get("lastModifiedDateTime"),
                "web_url": message.get("webLink"),
                "created_by_this_profile": msg_id in owned,
            }
        )
    return out
