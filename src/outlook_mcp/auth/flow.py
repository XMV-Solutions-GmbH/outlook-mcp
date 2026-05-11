# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""OAuth 2.0 Device Code Flow + refresh-token client against Microsoft Identity.

Thin shim over `mcp-microsoft-graph-auth`'s `device_code` module
that supplies Outlook-specific defaults: the bundled multi-tenant
Entra app's client_id, the Outlook-flavoured Mail/Calendar Graph
scopes, and the multi-tenant `organizations` authority.

Each function delegates to the shared library after applying the
defaults. Existing imports (`outlook_mcp.auth.flow.poll_for_token`,
`resolve_scopes`, etc.) keep working without source-level changes.

Default scopes are deliberately read-only and DO NOT include
`Mail.Send`. The compliance line of this server is "drafts only,
sends are human-only" — the consent prompt should never read
"this app can send mail as you" unless the operator opts in via
`OUTLOOK_ALLOW_SEND`. See docs/app-concept.md for the full rationale.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable

import httpx
from mcp_microsoft_graph_auth.device_code import (
    AUTHORITY_BASE,
    AuthorizationDeniedError,
    DeviceCodeChallenge,
    DeviceCodeError,
    DeviceCodeExpiredError,
    RefreshTokenInvalidError,
)
from mcp_microsoft_graph_auth.device_code import (
    poll_for_token as _lib_poll_for_token,
)
from mcp_microsoft_graph_auth.device_code import (
    refresh_access_token as _lib_refresh_access_token,
)
from mcp_microsoft_graph_auth.device_code import (
    request_device_code as _lib_request_device_code,
)
from mcp_microsoft_graph_auth.tokens import CachedToken

# ---------------------------------------------------------------------
# Outlook-specific defaults — see docs/app-concept.md § Authentication.
# ---------------------------------------------------------------------

# XMV-published multi-tenant Entra app registration for mcp-server-outlook.
# Public client, Device Code flow enabled. As of v0.3 the registered
# permission list is: Mail.Read, Mail.ReadWrite, Mail.Send, Calendars.Read,
# Calendars.ReadWrite, User.Read, offline_access. **Mail.Send is in the
# registered permission list but is NOT in the default OAuth scope
# request** — see `resolve_scopes()` below for the lazy-request semantic.
# Override via OUTLOOK_CLIENT_ID for tenants with strict app-allowlisting.
DEFAULT_CLIENT_ID = "5df367d9-4c9b-44fd-9f84-0b4fb1f1268a"
DEFAULT_AUTHORITY_TENANT = "organizations"

# Env var that opts the running MCP server into requesting Mail.Send at
# OAuth time (and registering ol_email_send_draft as an MCP tool). When
# unset / falsy, the consent screen does NOT include "this app can send
# mail as you" — the default install is drafts-only. See
# docs/spikes/2026-05-08-v02-drafts-spikes.md § 1 (revised) for the design
# discussion.
ALLOW_SEND_ENV = "OUTLOOK_ALLOW_SEND"
ALLOW_DRAFTS_ENV = "OUTLOOK_ALLOW_DRAFTS"

# `OUTLOOK_ALLOW_DRAFTS` and `OUTLOOK_ALLOW_SEND` MUST be set to
# exactly "true" or "false" (case-insensitive, trimmed). Earlier
# versions accepted any of {"1","true","yes","on"} as truthy and
# silently treated unset as false; v0.4 enforces an explicit decision
# because "drafts not enabled because nobody flipped the switch" is
# indistinguishable, from the operator's perspective, from "drafts
# not enabled because I decided against it." See issue #37 for the
# user-side rationale.
_STRICT_TRUE = "true"
_STRICT_FALSE = "false"


class OutlookConsentNotConfiguredError(RuntimeError):
    """Raised at server-build / CLI-login time when one of the
    operator-consent env vars is unset or has a non-`true`/`false`
    value.

    The exception message is the user-facing onboarding hint —
    callers re-raise without wrapping so the operator sees it
    verbatim on stderr.
    """


