# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the OAuth Device Code + refresh-token flow.

All HTTP calls intercepted via respx; no Microsoft Identity touched.
Polling timing made deterministic via injected `sleep` and `now`.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
import respx

from outlook_mcp.auth.flow import (
    ACCOUNT_TYPE_PERSONAL,
    ACCOUNT_TYPE_WORK_OR_SCHOOL,
    DEFAULT_AUTHORITY_TENANT,
    VALID_ACCOUNT_TYPES,
    AuthorizationDeniedError,
    DeviceCodeError,
    DeviceCodeExpiredError,
    LoginAccountTypeRequiredError,
    RefreshTokenInvalidError,
    account_type_to_tenant,
    poll_for_token,
    refresh_access_token,
    request_device_code,
)

CLIENT_ID = "test-client-id"
TENANT = "test-tenant"
DEVICE_CODE_URL = f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/devicecode"
TOKEN_URL = f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token"


# ---------------------------------------------------------------------
# request_device_code
# ---------------------------------------------------------------------


@respx.mock
def test_request_device_code_returns_secret_and_challenge() -> None:
    """Microsoft Identity v2.0 — no verification_uri_complete in response."""
    respx.post(DEVICE_CODE_URL).respond(
        json={
            "device_code": "DC-XYZ",
            "user_code": "ABC-123",
            "verification_uri": "https://microsoft.com/devicelogin",
            "expires_in": 900,
            "interval": 5,
            "message": "go to URL and enter ABC-123",
        }
    )
    device_code, challenge = request_device_code(client_id=CLIENT_ID, tenant=TENANT)
    assert device_code == "DC-XYZ"
    assert challenge.user_code == "ABC-123"
    assert challenge.verification_uri == "https://microsoft.com/devicelogin"
    assert challenge.verification_uri_complete is None
    assert challenge.interval == 5


@respx.mock
def test_request_device_code_captures_verification_uri_complete_if_provided() -> None:
    """RFC 8628 §3.3.1 — some OAuth providers populate this; we capture it."""
    respx.post(DEVICE_CODE_URL).respond(
        json={
            "device_code": "DC",
            "user_code": "ABC123",
            "verification_uri": "https://example.com/devicelogin",
            "verification_uri_complete": "https://example.com/devicelogin?code=ABC123",
            "expires_in": 900,
            "interval": 5,
            "message": "",
        }
    )
    _, challenge = request_device_code(client_id=CLIENT_ID, tenant=TENANT)
    assert challenge.verification_uri_complete == "https://example.com/devicelogin?code=ABC123"


@respx.mock
def test_request_device_code_sends_client_id_and_scopes() -> None:
    route = respx.post(DEVICE_CODE_URL).respond(
        json={
            "device_code": "DC",
            "user_code": "U",
            "verification_uri": "x",
            "expires_in": 1,
            "interval": 1,
            "message": "",
        }
    )
    request_device_code(client_id=CLIENT_ID, tenant=TENANT, scopes=("Mail.Read",))
    body = route.calls.last.request.read().decode()
    assert "client_id=test-client-id" in body
    assert "Mail.Read" in body


# ---------------------------------------------------------------------
# poll_for_token — happy path + the four documented error codes + cap
# ---------------------------------------------------------------------


@respx.mock
def test_poll_for_token_immediate_success() -> None:
    respx.post(TOKEN_URL).respond(
        json={
            "access_token": "AT-1",
            "refresh_token": "RT-1",
            "expires_in": 3600,
            "scope": "Mail.Read offline_access",
            "token_type": "Bearer",
        }
    )
    sleeps: list[float] = []
    cached = poll_for_token(
        device_code="DC",
        client_id=CLIENT_ID,
        tenant=TENANT,
        interval=5,
        sleep=sleeps.append,
        now=_fake_clock(0, [0, 0]),
    )
    assert cached.access_token == "AT-1"
    assert cached.refresh_token == "RT-1"
    assert cached.scope == "Mail.Read offline_access"
    assert sleeps == [5]


