# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the service-principal / client-credentials auth path."""

from __future__ import annotations

import pytest
import respx

from outlook_mcp.auth.flow import AUTHORITY_BASE
from outlook_mcp.auth.service_principal import (
    ServicePrincipalConfigError,
    acquire_app_only_token,
    get_app_only_token,
    is_service_principal_mode,
    reset_cache,
)


@pytest.fixture(autouse=True)
def _isolate_cache_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_cache()
    monkeypatch.delenv("OUTLOOK_AUTH_MODE", raising=False)
    monkeypatch.delenv("OUTLOOK_CLIENT_ID", raising=False)
    monkeypatch.delenv("OUTLOOK_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("OUTLOOK_TENANT_ID", raising=False)


# ---------------------------------------------------------------------
# is_service_principal_mode
# ---------------------------------------------------------------------


def test_mode_default_is_delegated() -> None:
    assert is_service_principal_mode() is False


@pytest.mark.parametrize(
    "mode_value",
    [
        "service-principal",
        "service_principal",
        "client-credentials",
        "client_credentials",
        "app-only",
        "app_only",
        "SERVICE-PRINCIPAL",  # case-insensitive
    ],
)
def test_mode_explicit_service_principal(monkeypatch: pytest.MonkeyPatch, mode_value: str) -> None:
    monkeypatch.setenv("OUTLOOK_AUTH_MODE", mode_value)
    assert is_service_principal_mode() is True


def test_mode_explicit_delegated_overrides_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OUTLOOK_AUTH_MODE", "delegated")
    monkeypatch.setenv("OUTLOOK_CLIENT_SECRET", "x")
    assert is_service_principal_mode() is False


def test_mode_auto_detected_via_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OUTLOOK_CLIENT_SECRET", "non-empty-secret")
    assert is_service_principal_mode() is True


def test_mode_empty_secret_is_not_sp_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OUTLOOK_CLIENT_SECRET", "   ")
    assert is_service_principal_mode() is False


# ---------------------------------------------------------------------
# acquire_app_only_token
# ---------------------------------------------------------------------


@respx.mock
def test_acquire_app_only_token_uses_default_scope() -> None:
    route = respx.post(f"{AUTHORITY_BASE}/tenant-x/oauth2/v2.0/token").respond(
        json={"access_token": "AT-app", "expires_in": 3600, "scope": ".default"},
    )
    cached = acquire_app_only_token(client_id="cid", client_secret="secret", tenant="tenant-x")
    assert cached.access_token == "AT-app"
    assert cached.refresh_token is None
    body = route.calls.last.request.read().decode()
    assert "grant_type=client_credentials" in body
    assert "https" in body  # scope is .default URL-encoded


# ---------------------------------------------------------------------
# get_app_only_token
# ---------------------------------------------------------------------


@respx.mock
def test_get_app_only_token_caches_within_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OUTLOOK_CLIENT_ID", "cid")
    monkeypatch.setenv("OUTLOOK_CLIENT_SECRET", "secret")
    monkeypatch.setenv("OUTLOOK_TENANT_ID", "tenant-cache")
    route = respx.post(f"{AUTHORITY_BASE}/tenant-cache/oauth2/v2.0/token").respond(
        json={"access_token": "AT-1", "expires_in": 3600, "scope": ""},
    )
    assert get_app_only_token() == "AT-1"
    # Second call should reuse the in-process cache, not re-issue.
    assert get_app_only_token() == "AT-1"
    assert route.call_count == 1


def test_get_app_only_token_missing_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OUTLOOK_CLIENT_ID", "cid")
    # OUTLOOK_CLIENT_SECRET + OUTLOOK_TENANT_ID missing.
    with pytest.raises(ServicePrincipalConfigError, match="OUTLOOK_CLIENT_SECRET"):
        get_app_only_token()


@respx.mock
def test_get_app_only_token_separate_tenants_cached_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OUTLOOK_CLIENT_ID", "cid")
    monkeypatch.setenv("OUTLOOK_CLIENT_SECRET", "secret")
    monkeypatch.setenv("OUTLOOK_TENANT_ID", "tenant-a")
    respx.post(f"{AUTHORITY_BASE}/tenant-a/oauth2/v2.0/token").respond(
        json={"access_token": "AT-A", "expires_in": 3600, "scope": ""},
    )
    assert get_app_only_token() == "AT-A"

    monkeypatch.setenv("OUTLOOK_TENANT_ID", "tenant-b")
    respx.post(f"{AUTHORITY_BASE}/tenant-b/oauth2/v2.0/token").respond(
        json={"access_token": "AT-B", "expires_in": 3600, "scope": ""},
    )
    assert get_app_only_token() == "AT-B"
