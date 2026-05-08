# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for ol_login_status.

Pins the load-bearing properties:

- Active probe: a token already in the store (CLI-installed or
  tool-installed) → `signed_in`, NOT `none`.
- `pending` returns user_code + verification_url + time_remaining_s
  via the lib's `public_view`.
- `none` is the only fallthrough; terminal session statuses
  (failed/expired/cancelled) get folded into `none` + a structured
  `error` field so the agent's decision logic stays simple.
- `/me` is called at most once per profile-state-transition; the UPN
  cache is the second-call short-circuit.
- Wire-format edge cases: `/me` 4xx, malformed payload, missing
  userPrincipalName all degrade to `signed_in` without UPN rather
  than crashing.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest
import respx
from mcp_microsoft_graph_auth import LoginSession

from outlook_mcp.auth import get_token
from outlook_mcp.auth.tokens import CachedToken
from outlook_mcp.login_state import (
    cache_upn,
    get_login_session_registry,
    reset_for_tests,
)
from outlook_mcp.tools.login_status import login_status

ME_URL = "https://graph.microsoft.com/v1.0/me"


@pytest.fixture(autouse=True)
def _isolate_login_state() -> None:
    """Each test starts with an empty registry + empty UPN cache.
    Prevents accidental cross-test bleeding through the
    process-singleton."""
    reset_for_tests()


class _MemStore:
    def __init__(self, token: CachedToken | None = None) -> None:
        self._d: dict[str, bytes] = {}
        if token is not None:
            self._d["default"] = token.to_json().encode()

    def get(self, profile: str) -> bytes | None:
        return self._d.get(profile)

    def set(self, profile: str, value: bytes) -> None:
        self._d[profile] = value

    def delete(self, profile: str) -> None:
        self._d.pop(profile, None)


def _fresh_token() -> CachedToken:
    return CachedToken(
        access_token="AT",
        refresh_token="RT",
        expires_at=time.time() + 3600,
        scope="",
    )


def _patched_get_token(monkeypatch: pytest.MonkeyPatch, store: _MemStore) -> None:
    monkeypatch.setattr(
        "outlook_mcp.tools.login_status.get_token",
        lambda profile="default": get_token(profile=profile, store=store),
    )


# ---------------------------------------------------------------------
# State 1 — `signed_in`: token in store, fresh / valid
# ---------------------------------------------------------------------


@respx.mock
def test_signed_in_when_token_present_and_me_returns_upn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patched_get_token(monkeypatch, _MemStore(token=_fresh_token()))
    respx.get(ME_URL).respond(
        json={"userPrincipalName": "anna@xmv.de"},
    )
    result = login_status(profile="default")
    assert result == {"status": "signed_in", "signed_in_user_upn": "anna@xmv.de"}


@respx.mock
def test_signed_in_caches_upn_and_skips_second_me_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second status call must NOT hit /me — the UPN cache is the
    short-circuit. Otherwise a busy agent's status loop would pile
    up Graph round-trips."""
    _patched_get_token(monkeypatch, _MemStore(token=_fresh_token()))
    route = respx.get(ME_URL).respond(json={"userPrincipalName": "anna@xmv.de"})

    login_status(profile="default")
    login_status(profile="default")
    login_status(profile="default")

    assert route.call_count == 1


@respx.mock
def test_signed_in_returns_signed_in_even_when_me_4xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the token is valid but `/me` 4xx's (e.g. transient
    backend hiccup or a scope mismatch where User.Read isn't
    consented for some weird reason), we still return `signed_in`
    — just without the UPN."""
    _patched_get_token(monkeypatch, _MemStore(token=_fresh_token()))
    respx.get(ME_URL).respond(403, json={"error": {"code": "Forbidden"}})

    result = login_status(profile="default")
    assert result == {"status": "signed_in", "signed_in_user_upn": None}


@respx.mock
def test_signed_in_returns_signed_in_when_me_payload_missing_upn_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `/me` response without `userPrincipalName` (rare but
    possible — some Microsoft tenant configurations) is not a
    crash — UPN is just unknown."""
    _patched_get_token(monkeypatch, _MemStore(token=_fresh_token()))
    respx.get(ME_URL).respond(json={"id": "abc-123"})  # no userPrincipalName key

    result = login_status(profile="default")
    assert result == {"status": "signed_in", "signed_in_user_upn": None}


@respx.mock
def test_signed_in_handles_me_returning_non_dict_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defensive: a list / null / anything-but-a-dict from `/me`
    must not crash the status call."""
    _patched_get_token(monkeypatch, _MemStore(token=_fresh_token()))
    respx.get(ME_URL).respond(json=[])

    result = login_status(profile="default")
    assert result == {"status": "signed_in", "signed_in_user_upn": None}


@respx.mock
def test_signed_in_handles_me_returning_non_string_upn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Microsoft has shipped numeric or null userPrincipalName on
    obscure tenant types in the past. We coerce to None rather
    than blow up."""
    _patched_get_token(monkeypatch, _MemStore(token=_fresh_token()))
    respx.get(ME_URL).respond(json={"userPrincipalName": None})

    result = login_status(profile="default")
    assert result == {"status": "signed_in", "signed_in_user_upn": None}


def test_signed_in_uses_cached_upn_without_me_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pre-populating the UPN cache means /me is never called.
    Useful path: ol_login_begin populated the cache, status calls
    short-circuit immediately."""
    _patched_get_token(monkeypatch, _MemStore(token=_fresh_token()))
    cache_upn("default", "pre-cached@xmv.de")

    with respx.mock(base_url="https://graph.microsoft.com") as router:
        result = login_status(profile="default")
        assert not router.calls
    assert result == {"status": "signed_in", "signed_in_user_upn": "pre-cached@xmv.de"}


