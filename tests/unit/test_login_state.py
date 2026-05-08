# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for outlook_mcp.login_state — the process-singleton holder.

Pins:

- The registry singleton is a single shared instance across calls.
- The UPN cache survives across profile reads + isolates per profile.
- `reset_for_tests` produces a clean slate (the test fixture's
  contract).
- Thread safety on the UPN cache (basic sanity — concurrent writes
  from a few threads do not lose entries).
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

from mcp_microsoft_graph_auth import LoginSession

from outlook_mcp.login_state import (
    cache_upn,
    cached_upn,
    get_login_session_registry,
    invalidate_upn,
    reset_for_tests,
)


def _session(profile: str = "default") -> LoginSession:
    now = datetime.now(UTC)
    return LoginSession(
        session_id="x",
        profile=profile,
        device_code="dc",
        user_code="UC",
        verification_url="https://x",
        verification_url_complete=None,
        expires_at=now + timedelta(minutes=10),
        interval_s=5,
        status="pending",
        signed_in_user_upn=None,
        error=None,
        task=None,
        started_at=now,
    )


# ---------------------------------------------------------------------
# Singleton identity
# ---------------------------------------------------------------------


def test_get_login_session_registry_returns_same_instance() -> None:
    """Crucial: ol_login_begin and ol_login_status share state.
    If this returned a fresh instance each time, status would
    never see a pending session."""
    a = get_login_session_registry()
    b = get_login_session_registry()
    assert a is b


# ---------------------------------------------------------------------
# UPN cache — read / write / invalidate / per-profile
# ---------------------------------------------------------------------


def test_cached_upn_returns_none_when_not_yet_cached() -> None:
    reset_for_tests()
    assert cached_upn("default") is None


def test_cache_then_read_roundtrip() -> None:
    reset_for_tests()
    cache_upn("default", "anna@xmv.de")
    assert cached_upn("default") == "anna@xmv.de"


def test_cache_overwrites_existing_entry() -> None:
    reset_for_tests()
    cache_upn("default", "old@xmv.de")
    cache_upn("default", "new@xmv.de")
    assert cached_upn("default") == "new@xmv.de"


def test_cache_isolates_per_profile() -> None:
    reset_for_tests()
    cache_upn("acme", "alice@acme.com")
    cache_upn("globex", "bob@globex.com")
    assert cached_upn("acme") == "alice@acme.com"
    assert cached_upn("globex") == "bob@globex.com"
    # Unrelated profile stays None
    assert cached_upn("nope") is None


def test_invalidate_drops_entry() -> None:
    reset_for_tests()
    cache_upn("default", "anna@xmv.de")
    invalidate_upn("default")
    assert cached_upn("default") is None


def test_invalidate_unknown_profile_is_noop() -> None:
    reset_for_tests()
    # Must not raise.
    invalidate_upn("never-cached")


# ---------------------------------------------------------------------
# reset_for_tests
# ---------------------------------------------------------------------


def test_reset_clears_registry_and_upn_cache() -> None:
    """The fixture's contract: every test starts clean."""
    cache_upn("default", "x@x.de")
    get_login_session_registry().put(_session("default"))

    reset_for_tests()

    assert cached_upn("default") is None
    assert get_login_session_registry().get("default") is None


def test_reset_preserves_singleton_identity() -> None:
    """Resetting must NOT swap the registry instance — anyone holding
    a reference (e.g. a long-lived asyncio task in a real server)
    would otherwise lose their handle to the active state."""
    before = get_login_session_registry()
    reset_for_tests()
    after = get_login_session_registry()
    assert before is after


# ---------------------------------------------------------------------
# Thread safety — basic sanity
# ---------------------------------------------------------------------


def test_concurrent_upn_writes_are_safe() -> None:
    """Spawn several threads writing distinct profiles to the UPN
    cache; verify all entries land. The lock guarantees no
    write-write race loses an update."""
    reset_for_tests()
    profiles = [f"p{i}" for i in range(50)]
    threads = [threading.Thread(target=cache_upn, args=(p, f"{p}@x.de")) for p in profiles]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for p in profiles:
        assert cached_upn(p) == f"{p}@x.de", f"lost write for {p}"


def test_concurrent_reads_during_writes_do_not_crash() -> None:
    """Defensive sanity: a reader thread spinning on cached_upn while
    other threads write must not see torn state or raise."""
    reset_for_tests()
    cache_upn("p", "initial@x.de")
    stop = threading.Event()
    seen: list[str | None] = []

    def reader() -> None:
        while not stop.is_set():
            seen.append(cached_upn("p"))

    def writer() -> None:
        for i in range(200):
            cache_upn("p", f"v{i}@x.de")

    r = threading.Thread(target=reader)
    w = threading.Thread(target=writer)
    r.start()
    w.start()
    w.join()
    stop.set()
    r.join()

    # If we got here without a deadlock or exception, that's the
    # win. Check seen is non-empty to confirm the reader actually
    # ran.
    assert seen
