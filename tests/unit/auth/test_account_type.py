# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for auth/account_type.py — the personal-vs-work-token detector."""

from __future__ import annotations

import base64
import json

import pytest

from outlook_mcp.auth.account_type import (
    CONSUMER_TENANT_ID,
    _decode_jwt_claims,
    is_personal_account,
    signed_in_account_type,
)


def _jwt(claims: dict[str, object]) -> str:
    """Build a syntactically-valid 3-segment JWT with the given claims.

    Signature is junk — the decoder doesn't verify (caller already trusts
    the token; we just read claims).
    """
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.sig"


# ── _decode_jwt_claims ───────────────────────────────────────────────────


def test_decode_returns_payload_dict() -> None:
    token = _jwt({"tid": "abc", "upn": "alice@xmv.de"})
    assert _decode_jwt_claims(token) == {"tid": "abc", "upn": "alice@xmv.de"}


def test_decode_handles_missing_padding() -> None:
    """JWT base64url segments often have stripped `=` padding — we add it
    back internally. Regression guard."""
    # Construct a payload whose base64 length isn't a multiple of 4
    # without padding — `{"x": 1}` → 8 bytes → base64 → 12 chars (no
    # padding needed). Use a payload that DOES need padding: 5 bytes raw.
    claims = {"a": 1}
    payload_bytes = json.dumps(claims).encode()
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()
    token = f"hdr.{payload_b64}.sig"
    assert _decode_jwt_claims(token) == claims


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "not-a-jwt",
        "only.two",
        "four.parts.in.token",
        "header.@@@invalid_base64@@@.sig",
        "header.bm90LWpzb24=.sig",  # base64 of "not-json" — not valid JSON
    ],
)
def test_decode_returns_empty_on_malformed(bad: str) -> None:
    """Malformed JWTs → empty dict, not a raised exception. The caller
    treats absent claims as 'work/school' (safe default)."""
    assert _decode_jwt_claims(bad) == {}


def test_decode_returns_empty_when_payload_is_not_an_object() -> None:
    """A JWT whose payload is a valid JSON array (not object) — we want
    `{}` so .get("tid") returns None, not a list-index crash."""
    payload_b64 = base64.urlsafe_b64encode(b"[1, 2, 3]").rstrip(b"=").decode()
    token = f"hdr.{payload_b64}.sig"
    assert _decode_jwt_claims(token) == {}


# ── is_personal_account ──────────────────────────────────────────────────


def test_consumer_tid_returns_true() -> None:
    token = _jwt({"tid": CONSUMER_TENANT_ID, "upn": "user_outlook.com#EXT#@msa.com"})
    assert is_personal_account(token) is True


def test_work_school_tid_returns_false() -> None:
    """XMV's tenant GUID is a real Azure AD tenant — should be work/school."""
    token = _jwt({"tid": "7be9152f-5514-4a2d-b3d1-9aa5acf966c8", "upn": "d.koller@xmv.de"})
    assert is_personal_account(token) is False


def test_missing_tid_returns_false() -> None:
    """No tid claim → conservative default 'work/school' so work-only paths
    stay available rather than spuriously refused."""
    token = _jwt({"upn": "no-tid@example.com"})
    assert is_personal_account(token) is False


def test_opaque_token_returns_true_personal() -> None:
    """Microsoft Graph issues opaque (non-JWT, `Ew...`) tokens for personal
    Microsoft accounts; work/school accounts always get JWTs. Pre-v0.7
    (#49) this returned False — that broke personal-account guards
    because the real personal tokens never matched the JWT path."""
    assert is_personal_account("opaque-string-not-a-jwt") is True


def test_real_msa_opaque_token_returns_true() -> None:
    """Realistic shape: Microsoft-Account compact tokens start with `Ew`
    and contain no dots. Captured via curl against personal-account
    sign-in during the v0.7 personal-account harness work."""
    msa_token = "EwBYBMl6BAAU9BatlgMxts2T1B5e3Mucgfs4jcAAAQgt6w34yx8drVYaBv72"
    assert is_personal_account(msa_token) is True


def test_empty_token_returns_false() -> None:
    """Empty access_token is malformed input (would have failed the
    Graph round-trip already). Defaults to work/school to avoid
    flipping arbitrary failure modes."""
    assert is_personal_account("") is False


def test_two_segment_token_returns_true() -> None:
    """Any non-3-segment non-empty token is treated as opaque (personal).
    Two-segment input is non-empty and not-a-JWT, so it counts."""
    assert is_personal_account("foo.bar") is True


def test_three_segment_unparseable_returns_false() -> None:
    """3-segment shape but the payload can't decode — preserve pre-v0.7
    fall-through to work/school so we don't accidentally widen the
    interpretation to 'anything weird is personal'."""
    assert is_personal_account("hdr.@@@invalid_base64@@@.sig") is False


def test_consumer_tid_case_sensitive() -> None:
    """Microsoft documents the consumer tid as a specific GUID. Microsoft's
    Identity service emits it lowercase; we match exactly. Case-mismatched
    GUIDs (theoretical) should NOT match — better to fail closed than
    accept wrong-case as consumer."""
    upper = CONSUMER_TENANT_ID.upper()
    token = _jwt({"tid": upper})
    assert is_personal_account(token) is False


# ── signed_in_account_type ───────────────────────────────────────────────


def test_account_type_label_personal() -> None:
    token = _jwt({"tid": CONSUMER_TENANT_ID})
    assert signed_in_account_type(token) == "personal"


def test_account_type_label_work_or_school() -> None:
    token = _jwt({"tid": "00000000-0000-0000-0000-000000000001"})
    assert signed_in_account_type(token) == "work_or_school"


def test_account_type_label_is_stable_string() -> None:
    """Tests + error messages match on these literals — they're the
    contract, not just documentation."""
    consumer_token = _jwt({"tid": CONSUMER_TENANT_ID})
    work_token = _jwt({"tid": "00000000-0000-0000-0000-000000000001"})
    assert signed_in_account_type(consumer_token) in {"personal", "work_or_school"}
    assert signed_in_account_type(work_token) in {"personal", "work_or_school"}


def test_account_type_label_opaque_is_personal() -> None:
    """Regression: opaque tokens now map to the `personal` label (#49)."""
    assert signed_in_account_type("EwBYBMl6BAAU9BatlgMxts") == "personal"
