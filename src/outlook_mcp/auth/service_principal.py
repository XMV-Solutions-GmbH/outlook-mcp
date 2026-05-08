# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Service-principal / client-credentials auth path.

Thin shim over `mcp-microsoft-graph-auth`'s `service_principal`
module:

- `acquire_app_only_token` is re-exported from the lib unchanged.
- `SERVICE_PRINCIPAL_SCOPE` is re-exported.
- `is_service_principal_mode()` and `get_app_only_token()` keep
  their `OUTLOOK_*` env-var-reading semantics — these are Outlook-
  specific (env-var prefix is `OUTLOOK_AUTH_MODE`, etc.) and stay here.
- `ServicePrincipalConfigError` stays here for backwards
  compatibility — the lib uses `ValueError` from
  `AppOnlyTokenCache.get_or_acquire`, but existing outlook-mcp code
  catches `ServicePrincipalConfigError` so we keep it.
- `_app_token_cache` and `reset_cache` keep their behaviour via a
  module-level `AppOnlyTokenCache` instance.

**Audit trail caveat.** App-only tokens attribute every action in
Microsoft 365's audit log to the *application* principal, NOT a real
user. The compliance-friendly default is delegated user auth. Only
switch to service-principal when no human is in the loop.

**`Mail.Send` is intentionally never required, listed, or used.** The
never-auto-send rule applies in service-principal mode just as it
does in delegated mode — sending stays a human action in Outlook.
"""

from __future__ import annotations

import os

import httpx
from mcp_microsoft_graph_auth.service_principal import (
    SERVICE_PRINCIPAL_SCOPE as SERVICE_PRINCIPAL_SCOPE,
)
from mcp_microsoft_graph_auth.service_principal import (
    AppOnlyTokenCache as AppOnlyTokenCache,
)
from mcp_microsoft_graph_auth.service_principal import (
    acquire_app_only_token as acquire_app_only_token,
)
from mcp_microsoft_graph_auth.tokens import CachedToken

AUTH_MODE_ENV = "OUTLOOK_AUTH_MODE"
CLIENT_SECRET_ENV = "OUTLOOK_CLIENT_SECRET"
TENANT_ENV = "OUTLOOK_TENANT_ID"
CLIENT_ID_ENV = "OUTLOOK_CLIENT_ID"

_SERVICE_PRINCIPAL_ALIASES = frozenset(
    {
        "service-principal",
        "service_principal",
        "client-credentials",
        "client_credentials",
        "app-only",
        "app_only",
    }
)
_DELEGATED_ALIASES = frozenset(
    {
        "delegated",
        "user",
        "device-code",
        "device_code",
    }
)

__all__ = [
    "SERVICE_PRINCIPAL_SCOPE",
    "AppOnlyTokenCache",
    "ServicePrincipalConfigError",
    "acquire_app_only_token",
    "get_app_only_token",
    "is_service_principal_mode",
    "reset_cache",
]


class ServicePrincipalConfigError(RuntimeError):
    """Service-principal mode is missing required configuration.

    Raised when `OUTLOOK_CLIENT_ID`, `OUTLOOK_CLIENT_SECRET`, or
    `OUTLOOK_TENANT_ID` is empty in service-principal mode.
    """


# Module-level cache instance (replaces the old `_app_token_cache` dict
# and `_app_token_lock` pair). Kept as a module-global so `reset_cache()`
# and `get_app_only_token()` continue to share the same cache across
# imports — same behaviour as before, internals different.
_cache = AppOnlyTokenCache()
# Back-compat alias — some tests poke at `_app_token_cache` directly.
_app_token_cache = _cache._cache


def is_service_principal_mode() -> bool:
    """True iff the environment selects service-principal auth.

    Resolution order:

    1. `OUTLOOK_AUTH_MODE` set to one of the service-principal aliases -> True
    2. `OUTLOOK_AUTH_MODE` set to one of the delegated aliases -> False
       (explicit delegated request beats secret presence)
    3. `OUTLOOK_CLIENT_SECRET` set and non-empty -> True (auto-detect)
    4. Otherwise -> False
    """
    mode = os.environ.get(AUTH_MODE_ENV, "").strip().lower()
    if mode in _SERVICE_PRINCIPAL_ALIASES:
        return True
    if mode in _DELEGATED_ALIASES:
        return False
    return bool(os.environ.get(CLIENT_SECRET_ENV, "").strip())


def get_app_only_token(
    *,
    http: httpx.Client | None = None,
) -> str:
    """Return a valid app-only access token, using the in-process cache.

    Raises `ServicePrincipalConfigError` if any required env var is
    missing or empty.
    """
    client_id = os.environ.get(CLIENT_ID_ENV, "").strip()
    client_secret = os.environ.get(CLIENT_SECRET_ENV, "").strip()
    tenant = os.environ.get(TENANT_ENV, "").strip()
    missing = [
        name
        for name, value in (
            (CLIENT_ID_ENV, client_id),
            (CLIENT_SECRET_ENV, client_secret),
            (TENANT_ENV, tenant),
        )
        if not value
    ]
    if missing:
        raise ServicePrincipalConfigError(
            "Service-principal mode requires "
            + ", ".join(missing)
            + " to be set in the environment.",
        )

    return _cache.get_or_acquire(
        client_id=client_id,
        client_secret=client_secret,
        tenant=tenant,
        http=http,
    )


def reset_cache() -> None:
    """Drop the in-process app-only token cache. Test-only escape hatch."""
    _cache.reset()


# Suppress unused-import warning — CachedToken is re-exported for
# backwards compat with code that does
# `from outlook_mcp.auth.service_principal import CachedToken`.
_ = CachedToken
