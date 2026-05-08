# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""OAuth 2.0 Device Code Flow + refresh-token client against Microsoft Identity.

Three HTTP-level primitives used by the higher-level `auth.__init__` API:

- `request_device_code()` — POST /devicecode, returns the secret
  device_code we poll with plus the human-facing challenge
  (`user_code`, verification URL, polling interval).
- `poll_for_token()` — POST /token (grant_type=device_code) in a loop
  until success, slow_down, expired_token, or access_denied.
- `refresh_access_token()` — POST /token (grant_type=refresh_token)
  for silent token renewal.

Synchronous on purpose: the flows are HTTP request/response with
modest latency; sync is debuggable, and the MCP tool layer wraps
calls in `asyncio.to_thread` if it needs them off the event loop.
Refresh in particular is sub-second.

Default scopes are deliberately read-only and DO NOT include
`Mail.Send`. The compliance line of this server is "drafts only,
sends are human-only" — the consent prompt should never read
"this app can send mail as you". See docs/app-concept.md for the
full rationale.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from outlook_mcp.auth.tokens import CachedToken

# ---------------------------------------------------------------------
# Defaults — see docs/app-concept.md § Authentication. The client_id
# is a placeholder until the XMV-published multi-tenant Entra app
# registration for outlook-mcp is provisioned (tracked as an open
# tech-spike question in app-concept.md). Users override via
# OUTLOOK_CLIENT_ID for BYO scenarios.
# ---------------------------------------------------------------------

AUTHORITY_BASE = "https://login.microsoftonline.com"
# Placeholder: replace with the real outlook-mcp Entra app registration
# GUID before the first PyPI release. Tracked in docs/app-concept.md
# § Open questions for the tech spike.
DEFAULT_CLIENT_ID = "00000000-0000-0000-0000-000000000000"
DEFAULT_AUTHORITY_TENANT = "organizations"
DEFAULT_SCOPES = (
    "Mail.Read",
    "Calendars.Read",
    "User.Read",
    "offline_access",
)
DEVICE_CODE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"

# Polling cap so a stuck `authorization_pending` response loop can't
# spin forever past the device code's actual expiry. Microsoft's
# device codes typically expire after 15 min; a 20 min cap leaves
# margin without becoming a bug-hiding fallback.
_MAX_POLL_DURATION_SECONDS = 1200


def _authority_url(tenant: str) -> str:
    return f"{AUTHORITY_BASE}/{tenant}"


# ---------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------


class DeviceCodeError(RuntimeError):
    """Base class for Device Code flow failures."""


class AuthorizationDeniedError(DeviceCodeError):
    """User refused the authorisation prompt."""


class DeviceCodeExpiredError(DeviceCodeError):
    """The device code expired before the user completed sign-in."""


class RefreshTokenInvalidError(RuntimeError):
    """The refresh token was rejected by Microsoft Identity.

    Caller's only recovery is full interactive re-login.
    """


# ---------------------------------------------------------------------
# Device-code challenge value type
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class DeviceCodeChallenge:
    """The user-facing half of the Device Code flow.

    Returned from `request_device_code()` so the caller can surface
    `user_code` + `verification_uri` to the human (via stderr, an MCP
    error response, or wherever the calling layer chooses).

    `verification_uri_complete` is RFC 8628 §3.3.1 — an optional URL
    with the user_code already embedded so the user only has to click
    and pick an account. Microsoft Identity v2.0 doesn't currently
    populate this for /devicecode, so it's almost always None. We
    capture it anyway in case Microsoft adds it later or for non-MS
    OAuth providers that do support it.
    """

    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    expires_at: float
    interval: int
    message: str


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _scope_string(scopes: tuple[str, ...] | list[str]) -> str:
    return " ".join(scopes)


def _build_cached_token(payload: dict[str, Any], requested_at: float) -> CachedToken:
    """Convert Microsoft's `/token` 200 response into our CachedToken."""
    expires_in = float(payload.get("expires_in", 0))
    return CachedToken(
        access_token=str(payload["access_token"]),
        refresh_token=str(payload["refresh_token"]) if "refresh_token" in payload else None,
        expires_at=requested_at + expires_in,
        scope=str(payload.get("scope", "")),
    )


# ---------------------------------------------------------------------
# Device Code flow
# ---------------------------------------------------------------------


