# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Service-principal / client-credentials auth path.

Activated when `OUTLOOK_AUTH_MODE=service-principal` (or one of its
aliases), or auto-detected when `OUTLOOK_CLIENT_SECRET` is set in the
environment. Used for unattended automation pipelines: CI runners,
scheduled jobs, multi-tenant onboarding scripts.

**Audit trail caveat.** App-only tokens attribute every action in
Microsoft 365's audit log to the *application* principal, NOT a real
user. The compliance-friendly default is delegated user auth. Only
switch to service-principal when no human is in the loop.

The app registration that backs this flow MUST be granted
*Application* (not just Delegated) Microsoft Graph permissions —
typically `Mail.Read` and `Calendars.Read` — and admin consent must
be recorded by a tenant admin. Microsoft's `/v2.0/.default` scope
syntax tells AAD "issue a token covering exactly the application
permissions already consented".

**`Mail.Send` is intentionally never required, listed, or used.** The
never-auto-send rule applies in service-principal mode just as it
does in delegated mode — sending stays a human action in Outlook.

Tokens are cached in-process (per `(client_id, tenant)` key) until
expiry, then re-acquired. We deliberately do NOT persist app-only
tokens to disk: the client secret is already in env vars (typically
rotated), and a persisted app-only token adds attack surface
without much value (acquisition is sub-second once the secret is
correct).
"""

from __future__ import annotations

import os
import threading
import time

import httpx

from outlook_mcp.auth.flow import AUTHORITY_BASE
from outlook_mcp.auth.tokens import CachedToken

AUTH_MODE_ENV = "OUTLOOK_AUTH_MODE"
CLIENT_SECRET_ENV = "OUTLOOK_CLIENT_SECRET"
TENANT_ENV = "OUTLOOK_TENANT_ID"
CLIENT_ID_ENV = "OUTLOOK_CLIENT_ID"

SERVICE_PRINCIPAL_SCOPE = "https://graph.microsoft.com/.default"

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


class ServicePrincipalConfigError(RuntimeError):
    """Service-principal mode is missing required configuration.

    Raised when `OUTLOOK_CLIENT_ID`, `OUTLOOK_CLIENT_SECRET`, or
    `OUTLOOK_TENANT_ID` is empty in service-principal mode. The
    delegated default doesn't need these — the multi-tenant
    `organizations` authority works without a tenant override — so we
    can't share the env-var defaults.
    """


_app_token_cache: dict[tuple[str, str], CachedToken] = {}
_app_token_lock = threading.Lock()


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


def acquire_app_only_token(
    *,
    client_id: str,
    client_secret: str,
    tenant: str,
    http: httpx.Client | None = None,
) -> CachedToken:
    """Client-credentials grant. Returns CachedToken (no refresh_token).

    Per Microsoft's v2.0 `/.default` semantics, no `scope` choice is
    required: AAD issues a token covering whatever Application
    permissions the tenant admin has consented to.
    """
    client = http if http is not None else httpx.Client(timeout=10.0)
    request_started = time.time()
    try:
        response = client.post(
            f"{AUTHORITY_BASE}/{tenant}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": SERVICE_PRINCIPAL_SCOPE,
            },
        )
        response.raise_for_status()
        payload = response.json()
    finally:
        if http is None:
            client.close()
    return CachedToken(
        access_token=str(payload["access_token"]),
        refresh_token=None,
        expires_at=request_started + float(payload.get("expires_in", 0)),
        scope=str(payload.get("scope", "")),
    )


def get_app_only_token(
    *,
    http: httpx.Client | None = None,
) -> str:
    """Return a valid app-only access token, using the in-process cache.

    Raises `ServicePrincipalConfigError` if any required env var is
    missing or empty.

    Cache is keyed by `(client_id, tenant)` so multiple distinct apps
    in one process work; expiry is per-entry.
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

    key = (client_id, tenant)
    with _app_token_lock:
        cached = _app_token_cache.get(key)
        if cached is not None and not cached.is_expired():
            return cached.access_token
        # Acquire new — do this outside the lock to avoid blocking
        # other callers on a remote round-trip. Re-acquire the lock
        # to publish. If two callers race, both acquire (extra round
        # trip) but no correctness issue.
    new = acquire_app_only_token(
        client_id=client_id,
        client_secret=client_secret,
        tenant=tenant,
        http=http,
    )
    with _app_token_lock:
        _app_token_cache[key] = new
    return new.access_token


def reset_cache() -> None:
    """Drop the in-process app-only token cache. Test-only escape hatch."""
    with _app_token_lock:
        _app_token_cache.clear()
