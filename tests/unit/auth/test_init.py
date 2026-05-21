# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the public auth API (`get_token`, `interactive_login`).

Exercises the orchestration around the lower-level flow primitives:
cache-hit, refresh-on-expiry, refresh-rejected-clears-cache, BYO env
overrides, and the interactive-login full-cycle.
"""

from __future__ import annotations

import time

import pytest
import respx

from outlook_mcp.auth import (
    AGENT_INSTRUCTIONS,
    AuthRequiredError,
    DeviceCodeChallenge,
    _default_prompt,
    get_token,
    interactive_login,
)
from outlook_mcp.auth.flow import (
    DEFAULT_AUTHORITY_TENANT,
    DEFAULT_CLIENT_ID,
)
from outlook_mcp.auth.tokens import CachedToken

# ---------------------------------------------------------------------
# In-memory store fixture
# ---------------------------------------------------------------------


class _MemStore:
    def __init__(self) -> None:
        self._d: dict[str, bytes] = {}

    def get(self, profile: str) -> bytes | None:
        return self._d.get(profile)

    def set(self, profile: str, value: bytes) -> None:
        self._d[profile] = value

    def delete(self, profile: str) -> None:
        self._d.pop(profile, None)


@pytest.fixture
def store() -> _MemStore:
    return _MemStore()


@pytest.fixture(autouse=True)
def _ensure_delegated_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Most tests in this file exercise the delegated-mode code path.
    Clear the service-principal env vars so a polluted shell can't make
    them dispatch to the SP path."""
    monkeypatch.delenv("OUTLOOK_AUTH_MODE", raising=False)
    monkeypatch.delenv("OUTLOOK_CLIENT_SECRET", raising=False)


# ---------------------------------------------------------------------
# get_token — cache-hit / refresh / re-auth-required
# ---------------------------------------------------------------------


def test_get_token_returns_cached_when_fresh(store: _MemStore) -> None:
    fresh = CachedToken(
        access_token="AT-fresh",
        refresh_token="RT",
        expires_at=time.time() + 3600,
        scope="",
    )
    store.set("default", fresh.to_json().encode())
    assert get_token(store=store) == "AT-fresh"


def test_get_token_no_cache_raises_AuthRequiredError(store: _MemStore) -> None:
    with pytest.raises(AuthRequiredError, match="no cached credentials"):
        get_token(store=store)


def test_get_token_expired_no_refresh_raises_AuthRequiredError(store: _MemStore) -> None:
    expired = CachedToken(
        access_token="AT",
        refresh_token=None,
        expires_at=time.time() - 1,
        scope="",
    )
    store.set("default", expired.to_json().encode())
    with pytest.raises(AuthRequiredError, match="no refresh token"):
        get_token(store=store)


@respx.mock
def test_get_token_refreshes_when_expired(store: _MemStore) -> None:
    expired = CachedToken(
        access_token="AT-old",
        refresh_token="RT-1",
        expires_at=time.time() - 1,
        scope="",
    )
    store.set("default", expired.to_json().encode())

    refresh_url = f"https://login.microsoftonline.com/{DEFAULT_AUTHORITY_TENANT}/oauth2/v2.0/token"
    respx.post(refresh_url).respond(
        json={
            "access_token": "AT-new",
            "refresh_token": "RT-2",
            "expires_in": 3600,
            "scope": "",
            "token_type": "Bearer",
        }
    )

    assert get_token(store=store) == "AT-new"
    # Persisted updated token, including rotated refresh token
    raw = store.get("default")
    assert raw is not None
    new_cached = CachedToken.from_json(raw.decode())
    assert new_cached.access_token == "AT-new"
    assert new_cached.refresh_token == "RT-2"


@respx.mock
def test_get_token_invalid_refresh_clears_cache(store: _MemStore) -> None:
    expired = CachedToken(
        access_token="AT",
        refresh_token="RT-stale",
        expires_at=time.time() - 1,
        scope="",
    )
    store.set("default", expired.to_json().encode())

    refresh_url = f"https://login.microsoftonline.com/{DEFAULT_AUTHORITY_TENANT}/oauth2/v2.0/token"
    respx.post(refresh_url).respond(
        400,
        json={"error": "invalid_grant", "error_description": "AADSTS70008"},
    )

    with pytest.raises(AuthRequiredError, match="rejected"):
        get_token(store=store)
    # Cache cleared so next call doesn't re-attempt the bad refresh token
    assert store.get("default") is None


# ---------------------------------------------------------------------
# BYO env-var override
# ---------------------------------------------------------------------


