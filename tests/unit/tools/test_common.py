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

import pytest

from outlook_mcp import __version__
from outlook_mcp.tools._common import GRAPH_BASE, USER_AGENT, auth_headers, mailbox_path


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


# ---------------------------------------------------------------------
# mailbox_path — #45 shared-mailbox routing
# ---------------------------------------------------------------------


def test_mailbox_path_none_returns_me() -> None:
    """The default path matches pre-#45 behaviour: signed-in user."""
    assert mailbox_path(None) == "me"


def test_mailbox_path_upn_returns_users_segment() -> None:
    """`@` is in the safe set of the urllib.quote call — passes through
    unquoted because Microsoft Graph accepts `/users/{upn}` URLs in
    that form and unquoted reads better in audit logs."""
    assert mailbox_path("sekretariat@xmv.de") == "users/sekretariat@xmv.de"


def test_mailbox_path_preserves_dot_and_plus_in_upn() -> None:
    """`.`, `+`, `-`, `_`, `@` are in the safe set — all pass through
    unquoted for audit-log readability."""
    assert mailbox_path("first.last+team@contoso.de") == ("users/first.last+team@contoso.de")


def test_mailbox_path_strips_whitespace() -> None:
    """A copy-pasted UPN with trailing whitespace shouldn't break routing."""
    assert mailbox_path("  shared@xmv.de  ") == "users/shared@xmv.de"


def test_mailbox_path_rejects_empty_string() -> None:
    """An empty `mailbox` is operator error — fail loud."""
    with pytest.raises(ValueError, match="non-empty UPN"):
        mailbox_path("")


def test_mailbox_path_rejects_whitespace_only() -> None:
    with pytest.raises(ValueError, match="non-empty UPN"):
        mailbox_path("   ")


def test_mailbox_path_blocks_path_traversal_attempt() -> None:
    """A mailbox value with a slash would compose to a different URL
    shape; quoting catches it so the Graph URL stays scoped to /users/."""
    quoted = mailbox_path("../admin@evil.de")
    # The slash gets %-encoded; the URL still routes via /users/.
    assert quoted.startswith("users/")
    assert "/" not in quoted[len("users/") :]
