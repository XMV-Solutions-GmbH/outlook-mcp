# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Resolve "who is this token for" for the login tools.

One resolution order, shared by `ol_login_begin` and
`ol_login_status` so the two can never disagree:

1. the per-profile cache, **only** if its entry was derived from this
   exact access token;
2. the token's own `upn` / `unique_name` / `preferred_username` claim
   — free, offline, and unambiguous for work/school accounts;
3. a `/me?$select=userPrincipalName` round-trip, which is the only
   option for personal Microsoft accounts (their tokens are opaque).

If all three come up empty the answer is None, and the caller omits
the field. Reporting an identity the current token does not support
is the failure mode issue #83 was filed for, and it is worse than
reporting none: it silently points the agent at the wrong mailbox.
"""

from __future__ import annotations

from typing import cast

import httpx

from outlook_mcp.auth.identity import upn_from_access_token
from outlook_mcp.login_state import cache_upn, cached_upn, invalidate_upn
from outlook_mcp.tools._common import GRAPH_BASE, auth_headers


def fetch_upn_from_graph(token: str, http: httpx.Client | None = None) -> str | None:
    """One `/me?$select=userPrincipalName` round-trip.

    Returns None on any failure (network blip, 4xx, malformed JSON) —
    the caller's response is still useful without the UPN.
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


def resolve_upn(
    *,
    profile: str,
    token: str,
    http: httpx.Client | None = None,
) -> str | None:
    """Return the UPN `token` belongs to, or None if undeterminable.

    Populates the per-profile cache on a successful lookup, bound to
    `token`, and clears it when nothing could be derived — so a failed
    lookup never leaves an older user's name readable.
    """
    hit = cached_upn(profile, token=token)
    if hit is not None:
        return hit

    upn = upn_from_access_token(token)
    if upn is None:
        upn = fetch_upn_from_graph(token, http)

    if upn is None:
        invalidate_upn(profile)
        return None

    cache_upn(profile, upn, token=token)
    return upn