def _strict_bool_env(name: str) -> bool:
    """Read `name` from the environment and parse strictly.

    Returns `True` for "true", `False` for "false" (case-insensitive,
    leading/trailing whitespace ignored). Raises
    `OutlookConsentNotConfiguredError` with the documented onboarding-help
    message for anything else, including unset / empty.
    """
    raw = os.environ.get(name)
    if raw is not None:
        normalised = raw.strip().lower()
        if normalised == _STRICT_TRUE:
            return True
        if normalised == _STRICT_FALSE:
            return False
    raise OutlookConsentNotConfiguredError(_consent_help_text(name, raw))


def _consent_help_text(name: str, raw: str | None) -> str:
    """Format the onboarding-help message for an unset / invalid
    consent env var. Identical layout for the two env vars so the
    operator gets predictable guidance independent of which one
    tripped."""
    got = "(not set)" if raw is None else f"{raw!r}"
    if name == ALLOW_DRAFTS_ENV:
        return (
            f"ERROR: mcp-server-outlook requires an explicit "
            f"{ALLOW_DRAFTS_ENV} decision (got {got}).\n\n"
            f"This server can create email drafts on the signed-in user's "
            f"behalf (opt-in) or operate in read-only mode. There is no "
            f"implicit default — the operator must consciously decide.\n\n"
            f"Set in your MCP client config (.mcp.json env section):\n\n"
            f'  "{ALLOW_DRAFTS_ENV}": "true"    — enable draft creation\n'
            f'  "{ALLOW_DRAFTS_ENV}": "false"   — read-only (no draft tools)\n\n'
            f"If you set {ALLOW_DRAFTS_ENV}=true, you must additionally "
            f"decide:\n\n"
            f'  "{ALLOW_SEND_ENV}": "true"      — additionally enable send tool\n'
            f'  "{ALLOW_SEND_ENV}": "false"     — drafts only, no send tool\n\n'
            f"See README §Authentication for the design rationale."
        )
    # ALLOW_SEND_ENV
    return (
        f"ERROR: mcp-server-outlook requires an explicit "
        f"{ALLOW_SEND_ENV} decision when {ALLOW_DRAFTS_ENV}=true (got {got}).\n\n"
        f"Sending mail is a separate consent decision from drafting it. "
        f"There is no implicit default — the operator must consciously "
        f"decide.\n\n"
        f"Set in your MCP client config (.mcp.json env section), next to "
        f'"{ALLOW_DRAFTS_ENV}": "true":\n\n'
        f'  "{ALLOW_SEND_ENV}": "true"      — register ol_email_send_draft\n'
        f'  "{ALLOW_SEND_ENV}": "false"     — drafts only, no send tool\n\n'
        f"See README §Authentication for the design rationale."
    )


def validate_consent_config() -> tuple[bool, bool]:
    """Validate the consent env vars at startup.

    Returns `(drafts_enabled, send_enabled)`. Raises
    `OutlookConsentNotConfiguredError` with a clear, actionable error
    message if either is unset or has a non-`true`/`false` value.

    Rules:

    - `OUTLOOK_ALLOW_DRAFTS` MUST be set to exactly `true` or `false`.
    - If `OUTLOOK_ALLOW_DRAFTS=true`, `OUTLOOK_ALLOW_SEND` MUST also
      be set to exactly `true` or `false`.
    - If `OUTLOOK_ALLOW_DRAFTS=false`, `OUTLOOK_ALLOW_SEND` is not
      checked — it would be dead config anyway (no drafts → nothing
      to send).
    """
    drafts = _strict_bool_env(ALLOW_DRAFTS_ENV)
    if drafts:
        send = _strict_bool_env(ALLOW_SEND_ENV)
    else:
        send = False
    return drafts, send


# Legacy truthy-set kept as documentation for callers reading old
# CHANGELOGs. Not used by the v0.4 strict parser.
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})

_BASE_SCOPES: tuple[str, ...] = (
    # Read inbox + calendar (v0.1 minimum)
    "Mail.Read",
    "Calendars.Read",
    # Draft creation / update / discard for v0.2 — gated at the tool
    # surface by OUTLOOK_ALLOW_DRAFTS=true. Mail.ReadWrite covers
    # POST/PATCH/DELETE on /me/messages; Calendars.ReadWrite covers
    # the same on /me/events.
    "Mail.ReadWrite",
    "Calendars.ReadWrite",
    "User.Read",
    "offline_access",
)


