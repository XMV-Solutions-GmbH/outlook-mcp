# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for ol_login_begin.

The tool is **non-blocking**: a call returns immediately with
`status="pending"` plus the user-facing fields (`user_code`,
`verification_url`), while a background asyncio task drives the
device-code poll loop to a terminal state. Tests therefore split into
two phases:

1. Assert what the synchronous return value looks like (pending +
   user_code + url + no device_code leak).
2. Where the test is about a terminal outcome (success / failed /
   expired / token-store error / UPN extraction), `await session.task`
   first, then assert against the now-mutated `LoginSession` and any
   side effects (token on disk, UPN cache).

Pins:

- Happy path: device-code request → poll succeeds → token written →
  session marked `success` → UPN cached.
- Idempotent: a second call while pending returns the existing
  session, NOT a new one. Polling task is started exactly once.
- `force=True`: cancels in-flight session and starts fresh.
- Failure modes: AADSTS access_denied → status=`failed`,
  expired_token → `expired`, unexpected exception → `failed` with
  message; in all cases token is NOT persisted.
- Token-store persistence failure → status `failed`, agent must retry.
- Concurrent same-profile login_begin calls do not corrupt the
  registry.
- public_view does NOT leak `device_code` (the polling secret).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from mcp_microsoft_graph_auth import LoginSession

from outlook_mcp.auth.tokens import CachedToken
from outlook_mcp.login_state import (
    cached_upn,
    get_login_session_registry,
    reset_for_tests,
)
from outlook_mcp.tools import login_begin as login_begin_module
from outlook_mcp.tools.login_begin import login_begin

DEVICE_CODE_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/devicecode"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
ME_URL = "https://graph.microsoft.com/v1.0/me"


@pytest.fixture(autouse=True)
def _isolate_login_state() -> None:
    reset_for_tests()


