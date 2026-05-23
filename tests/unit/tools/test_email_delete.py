# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for ol_email_delete (#45).

Covers:

- Happy-path soft delete against /me and /users/{upn}.
- Permanent delete via POST /permanentDelete (the v1.0 endpoint).
- 404 idempotence — re-deleting an already-gone message is success.
- Non-404 errors propagate.
- Empty / whitespace-only message_id and mailbox rejected at the helper.
"""

from __future__ import annotations

import time

import httpx
import pytest
import respx

from outlook_mcp.auth import get_token
from outlook_mcp.auth.tokens import CachedToken
from outlook_mcp.tools.email_delete import delete_message

GRAPH = "https://graph.microsoft.com/v1.0"
SOFT_DEL_URL = f"{GRAPH}/me/messages/m1"
HARD_DEL_URL = f"{GRAPH}/me/messages/m1/permanentDelete"
SHARED_SOFT_URL = f"{GRAPH}/users/sekretariat@xmv.de/messages/m1"
SHARED_HARD_URL = f"{GRAPH}/users/sekretariat@xmv.de/messages/m1/permanentDelete"


class _MemStore:
    def __init__(self) -> None:
        self._d: dict[str, bytes] = {
            "default": CachedToken(
                access_token="AT",
                refresh_token="RT",
                expires_at=time.time() + 3600,
                scope="",
            )
            .to_json()
            .encode()
        }

    def get(self, profile: str) -> bytes | None:
        return self._d.get(profile)

    def set(self, profile: str, value: bytes) -> None:
        self._d[profile] = value

    def delete(self, profile: str) -> None:
        self._d.pop(profile, None)


@pytest.fixture
def fresh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _MemStore()
    monkeypatch.setattr(
        "outlook_mcp.tools.email_delete.get_token",
        lambda profile="default": get_token(profile=profile, store=store),
    )


# ── happy path: soft delete on /me ────────────────────────────────────────


@respx.mock
def test_soft_delete_returns_descriptor(fresh_token: None) -> None:
    del fresh_token
    respx.delete(SOFT_DEL_URL).respond(204)

    result = delete_message("m1")

    assert result == {"message_id": "m1", "mailbox": None, "permanent": False}


@respx.mock
def test_soft_delete_uses_delete_method_not_post(fresh_token: None) -> None:
    """The default code path is DELETE, not POST. Catches a copy-paste
    accident where someone wires the soft path through /permanentDelete."""
    del fresh_token
    route = respx.delete(SOFT_DEL_URL).respond(204)

    delete_message("m1")

    assert route.calls.call_count == 1


# ── happy path: permanent delete on /me ───────────────────────────────────


@respx.mock
def test_permanent_delete_posts_to_permanentDelete_endpoint(fresh_token: None) -> None:
    """permanent=True → POST /permanentDelete (the v1.0 endpoint that
    skips Deleted Items and goes straight to Recoverable Items)."""
    del fresh_token
    route = respx.post(HARD_DEL_URL).respond(204)

    result = delete_message("m1", permanent=True)

    assert route.calls.call_count == 1
    assert result["permanent"] is True


@respx.mock
def test_permanent_delete_does_not_call_soft_delete_endpoint(
    fresh_token: None,
) -> None:
    """Regression guard: permanent=True must NOT call DELETE first —
    that would move the message to Deleted Items as a side effect even
    if the second call succeeds (and worse if it fails)."""
    del fresh_token
    soft_route = respx.delete(SOFT_DEL_URL).respond(204)
    hard_route = respx.post(HARD_DEL_URL).respond(204)

    delete_message("m1", permanent=True)

    assert soft_route.calls.call_count == 0
    assert hard_route.calls.call_count == 1


# ── shared mailbox routing ────────────────────────────────────────────────


@respx.mock
def test_soft_delete_targets_shared_mailbox_when_mailbox_set(
    fresh_token: None,
) -> None:
    del fresh_token
    me_route = respx.delete(SOFT_DEL_URL).respond(204)
    shared_route = respx.delete(SHARED_SOFT_URL).respond(204)

    result = delete_message("m1", mailbox="sekretariat@xmv.de")

    assert me_route.calls.call_count == 0
    assert shared_route.calls.call_count == 1
    assert result["mailbox"] == "sekretariat@xmv.de"


@respx.mock
def test_permanent_delete_targets_shared_mailbox_when_mailbox_set(
    fresh_token: None,
) -> None:
    del fresh_token
    shared_route = respx.post(SHARED_HARD_URL).respond(204)

    result = delete_message(
        "m1",
        mailbox="sekretariat@xmv.de",
        permanent=True,
    )

    assert shared_route.calls.call_count == 1
    assert result == {
        "message_id": "m1",
        "mailbox": "sekretariat@xmv.de",
        "permanent": True,
    }


# ── idempotency: 404 treated as success ───────────────────────────────────


@respx.mock
def test_soft_delete_404_is_success(fresh_token: None) -> None:
    """Re-deleting a message already gone: agent's intent ('make it
    disappear') is already satisfied. Don't bubble 404 as an error."""
    del fresh_token
    respx.delete(SOFT_DEL_URL).respond(404, json={"error": {"code": "ItemNotFound"}})

    # Should NOT raise.
    result = delete_message("m1")

    assert result == {"message_id": "m1", "mailbox": None, "permanent": False}


@respx.mock
def test_permanent_delete_404_is_success(fresh_token: None) -> None:
    del fresh_token
    respx.post(HARD_DEL_URL).respond(404, json={"error": {"code": "ItemNotFound"}})

    result = delete_message("m1", permanent=True)

    assert result["permanent"] is True


# ── non-404 errors propagate ──────────────────────────────────────────────


@respx.mock
def test_soft_delete_403_raises(fresh_token: None) -> None:
    """403 = no FullAccess on the target mailbox. Propagate the HTTP
    error so the caller can show the user what permission they need."""
    del fresh_token
    locked_url = f"{GRAPH}/users/locked@xmv.de/messages/m1"
    respx.delete(locked_url).respond(
        403,
        json={"error": {"code": "AccessDenied"}},
    )

    with pytest.raises(httpx.HTTPStatusError):
        delete_message("m1", mailbox="locked@xmv.de")


@respx.mock
def test_permanent_delete_5xx_raises(fresh_token: None) -> None:
    del fresh_token
    respx.post(HARD_DEL_URL).respond(500)

    with pytest.raises(httpx.HTTPStatusError):
        delete_message("m1", permanent=True)


# ── input validation ──────────────────────────────────────────────────────


def test_empty_message_id_raises(fresh_token: None) -> None:
    del fresh_token
    with pytest.raises(ValueError, match="message_id"):
        delete_message("")


def test_whitespace_message_id_raises(fresh_token: None) -> None:
    del fresh_token
    with pytest.raises(ValueError, match="message_id"):
        delete_message("   ")


def test_whitespace_mailbox_raises(fresh_token: None) -> None:
    """Whitespace mailbox is operator error — fail before round-tripping
    to Graph (which would return a less-helpful URL-validation error)."""
    del fresh_token
    with pytest.raises(ValueError, match="non-empty UPN"):
        delete_message("m1", mailbox="   ")
