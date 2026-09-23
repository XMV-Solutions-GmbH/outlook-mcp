# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""The gap between what was requested and what the token grants."""

from __future__ import annotations

import base64
import json

from outlook_mcp.auth.granted import excess_scopes, granted_scopes

BASE = (
    "Mail.Read",
    "Calendars.Read",
    "Mail.ReadWrite",
    "Calendars.ReadWrite",
    "User.Read",
    "offline_access",
)


def _jwt(scp: str) -> str:
    def seg(obj: dict[str, object]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{seg({'alg': 'none'})}.{seg({'scp': scp})}.sig"


def test_granted_scopes_are_read_from_the_scp_claim() -> None:
    assert granted_scopes(_jwt("Mail.Read User.Read")) == ("Mail.Read", "User.Read")


def test_opaque_token_grants_are_unknown_not_empty_claims() -> None:
    assert granted_scopes("EwBYA8l6BAAUlleecdefghijkl") == ()


def test_the_production_token_is_reported_as_exceeding_the_request() -> None:
    """The observed live case: drafts on, send off, shared and group
    unset — and the token carries all three gated scopes anyway."""
    token = _jwt(
        "Calendars.Read Calendars.ReadWrite Group-Conversation.Read.All Mail.Read "
        "Mail.ReadWrite Mail.ReadWrite.Shared Mail.Send User.Read profile openid email"
    )
    assert excess_scopes(token, BASE) == (
        "Group-Conversation.Read.All",
        "Mail.ReadWrite.Shared",
        "Mail.Send",
    )


def test_a_token_matching_the_request_reports_nothing() -> None:
    assert excess_scopes(_jwt(" ".join(BASE)), BASE) == ()


def test_protocol_scopes_are_not_reported_as_excess() -> None:
    assert (
        excess_scopes(_jwt("Mail.Read openid profile email offline_access"), ("Mail.Read",)) == ()
    )


def test_opaque_token_reports_no_excess() -> None:
    assert excess_scopes("opaque-token", BASE) == ()
