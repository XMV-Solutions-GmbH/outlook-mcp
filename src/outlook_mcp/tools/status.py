# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""ol_status — list drafts created by this profile.

Read-only. Returns the persistent draft registry's view for the
current profile. In v0.1 this is always an empty list (no draft
tools register entries yet); the tool exists so the agent surface is
stable across the v0.1 → v0.2 boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from outlook_mcp.draft_registry import DraftRegistry


def status(profile: str = "default") -> list[dict[str, Any]]:
    """Return one dict per draft created by this MCP profile.

    Each entry has `kind` (`email` or `event`), `graph_id`,
    `web_url`, `subject`, `created_at` (ISO datetime UTC). Empty list
    when nothing is pending.
    """
    registry = DraftRegistry(profile=profile)
    entries = registry.list_all()
    return [
        {
            "kind": entry.kind,
            "graph_id": entry.graph_id,
            "web_url": entry.web_url,
            "subject": entry.subject,
            "created_at": datetime.fromtimestamp(entry.created_at, tz=UTC).isoformat(),
        }
        for entry in entries
    ]
