# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Process-singleton state for the MCP-tool login flow.

`ol_login_begin` and `ol_login_status` share a single
`LoginSessionRegistry` instance per running MCP server process. The
asyncio polling task `ol_login_begin` spawns writes its session into
this registry; `ol_login_status` reads from it.

A second process-level dict caches the signed-in UPN per profile to
avoid hitting `/me` on every `ol_login_status` call once we've already
identified the user. Each entry is **bound to the access token it was
derived from** (by fingerprint): the moment the profile is serving a
different token — a re-login as another user, a refresh, a token the
CLI wrote from another process — the cache misses and the identity is
re-derived. Keying on the profile alone is what caused issue #83: the
MCP server process outlives `mcp-server-outlook logout`, so a
profile-keyed entry written at the first sign-in was reported forever,
naming an account the current token did not belong to.

Pending sessions and the UPN cache live in memory only — they are NOT
persisted to disk. Restarting the MCP server mid-flow loses any
pending session (the agent would need to call `ol_login_begin` again);
losing the UPN cache just costs one extra `/me` call on the next
status check, which is fine.
"""

from __future__ import annotations

import threading

from mcp_microsoft_graph_auth import LoginSessionRegistry

from outlook_mcp.auth.identity import token_fingerprint

# Process-wide singleton. Created at import time; cheap (no I/O).
_registry: LoginSessionRegistry = LoginSessionRegistry()

# Process-wide UPN cache: profile -> (access-token fingerprint, UPN).
# The fingerprint half is what makes a stale entry impossible to read
# back: a lookup with a different token simply misses.
_upn_cache: dict[str, tuple[str, str]] = {}
_upn_lock = threading.Lock()


def get_login_session_registry() -> LoginSessionRegistry:
    """Return the singleton `LoginSessionRegistry` for this process."""
    return _registry


def cached_upn(profile: str, *, token: str) -> str | None:
    """Return the cached UPN for `profile` **iff** it was derived from
    `token`; None otherwise.

    `token` is required, not optional: a caller that cannot name the
    token it is about to use has no business reading a cached identity
    (issue #83).
    """
    fingerprint = token_fingerprint(token)
    with _upn_lock:
        entry = _upn_cache.get(profile)
    if entry is None or entry[0] != fingerprint:
        return None
    return entry[1]


def cache_upn(profile: str, upn: str, *, token: str) -> None:
    """Cache `upn` for `profile`, bound to `token`.

    Replaces any previous entry for the profile, so a re-login
    overwrites rather than accumulates.
    """
    fingerprint = token_fingerprint(token)
    with _upn_lock:
        _upn_cache[profile] = (fingerprint, upn)


def invalidate_upn(profile: str) -> None:
    """Drop the cached UPN for `profile`. Called on logout, and before
    a fresh sign-in writes a new identity, so an interrupted login can
    never leave the previous user's name behind."""
    with _upn_lock:
        _upn_cache.pop(profile, None)


def reset_for_tests() -> None:
    """Clear all in-process state. Test-only escape hatch."""
    _registry.clear()
    with _upn_lock:
        _upn_cache.clear()