@respx.mock
def test_poll_for_token_pending_then_success() -> None:
    respx.post(TOKEN_URL).mock(
        side_effect=[
            httpx.Response(400, json={"error": "authorization_pending"}),
            httpx.Response(400, json={"error": "authorization_pending"}),
            httpx.Response(
                200,
                json={
                    "access_token": "AT-after-wait",
                    "refresh_token": "RT-after-wait",
                    "expires_in": 3600,
                    "scope": "",
                    "token_type": "Bearer",
                },
            ),
        ]
    )
    sleeps: list[float] = []
    cached = poll_for_token(
        device_code="DC",
        client_id=CLIENT_ID,
        tenant=TENANT,
        interval=5,
        sleep=sleeps.append,
        now=_fake_clock(0, [0, 0, 0, 0, 0, 0, 0]),
    )
    assert cached.access_token == "AT-after-wait"
    assert sleeps == [5, 5, 5]


@respx.mock
def test_poll_for_token_slow_down_increases_interval() -> None:
    respx.post(TOKEN_URL).mock(
        side_effect=[
            httpx.Response(400, json={"error": "slow_down"}),
            httpx.Response(
                200,
                json={
                    "access_token": "AT",
                    "refresh_token": "RT",
                    "expires_in": 3600,
                    "scope": "",
                    "token_type": "Bearer",
                },
            ),
        ]
    )
    sleeps: list[float] = []
    poll_for_token(
        device_code="DC",
        client_id=CLIENT_ID,
        tenant=TENANT,
        interval=5,
        sleep=sleeps.append,
        now=_fake_clock(0, [0, 0, 0, 0, 0]),
    )
    # First sleep was the original interval (5), second slept 10 after slow_down
    assert sleeps == [5, 10]


@respx.mock
def test_poll_for_token_expired_raises_DeviceCodeExpiredError() -> None:
    respx.post(TOKEN_URL).respond(400, json={"error": "expired_token"})
    with pytest.raises(DeviceCodeExpiredError):
        poll_for_token(
            device_code="DC",
            client_id=CLIENT_ID,
            tenant=TENANT,
            interval=1,
            sleep=lambda _: None,
            now=_fake_clock(0, [0, 0]),
        )


@respx.mock
def test_poll_for_token_access_denied_raises_AuthorizationDeniedError() -> None:
    respx.post(TOKEN_URL).respond(400, json={"error": "access_denied"})
    with pytest.raises(AuthorizationDeniedError):
        poll_for_token(
            device_code="DC",
            client_id=CLIENT_ID,
            tenant=TENANT,
            interval=1,
            sleep=lambda _: None,
            now=_fake_clock(0, [0, 0]),
        )


@respx.mock
def test_poll_for_token_max_duration_cap() -> None:
    """Even if Microsoft never resolves, we cap the loop at MAX_POLL_DURATION."""
    respx.post(TOKEN_URL).respond(400, json={"error": "authorization_pending"})
    times = iter([0, 0, 100, 100, 1300, 1300])
    with pytest.raises(DeviceCodeExpiredError, match="exceeded"):
        poll_for_token(
            device_code="DC",
            client_id=CLIENT_ID,
            tenant=TENANT,
            interval=1,
            sleep=lambda _: None,
            now=lambda: next(times),
        )


@respx.mock
def test_poll_for_token_unexpected_error_raises_DeviceCodeError() -> None:
    respx.post(TOKEN_URL).respond(400, json={"error": "internal_error"})
    with pytest.raises((DeviceCodeError, httpx.HTTPStatusError)):
        poll_for_token(
            device_code="DC",
            client_id=CLIENT_ID,
            tenant=TENANT,
            interval=1,
            sleep=lambda _: None,
            now=_fake_clock(0, [0, 0]),
        )


# ---------------------------------------------------------------------
# refresh_access_token
# ---------------------------------------------------------------------


@respx.mock
def test_refresh_access_token_success() -> None:
    respx.post(TOKEN_URL).respond(
        json={
            "access_token": "AT-new",
            "refresh_token": "RT-rotated",
            "expires_in": 3600,
            "scope": "Mail.Read",
            "token_type": "Bearer",
        }
    )
    cached = refresh_access_token(
        refresh_token="RT-old",
        client_id=CLIENT_ID,
        tenant=TENANT,
    )
    assert cached.access_token == "AT-new"
    assert cached.refresh_token == "RT-rotated"


@respx.mock
def test_refresh_access_token_invalid_grant_raises() -> None:
    respx.post(TOKEN_URL).respond(
        400,
        json={"error": "invalid_grant", "error_description": "AADSTS70008: refresh expired"},
    )
    with pytest.raises(RefreshTokenInvalidError, match="AADSTS70008"):
        refresh_access_token(refresh_token="RT-stale", client_id=CLIENT_ID, tenant=TENANT)


