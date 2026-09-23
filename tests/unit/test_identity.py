# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for deriving the signed-in identity from the token itself.

Issue #83: the reported identity must be a property of the access
token in hand, never of remembered process state. These tests pin the
two primitives that make that possible.
"""

from __future__ import annotations

import base64
import json

from outlook_mcp.auth.identity import token_fingerprint, upn_from_access_token


def _jwt(claims: dict[str, object]) -> str:
    """Build an unsigned JWT-shaped token carrying `claims`."""

    def seg(obj: dict[str, object]) -> str:
        raw = json.dumps(obj).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{seg({'alg': 'none'})}.{seg(claims)}.signature-not-verified"


def test_upn_claim_is_preferred() -> None:
    token = _jwt({"upn": "bob@xmv.de", "unique_name": "stale@xmv.de"})
    assert upn_from_access_token(token) == "bob@xmv.de"


def test_falls_back_to_unique_name() -> None:
    token = _jwt({"unique_name": "bob@xmv.de"})
    assert upn_from_access_token(token) == "bob@xmv.de"


def test_falls_back_to_preferred_username() -> None:
    token = _jwt({"preferred_username": "bob@xmv.de"})
    assert upn_from_access_token(token) == "bob@xmv.de"


def test_opaque_personal_account_token_yields_none() -> None:
    """Personal Microsoft accounts get a non-JWT token. Unknown is the
    correct answer; the caller falls back to /me."""
    assert upn_from_access_token("EwBYA8l6BAAUlleecdefghijkl") is None


def test_malformed_payload_yields_none() -> None:
    assert upn_from_access_token("aaa.!!!not-base64!!!.ccc") is None


def test_non_object_payload_yields_none() -> None:
    payload = base64.urlsafe_b64encode(json.dumps([1, 2, 3]).encode()).decode().rstrip("=")
    assert upn_from_access_token(f"aaa.{payload}.ccc") is None


def test_jwt_without_identity_claims_yields_none() -> None:
    assert upn_from_access_token(_jwt({"aud": "graph", "scp": "Mail.Read"})) is None


def test_blank_claim_is_not_an_identity() -> None:
    assert upn_from_access_token(_jwt({"upn": "   "})) is None


def test_fingerprint_is_stable_and_distinguishes_tokens() -> None:
    assert token_fingerprint("AT") == token_fingerprint("AT")
    assert token_fingerprint("AT") != token_fingerprint("AT2")


def test_fingerprint_does_not_leak_the_token() -> None:
    assert "super-secret-token" not in token_fingerprint("super-secret-token")
