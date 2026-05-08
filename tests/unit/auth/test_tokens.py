# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the CachedToken dataclass."""

from __future__ import annotations

import time

from outlook_mcp.auth.tokens import CachedToken


def test_to_json_round_trip() -> None:
    token = CachedToken(
        access_token="AT", refresh_token="RT", expires_at=12345.0, scope="Mail.Read"
    )
    parsed = CachedToken.from_json(token.to_json())
    assert parsed == token


def test_is_expired_when_past() -> None:
    token = CachedToken(
        access_token="AT", refresh_token="RT", expires_at=time.time() - 10, scope=""
    )
    assert token.is_expired() is True


def test_is_expired_within_buffer() -> None:
    """Default 60s buffer — token expiring in 30s reads as expired."""
    token = CachedToken(
        access_token="AT", refresh_token="RT", expires_at=time.time() + 30, scope=""
    )
    assert token.is_expired() is True


def test_is_not_expired_well_before() -> None:
    token = CachedToken(
        access_token="AT", refresh_token="RT", expires_at=time.time() + 3600, scope=""
    )
    assert token.is_expired() is False


def test_custom_buffer() -> None:
    token = CachedToken(
        access_token="AT", refresh_token="RT", expires_at=time.time() + 30, scope=""
    )
    # With a 10s buffer the same token isn't expired.
    assert token.is_expired(buffer=10) is False


def test_refresh_token_can_be_none() -> None:
    token = CachedToken(access_token="AT", refresh_token=None, expires_at=0.0, scope="")
    parsed = CachedToken.from_json(token.to_json())
    assert parsed.refresh_token is None