@respx.mock
def test_get_token_byo_client_id_from_env(
    store: _MemStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    expired = CachedToken(
        access_token="old",
        refresh_token="RT",
        expires_at=time.time() - 1,
        scope="",
    )
    store.set("default", expired.to_json().encode())
    monkeypatch.setenv("OUTLOOK_CLIENT_ID", "byo-client-id")

    route = respx.post(
        f"https://login.microsoftonline.com/{DEFAULT_AUTHORITY_TENANT}/oauth2/v2.0/token"
    ).respond(
        json={
            "access_token": "AT",
            "refresh_token": "RT2",
            "expires_in": 3600,
            "scope": "",
            "token_type": "Bearer",
        }
    )
    get_token(store=store)
    body = route.calls.last.request.read().decode()
    assert "client_id=byo-client-id" in body


@respx.mock
def test_get_token_byo_tenant_from_env(store: _MemStore, monkeypatch: pytest.MonkeyPatch) -> None:
    expired = CachedToken(
        access_token="old",
        refresh_token="RT",
        expires_at=time.time() - 1,
        scope="",
    )
    store.set("default", expired.to_json().encode())
    monkeypatch.setenv("OUTLOOK_TENANT_ID", "byo-tenant-guid")

    respx.post("https://login.microsoftonline.com/byo-tenant-guid/oauth2/v2.0/token").respond(
        json={
            "access_token": "AT",
            "refresh_token": "RT2",
            "expires_in": 3600,
            "scope": "",
            "token_type": "Bearer",
        }
    )
    assert get_token(store=store) == "AT"


def test_get_token_explicit_kwarg_beats_env(
    store: _MemStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit kwarg precedence: caller > env > built-in default."""
    monkeypatch.setenv("OUTLOOK_CLIENT_ID", "should-be-ignored")
    fresh = CachedToken(
        access_token="AT",
        refresh_token="RT",
        expires_at=time.time() + 3600,
        scope="",
    )
    store.set("default", fresh.to_json().encode())
    # No HTTP call needed — token is fresh — but the function still goes through
    # _resolve_client_id and the explicit value should win silently.
    get_token(store=store, client_id="explicit-wins")


# ---------------------------------------------------------------------
# interactive_login — full Device Code flow
# ---------------------------------------------------------------------


@respx.mock
def test_interactive_login_full_flow_persists_token(store: _MemStore) -> None:
    base = f"https://login.microsoftonline.com/{DEFAULT_AUTHORITY_TENANT}/oauth2/v2.0"
    respx.post(f"{base}/devicecode").respond(
        json={
            "device_code": "DC-secret",
            "user_code": "USR-CODE",
            "verification_uri": "https://microsoft.com/devicelogin",
            "expires_in": 900,
            "interval": 1,
            "message": "Go to URL",
        }
    )
    respx.post(f"{base}/token").respond(
        200,
        json={
            "access_token": "AT-final",
            "refresh_token": "RT-final",
            "expires_in": 3600,
            "scope": "Mail.Read offline_access",
            "token_type": "Bearer",
        },
    )

    captured: list[DeviceCodeChallenge] = []
    cached = interactive_login(
        store=store,
        prompt=captured.append,
    )

    assert cached.access_token == "AT-final"
    assert cached.refresh_token == "RT-final"
    raw = store.get("default")
    assert raw is not None
    persisted = CachedToken.from_json(raw.decode())
    assert persisted == cached
    assert len(captured) == 1
    assert captured[0].user_code == "USR-CODE"
    assert captured[0].verification_uri == "https://microsoft.com/devicelogin"


@respx.mock
def test_interactive_login_uses_default_client_id(store: _MemStore) -> None:
    """No OUTLOOK_CLIENT_ID env, no explicit kwarg -> XMV-published default."""
    base = f"https://login.microsoftonline.com/{DEFAULT_AUTHORITY_TENANT}/oauth2/v2.0"
    devcode_route = respx.post(f"{base}/devicecode").respond(
        json={
            "device_code": "DC",
            "user_code": "U",
            "verification_uri": "x",
            "expires_in": 1,
            "interval": 1,
            "message": "",
        }
    )
    respx.post(f"{base}/token").respond(
        200,
        json={
            "access_token": "AT",
            "refresh_token": "RT",
            "expires_in": 3600,
            "scope": "",
            "token_type": "Bearer",
        },
    )
    interactive_login(store=store, prompt=lambda _ch: None)
    body = devcode_route.calls.last.request.read().decode()
    assert f"client_id={DEFAULT_CLIENT_ID}" in body


# ---------------------------------------------------------------------
# get_token — service-principal dispatch
# ---------------------------------------------------------------------


@respx.mock
def test_get_token_routes_to_service_principal_when_mode_set(
    monkeypatch: pytest.MonkeyPatch, store: _MemStore
) -> None:
    """OUTLOOK_AUTH_MODE=service-principal: skip TokenStore, hit /token directly."""
    from outlook_mcp.auth.flow import AUTHORITY_BASE
    from outlook_mcp.auth.service_principal import reset_cache

    reset_cache()
    monkeypatch.setenv("OUTLOOK_AUTH_MODE", "service-principal")
    monkeypatch.setenv("OUTLOOK_CLIENT_ID", "cid")
    monkeypatch.setenv("OUTLOOK_CLIENT_SECRET", "secret")
    monkeypatch.setenv("OUTLOOK_TENANT_ID", "tenant-x")
    respx.post(f"{AUTHORITY_BASE}/tenant-x/oauth2/v2.0/token").respond(
        json={"access_token": "AT-sp", "expires_in": 3600, "scope": ""},
    )
    # store contains nothing — but in SP mode we should bypass it entirely
    assert get_token(store=store) == "AT-sp"


@respx.mock
def test_get_token_auto_detects_service_principal_via_secret(
    monkeypatch: pytest.MonkeyPatch, store: _MemStore
) -> None:
    """OUTLOOK_CLIENT_SECRET alone (no OUTLOOK_AUTH_MODE) auto-detects SP mode."""
    from outlook_mcp.auth.flow import AUTHORITY_BASE
    from outlook_mcp.auth.service_principal import reset_cache

    reset_cache()
    monkeypatch.delenv("OUTLOOK_AUTH_MODE", raising=False)
    monkeypatch.setenv("OUTLOOK_CLIENT_ID", "cid")
    monkeypatch.setenv("OUTLOOK_CLIENT_SECRET", "secret")
    monkeypatch.setenv("OUTLOOK_TENANT_ID", "tenant-y")
    respx.post(f"{AUTHORITY_BASE}/tenant-y/oauth2/v2.0/token").respond(
        json={"access_token": "AT-sp-auto", "expires_in": 3600, "scope": ""},
    )
    assert get_token(store=store) == "AT-sp-auto"


def test_get_token_explicit_delegated_overrides_secret_presence(
    monkeypatch: pytest.MonkeyPatch, store: _MemStore
) -> None:
    """OUTLOOK_AUTH_MODE=delegated wins even if OUTLOOK_CLIENT_SECRET is also set."""
    monkeypatch.setenv("OUTLOOK_AUTH_MODE", "delegated")
    monkeypatch.setenv("OUTLOOK_CLIENT_SECRET", "secret")
    # No cached token: delegated mode would raise AuthRequiredError;
    # SP mode would raise ServicePrincipalConfigError. We expect the
    # former.
    with pytest.raises(AuthRequiredError, match="no cached credentials"):
        get_token(store=store)


# ---------------------------------------------------------------------
# AGENT_INSTRUCTIONS rendering — closes #42
# ---------------------------------------------------------------------


def _challenge(
    code: str = "ABCD-1234",
    uri: str = "https://aka.ms/devicelogin",
) -> DeviceCodeChallenge:
    return DeviceCodeChallenge(
        user_code=code,
        verification_uri=uri,
        verification_uri_complete=None,
        expires_at=time.time() + 900,
        interval=5,
        message="msg",
    )


def test_default_prompt_emits_agent_instructions_marker(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The literal `AGENT_INSTRUCTIONS:` marker is in the stderr output so
    a pattern-matching MCP-client can detect it."""
    _default_prompt(_challenge())
    err = capsys.readouterr().err
    assert "AGENT_INSTRUCTIONS:" in err


def test_default_prompt_wraps_code_in_fenced_block(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An agent that copies the stderr verbatim still gets the right visual
    output: the code is already inside ```...```."""
    _default_prompt(_challenge(code="XYZ-9999"))
    err = capsys.readouterr().err
    assert "```\nXYZ-9999\n```" in err


def test_default_prompt_emits_url_as_bare_link(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The verification URL appears as a bare URL on its own line — no `URL:`
    prefix, no quoting — so chat UIs that auto-link bare URLs render it as
    clickable."""
    _default_prompt(_challenge(uri="https://login.microsoftonline.com/common/oauth2/deviceauth"))
    err = capsys.readouterr().err
    assert "Sign-in URL: https://login.microsoftonline.com/common/oauth2/deviceauth" in err


def test_default_prompt_does_not_wrap_url_in_quotes_or_backticks(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Regression guard: previously the URL was prefixed with `URL:` and indented,
    which prevented chat UIs from auto-linking it."""
    _default_prompt(_challenge(uri="https://example.com/auth"))
    err = capsys.readouterr().err
    assert "`https://example.com/auth`" not in err
    assert "     URL:" not in err


def test_default_prompt_includes_no_paraphrase_clause(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The 'Do not paraphrase' rule is what stops well-meaning models from
    formatting it 'helpfully'."""
    _default_prompt(_challenge())
    err = capsys.readouterr().err
    assert "Do not paraphrase" in err


def test_agent_instructions_constant_is_stable_string() -> None:
    """The constant is a single string — agents pattern-match on the literal
    `AGENT_INSTRUCTIONS:` prefix, so don't make it a template with placeholders."""
    assert AGENT_INSTRUCTIONS.startswith("AGENT_INSTRUCTIONS:")
    assert "fenced code block" in AGENT_INSTRUCTIONS
    assert "markdown link" in AGENT_INSTRUCTIONS