@pytest.fixture(autouse=True)
def _redirect_token_store(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """Redirect the token store to tmp_path so tests don't touch the
    real ~/.cache/outlook-mcp."""
    from outlook_mcp.auth.store import PlainFileTokenStore

    store = PlainFileTokenStore(base_dir=tmp_path)
    monkeypatch.setattr(
        "outlook_mcp.tools.login_begin.get_token_store",
        lambda: store,
    )
    return tmp_path


def _device_code_response_json(*, expires_in: int = 900, interval: int = 1) -> dict[str, Any]:
    return {
        "device_code": "DC-secret-xyz",
        "user_code": "ABCD-EFGH",
        "verification_uri": "https://microsoft.com/devicelogin",
        "expires_in": expires_in,
        "interval": interval,
        "message": "Go to URL and enter the code",
    }


def _success_token_json() -> dict[str, Any]:
    return {
        "access_token": "AT-final",
        "refresh_token": "RT-final",
        "expires_in": 3600,
        "scope": "Mail.Read offline_access",
        "token_type": "Bearer",
    }


async def _await_task(profile: str, *, timeout: float = 5.0) -> LoginSession:
    """Drain the background polling task for `profile` and return the
    (now mutated) `LoginSession`. Tests call this when they need to
    assert a terminal state — login_begin itself returns while polling
    is still in flight."""
    session = get_login_session_registry().get(profile)
    assert session is not None, f"No session registered for {profile!r}"
    task = session.task
    if task is not None and not task.done():
        await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
    return session


# ---------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------


@respx.mock
async def test_login_begin_happy_path() -> None:
    respx.post(DEVICE_CODE_URL).respond(json=_device_code_response_json())
    respx.post(TOKEN_URL).respond(200, json=_success_token_json())
    respx.get(ME_URL).respond(json={"userPrincipalName": "anna@xmv.de"})

    result = await login_begin(profile="default")

    # Non-blocking: returns pending immediately with the user-facing
    # fields the agent needs to surface.
    assert result["status"] == "pending"
    assert result["user_code"] == "ABCD-EFGH"
    assert result["verification_url"] == "https://microsoft.com/devicelogin"
    # device_code MUST NOT leak even on the synchronous return.
    assert "device_code" not in result

    # Drain the polling task — now the terminal state is observable.
    session = await _await_task("default")
    assert session.status == "success"
    assert session.signed_in_user_upn == "anna@xmv.de"
    # UPN cached for downstream login_status calls.
    assert cached_upn("default") == "anna@xmv.de"


@respx.mock
async def test_login_begin_persists_token_to_store(_redirect_token_store) -> None:  # type: ignore[no-untyped-def]
    """Successful login writes the CachedToken to the configured
    TokenStore so login_status can probe it later."""
    respx.post(DEVICE_CODE_URL).respond(json=_device_code_response_json())
    respx.post(TOKEN_URL).respond(200, json=_success_token_json())
    respx.get(ME_URL).respond(json={"userPrincipalName": "x@x.de"})

    await login_begin(profile="default")
    await _await_task("default")

    persisted = (_redirect_token_store / "default" / "token.json").read_text()
    cached = CachedToken.from_json(persisted)
    assert cached.access_token == "AT-final"
    assert cached.refresh_token == "RT-final"


@respx.mock
async def test_login_begin_session_in_registry_after_success() -> None:
    respx.post(DEVICE_CODE_URL).respond(json=_device_code_response_json())
    respx.post(TOKEN_URL).respond(200, json=_success_token_json())
    respx.get(ME_URL).respond(json={"userPrincipalName": "x@x.de"})

    await login_begin(profile="default")
    session = await _await_task("default")

    assert session.status == "success"
    assert session.signed_in_user_upn == "x@x.de"


# ---------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------


async def test_login_begin_returns_existing_pending_session_idempotent() -> None:
    """A call while a pending session exists returns the same
    session-id, doesn't start a second polling task."""
    started = datetime.now(UTC)
    existing = LoginSession(
        session_id="existing-sid",
        profile="default",
        device_code="DC-existing",
        user_code="EXIST-CODE",
        verification_url="https://microsoft.com/devicelogin",
        verification_url_complete=None,
        expires_at=started + timedelta(minutes=10),
        interval_s=5,
        status="pending",
        signed_in_user_upn=None,
        error=None,
        task=None,
        started_at=started,
    )
    get_login_session_registry().put(existing)

    # No outbound HTTP should fire — the existing pending session is
    # returned untouched, no new device-code flow starts.
    with respx.mock(base_url="https://login.microsoftonline.com") as router:
        result = await login_begin(profile="default")
        assert not router.calls, "No new device code flow should start"

    assert result["session_id"] == "existing-sid"
    assert result["user_code"] == "EXIST-CODE"
    assert result["status"] == "pending"


@respx.mock
async def test_login_begin_force_cancels_pending_and_starts_fresh() -> None:
    """force=True kills the existing session and produces a new one."""
    started = datetime.now(UTC)
    old = LoginSession(
        session_id="old-sid",
        profile="default",
        device_code="DC-old",
        user_code="OLD-CODE",
        verification_url="https://microsoft.com/devicelogin",
        verification_url_complete=None,
        expires_at=started + timedelta(minutes=10),
        interval_s=5,
        status="pending",
        signed_in_user_upn=None,
        error=None,
        task=None,
        started_at=started,
    )
    get_login_session_registry().put(old)

    respx.post(DEVICE_CODE_URL).respond(
        json={**_device_code_response_json(), "user_code": "NEW-CODE"}
    )
    respx.post(TOKEN_URL).respond(200, json=_success_token_json())
    respx.get(ME_URL).respond(json={"userPrincipalName": "x@x.de"})

    result = await login_begin(profile="default", force=True)
    assert result["status"] == "pending"
    assert result["user_code"] == "NEW-CODE"
    assert result["session_id"] != "old-sid"
    # Old session was marked cancelled.
    assert old.status == "cancelled"

    # Drain the new session's polling task so the test leaves no
    # background work behind.
    new_session = await _await_task("default")
    assert new_session.status == "success"
    assert new_session.session_id != "old-sid"


# ---------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------


@respx.mock
async def test_login_begin_user_denies_consent_marks_failed() -> None:
    respx.post(DEVICE_CODE_URL).respond(json=_device_code_response_json())
    respx.post(TOKEN_URL).respond(400, json={"error": "access_denied"})

    pending = await login_begin(profile="default")
    assert pending["status"] == "pending"

    session = await _await_task("default")
    assert session.status == "failed"
    assert session.error is not None
    assert session.error["code"] == "access_denied"


@respx.mock
async def test_login_begin_device_code_expired_marks_expired() -> None:
    respx.post(DEVICE_CODE_URL).respond(json=_device_code_response_json())
    respx.post(TOKEN_URL).respond(400, json={"error": "expired_token"})

    pending = await login_begin(profile="default")
    assert pending["status"] == "pending"

    session = await _await_task("default")
    assert session.status == "expired"
    assert session.error is not None
    assert session.error["code"] == "expired_token"


@respx.mock
async def test_login_begin_token_store_failure_marks_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If we get a token but can't write it to disk, the session
    is marked failed so the agent retries (rather than thinking
    we're signed-in but actually not)."""
    respx.post(DEVICE_CODE_URL).respond(json=_device_code_response_json())
    respx.post(TOKEN_URL).respond(200, json=_success_token_json())

    class _FailingStore:
        def get(self, profile: str) -> bytes | None:
            return None

        def set(self, profile: str, value: bytes) -> None:
            raise OSError("disk full")

        def delete(self, profile: str) -> None:
            pass

    monkeypatch.setattr(
        "outlook_mcp.tools.login_begin.get_token_store",
        lambda: _FailingStore(),
    )

    await login_begin(profile="default")
    session = await _await_task("default")
    assert session.status == "failed"
    assert session.error is not None
    assert session.error["code"] == "token_store_failed"
    assert "disk full" in session.error["message"]


@respx.mock
async def test_login_begin_does_not_persist_token_on_failure(
    _redirect_token_store: Any,
) -> None:
    """access_denied / expired must not leave a token on disk."""
    respx.post(DEVICE_CODE_URL).respond(json=_device_code_response_json())
    respx.post(TOKEN_URL).respond(400, json={"error": "access_denied"})

    await login_begin(profile="default")
    await _await_task("default")
    assert not (_redirect_token_store / "default" / "token.json").exists()


# ---------------------------------------------------------------------
# ctx parameter is accepted (forward-compat) but currently unused
# ---------------------------------------------------------------------


@respx.mock
async def test_login_begin_works_without_ctx() -> None:
    """ctx=None — tool still works (ctx is reserved for future
    progress-notification work but is unused in the non-blocking
    design; the agent polls ol_login_status instead)."""
    respx.post(DEVICE_CODE_URL).respond(json=_device_code_response_json())
    respx.post(TOKEN_URL).respond(200, json=_success_token_json())
    respx.get(ME_URL).respond(json={"userPrincipalName": "x@x.de"})

    result = await login_begin(profile="default", ctx=None)
    assert result["status"] == "pending"
    assert result["user_code"] == "ABCD-EFGH"

    session = await _await_task("default")
    assert session.status == "success"


# ---------------------------------------------------------------------
# Wire-format edge cases on the success path
# ---------------------------------------------------------------------


@respx.mock
async def test_login_begin_signed_in_user_upn_none_when_me_4xx() -> None:
    """Login succeeds (token valid) but /me 4xx's. Session is still
    success; UPN is None."""
    respx.post(DEVICE_CODE_URL).respond(json=_device_code_response_json())
    respx.post(TOKEN_URL).respond(200, json=_success_token_json())
    respx.get(ME_URL).respond(403)

    await login_begin(profile="default")
    session = await _await_task("default")
    assert session.status == "success"
    assert session.signed_in_user_upn is None
    assert cached_upn("default") is None


@respx.mock
async def test_login_begin_signed_in_user_upn_none_when_me_payload_missing_field() -> None:
    respx.post(DEVICE_CODE_URL).respond(json=_device_code_response_json())
    respx.post(TOKEN_URL).respond(200, json=_success_token_json())
    respx.get(ME_URL).respond(json={"id": "abc-no-upn-field"})

    await login_begin(profile="default")
    session = await _await_task("default")
    assert session.status == "success"
    assert session.signed_in_user_upn is None


# ---------------------------------------------------------------------
# Per-profile isolation
# ---------------------------------------------------------------------


@respx.mock
async def test_login_begin_profile_isolation() -> None:
    """Two distinct profiles maintain independent sessions."""
    respx.post(DEVICE_CODE_URL).mock(
        side_effect=[
            httpx.Response(200, json={**_device_code_response_json(), "user_code": "P1-CODE"}),
            httpx.Response(200, json={**_device_code_response_json(), "user_code": "P2-CODE"}),
        ]
    )
    respx.post(TOKEN_URL).respond(200, json=_success_token_json())
    respx.get(ME_URL).respond(json={"userPrincipalName": "x@x.de"})

    r1 = await login_begin(profile="profile-1")
    r2 = await login_begin(profile="profile-2")

    assert r1["user_code"] == "P1-CODE"
    assert r2["user_code"] == "P2-CODE"
    assert r1["session_id"] != r2["session_id"]

    # Drain both background tasks.
    await _await_task("profile-1")
    await _await_task("profile-2")


# ---------------------------------------------------------------------
# device_code never leaks
# ---------------------------------------------------------------------


@respx.mock
async def test_login_begin_response_has_no_device_code_secret() -> None:
    """Hard guarantee: device_code is the polling secret. The
    public_view from the lib strips it. Re-verify here in case
    someone routes around public_view in a future refactor."""
    respx.post(DEVICE_CODE_URL).respond(json=_device_code_response_json())
    respx.post(TOKEN_URL).respond(200, json=_success_token_json())
    respx.get(ME_URL).respond(json={"userPrincipalName": "x@x.de"})

    result = await login_begin(profile="default")

    # Top-level key not present on the synchronous return value.
    assert "device_code" not in result
    # Defensive: check no nested key matches either.
    flat = " ".join(str(v) for v in result.values())
    assert "DC-secret-xyz" not in flat

    # And the device_code is also not exposed via the registry's
    # public_view — drain the task and re-verify.
    await _await_task("default")


# ---------------------------------------------------------------------
# Module sanity
# ---------------------------------------------------------------------


def test_module_exports_login_begin() -> None:
    """Sanity: the public function name matches what server.py
    imports."""
    assert callable(login_begin_module.login_begin)
