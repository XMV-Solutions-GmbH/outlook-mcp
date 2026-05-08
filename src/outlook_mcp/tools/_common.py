# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Shared helpers across `ol_*` tool modules.

Default Microsoft Graph base URL + utilities for building the auth
header. Outlook is mailbox-scoped per user, so unlike the SharePoint
sister project we don't need URL parsing or site-id resolution.
Everything hits `/me/...` against the signed-in user.

Every Graph request carries a `User-Agent: mcp-server-outlook/<version>`
header in addition to the bearer token. The audit-trail rationale is
in docs/spikes/2026-05-08-v02-drafts-spikes.md § 2: ClientAppId +
AppDisplayName already identify the calling app inside Microsoft 365
audit logs, but a self-identifying User-Agent makes raw Graph
diagnostics readable too — a compliance reviewer scrolling through
sign-in / activity logs sees the server name immediately.

Naming uses leading underscore at the module level to flag "internal
to the tools/ subpackage".
"""

from __future__ import annotations

from outlook_mcp import __version__

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
USER_AGENT = f"mcp-server-outlook/{__version__}"


def auth_headers(token: str) -> dict[str, str]:
    """Build the standard headers for Graph requests.

    Includes the bearer token and a self-identifying User-Agent. Every
    `ol_*` tool routes its outbound HTTP through here, so the
    audit-trail label is consistent.
    """
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
    }