# ---------------------------------------------------------------------
# State 2 — `pending`: in-flight Device Code session
# ---------------------------------------------------------------------


def _pending_session(*, profile: str = "default", expires_in_s: int = 600) -> LoginSession:
    now = datetime.now(UTC)
    return LoginSession(
        session_id="sid-abc",
        profile=profile,
        device_code="DC-secret",
        user_code="ABCD-EFGH",
        verification_url="https://microsoft.com/devicelogin",
        verification_url_complete=None,
        expires_at=now + timedelta(seconds=expires_in_s),
        interval_s=5,
        status="pending",
        signed_in_user_upn=None,
        error=None,
        task=None,
        started_at=now,
    )


def test_pending_returns_user_code_and_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _patched_get_token(monkeypatch, _MemStore())  # no token → not signed in
    get_login_session_registry().put(_pending_session())

    result = login_status(profile="default")
    assert result["status"] == "pending"
    assert result["user_code"] == "ABCD-EFGH"
    assert result["verification_url"] == "https://microsoft.com/devicelogin"
    assert result["verification_url_complete"] is None
    assert result["session_id"] == "sid-abc"
    # time_remaining_s is computed and present
    assert isinstance(result["time_remaining_s"], int)
    assert result["time_remaining_s"] > 0


def test_pending_does_not_leak_device_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lib's `public_view` strips `device_code` (it's the
    server-side polling secret). Our wrapper must rely on
    public_view rather than reading session attributes directly."""
    _patched_get_token(monkeypatch, _MemStore())
    get_login_session_registry().put(_pending_session())

    result = login_status(profile="default")
    assert "device_code" not in result


def test_pending_overrides_a_stale_token_probe_only_via_priority_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a token exists, signed_in wins regardless of any pending
    session for the profile (e.g. user did CLI login while a tool
    flow was open). The active probe is authoritative."""
    _patched_get_token(monkeypatch, _MemStore(token=_fresh_token()))
    get_login_session_registry().put(_pending_session())
    with respx.mock(base_url="https://graph.microsoft.com") as router:
        router.get(ME_URL).respond(json={"userPrincipalName": "x@x.de"})
        result = login_status(profile="default")
    assert result["status"] == "signed_in"


# ---------------------------------------------------------------------
# State 3 — `none`: no token AND no in-flight session
# ---------------------------------------------------------------------


def test_none_when_no_token_and_no_session(monkeypatch: pytest.MonkeyPatch) -> None:
    _patched_get_token(monkeypatch, _MemStore())
    result = login_status(profile="default")
    assert result == {"status": "none"}


# ---------------------------------------------------------------------
# Terminal session statuses (failed / expired / cancelled) → `none` + error
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected_msg_substr"),
    [
        ("failed", "failed"),
        ("expired", "expired"),
        ("cancelled", "cancelled"),
    ],
)
def test_terminal_session_status_folds_into_none_with_error(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    expected_msg_substr: str,
) -> None:
    """failed / expired / cancelled all surface as `none` so the
    agent's decision tree is uniform ("no usable session, call
    login_begin"). The specific reason is preserved in `error` for
    diagnostics + `previous_session_status` for telemetry."""
    _patched_get_token(monkeypatch, _MemStore())
    session = _pending_session()
    # Mutate to terminal
    session.status = status  # type: ignore[assignment]
    get_login_session_registry().put(session)

    result = login_status(profile="default")
    assert result["status"] == "none"
    assert result["previous_session_status"] == status
    assert result["error"] is not None
    assert expected_msg_substr in result["error"]["message"].lower()


def test_terminal_session_with_explicit_error_payload_is_passed_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ol_login_begin's polling task records a structured
    error (e.g. AADSTS70008), we pass it through verbatim — the
    agent can show the exact message to the user."""
    _patched_get_token(monkeypatch, _MemStore())
    session = _pending_session()
    session.status = "failed"
    session.error = {"code": "invalid_grant", "message": "AADSTS70008: refresh expired"}
    get_login_session_registry().put(session)

    result = login_status(profile="default")
    assert result["error"] == {
        "code": "invalid_grant",
        "message": "AADSTS70008: refresh expired",
    }


# ---------------------------------------------------------------------
# Per-profile isolation
# ---------------------------------------------------------------------


def test_profile_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Profile A having a session does NOT leak into profile B."""
    store = _MemStore()
    monkeypatch.setattr(
        "outlook_mcp.tools.login_status.get_token",
        lambda profile="default": get_token(profile=profile, store=store),
    )
    get_login_session_registry().put(_pending_session(profile="profile-a"))

    result_a = login_status(profile="profile-a")
    result_b = login_status(profile="profile-b")
    assert result_a["status"] == "pending"
    assert result_b == {"status": "none"}


# ---------------------------------------------------------------------
# /me request shape (User-Agent + Authorization invariants apply here too)
# ---------------------------------------------------------------------


@respx.mock
def test_me_call_carries_authorization_and_user_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patched_get_token(monkeypatch, _MemStore(token=_fresh_token()))
    route = respx.get(ME_URL).respond(json={"userPrincipalName": "x@x.de"})
    login_status(profile="default")
    headers = route.calls.last.request.headers
    assert headers["Authorization"] == "Bearer AT"
    assert headers["User-Agent"].startswith("mcp-server-outlook/")


@respx.mock
def test_me_call_passes_select_query_param(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reduce payload size — only the field we actually need."""
    _patched_get_token(monkeypatch, _MemStore(token=_fresh_token()))
    route = respx.get(ME_URL).respond(json={"userPrincipalName": "x@x.de"})
    login_status(profile="default")
    assert "%24select=userPrincipalName" in str(route.calls.last.request.url)
