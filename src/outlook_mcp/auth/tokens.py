# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Cached-token data model.

Re-exports `CachedToken` and the refresh-buffer constant from the
shared `mcp-microsoft-graph-auth` library. The local module remains
so existing imports (`outlook_mcp.auth.tokens.CachedToken`) keep
working unchanged.
"""

from __future__ import annotations

from mcp_microsoft_graph_auth.tokens import (
    DEFAULT_REFRESH_BUFFER_SECONDS,
    CachedToken,
)

__all__ = ["DEFAULT_REFRESH_BUFFER_SECONDS", "CachedToken"]