@respx.mock
def test_refresh_access_token_other_error_raises() -> None:
    respx.post(TOKEN_URL).respond(500)
    with pytest.raises(httpx.HTTPStatusError):
        refresh_access_token(refresh_token="RT", client_id=CLIENT_ID, tenant=TENANT)


@respx.mock
def test_refresh_uses_default_tenant_when_not_specified() -> None:
    """Defaults coverage — exercising DEFAULT_AUTHORITY_TENANT (no tenant kwarg)."""
    default_url = f"https://login.microsoftonline.com/{DEFAULT_AUTHORITY_TENANT}/oauth2/v2.0/token"
    respx.post(default_url).respond(
        json={
            "access_token": "AT",
            "refresh_token": "RT",
            "expires_in": 3600,
            "scope": "",
            "token_type": "Bearer",
        }
    )
    cached = refresh_access_token(refresh_token="RT-old", client_id=CLIENT_ID)
    assert cached.access_token == "AT"


# ---------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------


def _fake_clock(start: float, ticks: list[float]) -> Callable[[], float]:
    """Return a `now()` callable that yields the provided values in order."""
    iterator = iter(ticks)

    def now() -> float:
        try:
            return next(iterator)
        except StopIteration:
            return start

    return now


# ---------------------------------------------------------------------
# account_type → tenant mapping (#49)
# ---------------------------------------------------------------------


def test_account_type_to_tenant_personal_maps_to_consumers() -> None:
    """Personal MSAs route through Microsoft Identity's /consumers
    authority — that's the only path that returns the personal
    Device Code landing page (microsoft.com/link)."""
    assert account_type_to_tenant(ACCOUNT_TYPE_PERSONAL) == "consumers"


def test_account_type_to_tenant_work_maps_to_organizations() -> None:
    """Work/school accounts route through /organizations, NOT /common.
    /common returns the work/school landing page even for personal-
    capable apps; we use /organizations for an explicit choice."""
    assert account_type_to_tenant(ACCOUNT_TYPE_WORK_OR_SCHOOL) == "organizations"


@pytest.mark.parametrize("bad", ["", "common", "consumers", "Personal", "WORK_OR_SCHOOL", "privat"])
def test_account_type_to_tenant_rejects_unknown(bad: str) -> None:
    """Strict per #49 — typos must raise loudly, never silently fall
    through to a wrong endpoint."""
    with pytest.raises(ValueError, match="account_type"):
        account_type_to_tenant(bad)


def test_valid_account_types_constant_matches_two_values() -> None:
    """The literal tuple is the public contract that callers
    (CLI choices, MCP-tool descriptions) hang their UI off."""
    assert VALID_ACCOUNT_TYPES == ("personal", "work_or_school")
    assert ACCOUNT_TYPE_PERSONAL == "personal"
    assert ACCOUNT_TYPE_WORK_OR_SCHOOL == "work_or_school"


# ---------------------------------------------------------------------
# LoginAccountTypeRequiredError (#49)
# ---------------------------------------------------------------------


def test_login_account_type_required_error_default_message_includes_both_values() -> None:
    """The default message is what the MCP-tool layer surfaces to the
    agent. It MUST name both valid values verbatim — the agent uses
    those strings to retry the tool call."""
    err = LoginAccountTypeRequiredError()
    msg = str(err)
    assert "personal" in msg
    assert "work_or_school" in msg


def test_login_account_type_required_error_mentions_outlook_com() -> None:
    """Help text should hint at concrete account-domain examples so
    the user can recognise their account kind. Without this hint
    users sometimes pick the wrong option."""
    err = LoginAccountTypeRequiredError()
    assert "outlook.com" in str(err)


def test_login_account_type_required_error_has_agent_instructions_marker() -> None:
    """Stable marker `AGENT_INSTRUCTIONS:` lets MCP clients pattern-
    match the error and route it to the user-elicitation UI rather
    than just rendering it as plain text."""
    assert "AGENT_INSTRUCTIONS:" in str(LoginAccountTypeRequiredError())


def test_login_account_type_required_error_accepts_custom_message() -> None:
    """Callers can override with profile-specific text if they want;
    default stays the safe one."""
    custom = LoginAccountTypeRequiredError("custom override text")
    assert str(custom) == "custom override text"