def send_enabled() -> bool:
    """True iff `OUTLOOK_ALLOW_SEND` is set to `"true"` AND
    `OUTLOOK_ALLOW_DRAFTS=true`.

    Strict parsing — raises `OutlookConsentNotConfiguredError` if either
    env var is unset or has a non-`true`/`false` value. Sends are a
    separate decision from drafting; the OAuth scope request omits
    `Mail.Send` and the MCP server does not register
    `ol_email_send_draft` unless this returns True.
    """
    _, send = validate_consent_config()
    return send


def resolve_scopes() -> tuple[str, ...]:
    """Return the OAuth scopes to request at this moment.

    Always includes `_BASE_SCOPES`. Appends `Mail.Send` only when
    `validate_consent_config()` returns `(True, True)` — i.e. the
    operator has explicitly opted into both drafts AND send.
    Resolved at call time, not at module load, so test-time
    `monkeypatch.setenv` flips behaviour without re-importing.

    Raises `OutlookConsentNotConfiguredError` if the consent env vars
    are not configured strictly.
    """
    _, send = validate_consent_config()
    if send:
        return (*_BASE_SCOPES, "Mail.Send")
    return _BASE_SCOPES


# Backwards-compat alias so callers who still import DEFAULT_SCOPES at
# module load continue to work — they get the un-flagged default. Tests
# that need to assert on the env-var-aware shape should call
# `resolve_scopes()` directly.
DEFAULT_SCOPES = _BASE_SCOPES

DEVICE_CODE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"

__all__ = [
    "ALLOW_DRAFTS_ENV",
    "ALLOW_SEND_ENV",
    "AUTHORITY_BASE",
    "DEFAULT_AUTHORITY_TENANT",
    "DEFAULT_CLIENT_ID",
    "DEFAULT_SCOPES",
    "DEVICE_CODE_GRANT_TYPE",
    "AuthorizationDeniedError",
    "CachedToken",
    "DeviceCodeChallenge",
    "DeviceCodeError",
    "DeviceCodeExpiredError",
    "OutlookConsentNotConfiguredError",
    "RefreshTokenInvalidError",
    "poll_for_token",
    "refresh_access_token",
    "request_device_code",
    "resolve_scopes",
    "send_enabled",
    "validate_consent_config",
]


def request_device_code(
    *,
    client_id: str = DEFAULT_CLIENT_ID,
    tenant: str = DEFAULT_AUTHORITY_TENANT,
    scopes: tuple[str, ...] | None = None,
    http: httpx.Client | None = None,
) -> tuple[str, DeviceCodeChallenge]:
    """Initiate the Device Code flow with Outlook-flavoured defaults.

    `scopes=None` (the default) calls `resolve_scopes()` so the env-var-
    aware Mail.Send-when-enabled behaviour kicks in. Pass an explicit
    tuple to override.
    """
    return _lib_request_device_code(
        client_id=client_id,
        tenant=tenant,
        scopes=scopes if scopes is not None else resolve_scopes(),
        http=http,
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
    """Poll `/token` until the user completes (or denies) sign-in."""
    return _lib_poll_for_token(
        device_code=device_code,
        client_id=client_id,
        tenant=tenant,
        interval=interval,
        http=http,
        sleep=sleep,
        now=now,
    )


def refresh_access_token(
    *,
    refresh_token: str,
    client_id: str = DEFAULT_CLIENT_ID,
    tenant: str = DEFAULT_AUTHORITY_TENANT,
    scopes: tuple[str, ...] | None = None,
    http: httpx.Client | None = None,
) -> CachedToken:
    """Exchange a refresh token for a new access (and refresh) token.

    Like `request_device_code`, `scopes=None` (the default) calls
    `resolve_scopes()` so the env-var-aware behaviour kicks in.
    """
    return _lib_refresh_access_token(
        refresh_token=refresh_token,
        client_id=client_id,
        tenant=tenant,
        scopes=scopes if scopes is not None else resolve_scopes(),
        http=http,
    )
