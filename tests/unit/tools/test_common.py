# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the shared `tools/_common.py` helpers.

Pins the audit-trail invariant from
docs/spikes/2026-05-08-v02-drafts-spikes.md § 2: every outbound Graph
request from any `ol_*` tool carries `Authorization: Bearer ...` AND
`User-Agent: mcp-server-outlook/<version>`. Hard-coding both header
keys here makes a regression visible the moment someone replaces
`auth_headers` with a hand-rolled dict.
"""

from __future__ import annotations

from outlook_mcp import __version__
from outlook_mcp.tools._common import GRAPH_BASE, USER_AGENT, auth_headers


def test_graph_base_url_is_v1() -> None:
    assert GRAPH_BASE == "https://graph.microsoft.com/v1.0"


def test_user_agent_includes_package_version() -> None:
    assert USER_AGENT == f"mcp-server-outlook/{__version__}"


def test_user_agent_starts_with_package_name() -> None:
    """Compliance reviewers should see the server name first in
    raw HTTP diagnostics — not a Python-version prefix."""
    assert USER_AGENT.startswith("mcp-server-outlook/")


def test_auth_headers_carry_bearer_token() -> None:
    headers = auth_headers("ABC.DEF.GHI")
    assert headers["Authorization"] == "Bearer ABC.DEF.GHI"


def test_auth_headers_carry_user_agent() -> None:
    headers = auth_headers("AT")
    assert headers["User-Agent"] == USER_AGENT


def test_auth_headers_only_authoritative_keys() -> None:
    """Catch accidental extra headers. Tools that need additional
    headers should layer them on top, not have them sneak in via the
    shared helper."""
    headers = auth_headers("AT")
    assert set(headers.keys()) == {"Authorization", "User-Agent"}