def request_device_code(
    *,
    client_id: str = DEFAULT_CLIENT_ID,
    tenant: str = DEFAULT_AUTHORITY_TENANT,
    scopes: tuple[str, ...] = DEFAULT_SCOPES,
    http: httpx.Client | None = None,
) -> tuple[str, DeviceCodeChallenge]:
    """Initiate the Device Code flow.

    Returns `(device_code, challenge)`. `device_code` is the secret
    token used in subsequent `/token` polls; never surface it to the
    user. `challenge` carries the user-facing parts.
    """
    client = http if http is not None else httpx.Client(timeout=10.0)
    try:
        response = client.post(
            f"{_authority_url(tenant)}/oauth2/v2.0/devicecode",
            data={"client_id": client_id, "scope": _scope_string(scopes)},
        )
        response.raise_for_status()
        payload = response.json()
    finally:
        if http is None:
            client.close()

    expires_in = float(payload["expires_in"])
    uri_complete_raw = payload.get("verification_uri_complete")
    return (
        str(payload["device_code"]),
        DeviceCodeChallenge(
            user_code=str(payload["user_code"]),
            verification_uri=str(payload["verification_uri"]),
            verification_uri_complete=str(uri_complete_raw) if uri_complete_raw else None,
            expires_at=time.time() + expires_in,
            interval=int(payload.get("interval", 5)),
            message=str(payload.get("message", "")),
        ),
    )


def poll_for_token(
    *,
    device_code: str,
    client_id: str = DEFAULT_CLIENT_ID,
    tenant: str = DEFAULT_AUTHORITY_TENANT,
    interval: int = 5,
    http: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.time,
) -> CachedToken:
    """Poll `/token` until the user completes (or denies) sign-in.

    Honours Microsoft's `interval` and `slow_down` semantics. Caps
    total wait at `_MAX_POLL_DURATION_SECONDS` to bound runaway
    `authorization_pending` loops.

    `sleep` and `now` are injected for test determinism.

    Returns the issued `CachedToken` on success. Raises
    `AuthorizationDeniedError`, `DeviceCodeExpiredError`, or
    `httpx.HTTPStatusError` for unexpected failures.
    """
    client = http if http is not None else httpx.Client(timeout=10.0)
    started = now()
    current_interval = interval
    try:
        while True:
            if now() - started > _MAX_POLL_DURATION_SECONDS:
                raise DeviceCodeExpiredError(
                    f"Device-code polling exceeded {_MAX_POLL_DURATION_SECONDS}s "
                    "without resolution.",
                )
            sleep(current_interval)
            request_started = now()
            response = client.post(
                f"{_authority_url(tenant)}/oauth2/v2.0/token",
                data={
                    "grant_type": DEVICE_CODE_GRANT_TYPE,
                    "client_id": client_id,
                    "device_code": device_code,
                },
            )
            if response.status_code == 200:
                return _build_cached_token(response.json(), requested_at=request_started)

            payload = (
                response.json()
                if response.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            error = str(payload.get("error", ""))
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                current_interval += 5
                continue
            if error == "expired_token":
                raise DeviceCodeExpiredError(
                    "Device code expired before sign-in completed.",
                )
            if error == "access_denied":
                raise AuthorizationDeniedError(
                    "User refused the authorisation prompt.",
                )
            response.raise_for_status()
            # If raise_for_status didn't fire (unexpected 2xx other than 200), bail.
            raise DeviceCodeError(
                f"Unexpected /token response: status={response.status_code} payload={payload!r}",
            )
    finally:
        if http is None:
            client.close()


# ---------------------------------------------------------------------
# Refresh-token flow
# ---------------------------------------------------------------------


def refresh_access_token(
    *,
    refresh_token: str,
    client_id: str = DEFAULT_CLIENT_ID,
    tenant: str = DEFAULT_AUTHORITY_TENANT,
    scopes: tuple[str, ...] = DEFAULT_SCOPES,
    http: httpx.Client | None = None,
) -> CachedToken:
    """Exchange a refresh token for a new access (and possibly refresh) token.

    Microsoft typically rotates the refresh token; the returned
    `CachedToken` carries whichever refresh token is now current. If
    Microsoft does not include one (rare for delegated user flows
    with `offline_access`), the `refresh_token` field is `None` and
    the caller should treat the next expiry as a forced re-login.

    Raises `RefreshTokenInvalidError` if Microsoft rejects the refresh
    token (`invalid_grant`); the caller's only recovery is interactive
    re-login.
    """
    client = http if http is not None else httpx.Client(timeout=10.0)
    request_started = time.time()
    try:
        response = client.post(
            f"{_authority_url(tenant)}/oauth2/v2.0/token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": refresh_token,
                "scope": _scope_string(scopes),
            },
        )
        if response.status_code == 200:
            return _build_cached_token(response.json(), requested_at=request_started)
        if response.status_code == 400:
            payload = (
                response.json()
                if response.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            if str(payload.get("error", "")) == "invalid_grant":
                raise RefreshTokenInvalidError(
                    str(payload.get("error_description", "Refresh token rejected.")),
                )
        response.raise_for_status()
        raise RefreshTokenInvalidError(
            f"Unexpected /token response on refresh: status={response.status_code}",
        )
    finally:
        if http is None:
            client.close()
