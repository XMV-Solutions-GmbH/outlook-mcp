# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""ol_login_status — three-state active-probe of this profile's auth.

Three states the agent can act on directly:

- `signed_in`: a valid token exists for `profile` (in OS keyring or
  on disk), regardless of how it got there. Includes the case where
  the user logged in via the CLI (`mcp-server-outlook login --profile
  <name>`) hours or days ago. The status check actively probes the
  token store + refreshes if needed; it does NOT require an
  in-process LoginSession.
- `pending`: an in-flight Device Code session exists for this
  profile (started by `ol_login_begin`). The response includes
  `user_code`, `verification_url`, and `time_remaining_s` so the
  agent can re-display the prompt to the user.
- `none`: no token, no in-flight session. The agent should call
  `ol_login_begin`.

If a previous session terminated unsuccessfully (`failed`,
`expired`, or `cancelled`), the response is `none` plus a structured
`error` field carrying what happened. Successful sessions, by
contrast, report `signed_in` because the active probe finds the
freshly-written token; the registry entry is incidental at that
point.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import httpx
from mcp_microsoft_graph_auth import public_view

from outlook_mcp.auth import AuthRequiredError, get_token
from outlook_mcp.login_state import cache_upn, cached_upn, get_login_session_registry
from outlook_mcp.tools._common import GRAPH_BASE, auth_headers


def login_status(
    *,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> dict[str, Any]:
    """Return the current auth status for `profile`.

    Active probe semantics: tries to obtain a valid token from the
    configured TokenStore. If that succeeds (cache hit, possibly
    after a silent refresh), reports `signed_in`. Only falls through
    to the in-process `LoginSessionRegistry` lookup when the token
    probe says "no usable credentials".

    Returns a dict with `status` (always present) and a subset of
    `signed_in_user_upn`, `user_code`, `verification_url`,
    `verification_url_complete`, `time_remaining_s`, `expires_at`,
    `error` depending on the state.
    """
    # 1. Active probe: try to get a usable token.
    try:
        token = get_token(profile)
    except AuthRequiredError:
        token = None

    if token is not None:
        upn = cached_upn(profile)
        if upn is None:
            upn = _fetch_upn(token=token, http=http)
            if upn is not None:
                cache_upn(profile, upn)
        return {
            "status": "signed_in",
            "signed_in_user_upn": upn,
        }

    # 2. No token. Check the in-process LoginSessionRegistry.
    registry = get_login_session_registry()
    session = registry.get(profile)
    if session is None:
        return {"status": "none"}

    view = public_view(session, now=datetime.now(UTC))

    if session.status == "pending":
        return {
            "status": "pending",
            "session_id": view["session_id"],
            "user_code": view["user_code"],
            "verification_url": view["verification_url"],
            "verification_url_complete": view["verification_url_complete"],
            "expires_at": view["expires_at"],
            "time_remaining_s": view["time_remaining_s"],
        }

    # Terminal states: failed / expired / cancelled. (success is
    # impossible to land here because the active probe above would
    # have found the token first.) Surface as `none` for the agent's
    # decision logic ("call login_begin"), with the underlying error
    # for diagnostics.
    error: dict[str, Any] | None = None
    if session.status in ("failed", "expired", "cancelled"):
        if session.error is not None:
            error = dict(session.error)
        else:
            error = {"code": session.status, "message": _default_error_message(session.status)}
    return {
        "status": "none",
        "previous_session_status": session.status,
        "error": error,
    }


def _fetch_upn(*, token: str, http: httpx.Client | None) -> str | None:
    """Round-trip /me?$select=userPrincipalName to learn who the token belongs to.

    Returns None on any failure (network blip, 4xx, malformed JSON) —
    the status response is still useful without the UPN. Sub-second
    in the typical case; we do at most one of these per
    profile-state-transition because of `cache_upn`.
    """
    client = http if http is not None else httpx.Client(timeout=15.0)
    try:
        response = client.get(
            f"{GRAPH_BASE}/me",
            headers=auth_headers(token),
            params={"$select": "userPrincipalName"},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return None
        upn = payload.get("userPrincipalName")
        return cast("str | None", upn) if isinstance(upn, str) else None
    except (httpx.HTTPError, ValueError):
        return None
    finally:
        if http is None:
            client.close()


def _default_error_message(status: str) -> str:
    return {
        "failed": "the previous login attempt failed before completion",
        "expired": "the device code expired before sign-in completed",
        "cancelled": "the previous login attempt was cancelled (force=True or ol_login_cancel)",
    }.get(status, status)
