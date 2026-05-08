# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Shared helpers across `ol_*` tool modules.

Default Microsoft Graph base URL + utilities for building the auth
header. Outlook is mailbox-scoped per user, so unlike the SharePoint
sister project we don't need URL parsing or site-id resolution.
Everything hits `/me/...` against the signed-in user.

Naming uses leading underscore at the module level to flag "internal
to the tools/ subpackage".
"""

from __future__ import annotations

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def auth_headers(token: str) -> dict[str, str]:
    """Build the standard Authorization header dict for Graph requests."""
    return {"Authorization": f"Bearer {token}"}
