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
identified the user. The cache is invalidated on logout / token store
delete.

Pending sessions and the UPN cache live in memory only — they are NOT
persisted to disk. Restarting the MCP server mid-flow loses any
pending session (the agent would need to call `ol_login_begin` again);
losing the UPN cache just costs one extra `/me` call on the next
status check, which is fine.
"""

from __future__ import annotations

import threading

from mcp_microsoft_graph_auth import LoginSessionRegistry

# Process-wide singleton. Created at import time; cheap (no I/O).
_registry: LoginSessionRegistry = LoginSessionRegistry()

# Process-wide UPN cache, keyed by profile.
_upn_cache: dict[str, str] = {}
_upn_lock = threading.Lock()


def get_login_session_registry() -> LoginSessionRegistry:
    """Return the singleton `LoginSessionRegistry` for this process."""
    return _registry


def cached_upn(profile: str) -> str | None:
    """Return the cached UPN for `profile`, or None if not yet cached."""
    with _upn_lock:
        return _upn_cache.get(profile)


def cache_upn(profile: str, upn: str) -> None:
    """Cache the UPN for `profile`. Subsequent `cached_upn` calls return it."""
    with _upn_lock:
        _upn_cache[profile] = upn


def invalidate_upn(profile: str) -> None:
    """Drop the cached UPN for `profile`. Called on logout / cache delete."""
    with _upn_lock:
        _upn_cache.pop(profile, None)


def reset_for_tests() -> None:
    """Clear all in-process state. Test-only escape hatch."""
    _registry.clear()
    with _upn_lock:
        _upn_cache.clear()
