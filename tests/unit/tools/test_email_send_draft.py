# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for ol_email_send_draft.

Pins the load-bearing properties:

- DraftRegistry-defensive: only profile-owned drafts can be sent;
  unowned ids fail BEFORE any Graph call.
- 202 / 204 are both treated as success.
- The registry entry is removed on success (the draft is no longer
  in the Drafts folder).
- The User-Agent + Authorization headers are present on every request.
- 403 (no Mail.Send consent) is propagated unchanged so the agent /
  MCP client can surface a clear "re-login with OUTLOOK_ALLOW_SEND"
  hint.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest
import respx

from outlook_mcp.auth import get_token
from outlook_mcp.auth.tokens import CachedToken
from outlook_mcp.draft_registry import DraftEntry, DraftRegistry
from outlook_mcp.tools.email_send_draft import send_draft
from outlook_mcp.tools.email_update_draft import DraftNotOwnedError

GRAPH_URL = "https://graph.microsoft.com/v1.0/me/messages/draft-1/send"


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
        "outlook_mcp.tools.email_send_draft.get_token",
        lambda profile="default": get_token(profile=profile, store=store),
    )


@pytest.fixture
def isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        "outlook_mcp.tools.email_send_draft.DraftRegistry",
        lambda profile: DraftRegistry(profile=profile, base_dir=tmp_path),
    )
    DraftRegistry(profile="default", base_dir=tmp_path).add(
        DraftEntry(
            kind="email",
            graph_id="draft-1",
            web_url="https://outlook.office.com/m/draft-1",
            subject="Reply to Anna",
            created_at=1715000000.0,
        )
    )
    return tmp_path


# ---------------------------------------------------------------------
# Defensive — not-owned drafts refused, no Graph call
# ---------------------------------------------------------------------


def test_send_unknown_draft_raises_DraftNotOwnedError(
    fresh_token: None, isolated_registry: Path
) -> None:
    """The most important property: hand-typed drafts in Outlook
    NEVER appear in the registry. send_draft refuses to send them.
    No Graph call is leaked when the id isn't ours."""
    del fresh_token, isolated_registry
    with respx.mock(base_url="https://graph.microsoft.com") as router:
        with pytest.raises(DraftNotOwnedError, match="not created by profile"):
            send_draft("not-ours")
        assert not router.calls


# ---------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------


@respx.mock
def test_send_owned_draft_202_succeeds_and_cleans_registry(
    fresh_token: None, isolated_registry: Path
) -> None:
    del fresh_token
    respx.post(GRAPH_URL).respond(202)
    result = send_draft("draft-1")
    assert result["draft_id"] == "draft-1"
    # ISO 8601 timestamp present
    assert "T" in result["sent_at"]
    # Registry cleaned up
    assert DraftRegistry(profile="default", base_dir=isolated_registry).get("draft-1") is None


@respx.mock
def test_send_owned_draft_204_also_succeeds(fresh_token: None, isolated_registry: Path) -> None:
    """Some Graph paths return 204 instead of 202 for /send. Both
    are treated as success — verified by the registry being cleaned
    up afterwards."""
    del fresh_token
    respx.post(GRAPH_URL).respond(204)
    send_draft("draft-1")
    assert DraftRegistry(profile="default", base_dir=isolated_registry).get("draft-1") is None


# ---------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------


@respx.mock
def test_send_carries_authorization_and_user_agent(
    fresh_token: None, isolated_registry: Path
) -> None:
    del fresh_token, isolated_registry
    route = respx.post(GRAPH_URL).respond(202)
    send_draft("draft-1")
    headers = route.calls.last.request.headers
    assert headers["Authorization"] == "Bearer AT"
    assert headers["User-Agent"].startswith("mcp-server-outlook/")


# ---------------------------------------------------------------------
# Error propagation
# ---------------------------------------------------------------------


@respx.mock
def test_send_403_propagates_and_keeps_registry(fresh_token: None, isolated_registry: Path) -> None:
    """403 typically means Mail.Send consent missing. Propagate so
    the agent can surface the re-login hint. Registry stays intact
    so the user can retry after consent refresh."""
    del fresh_token
    respx.post(GRAPH_URL).respond(403, json={"error": {"code": "ErrorAccessDenied"}})
    with pytest.raises(httpx.HTTPStatusError):
        send_draft("draft-1")
    assert DraftRegistry(profile="default", base_dir=isolated_registry).get("draft-1") is not None


@respx.mock
def test_send_500_propagates_and_keeps_registry(fresh_token: None, isolated_registry: Path) -> None:
    del fresh_token
    respx.post(GRAPH_URL).respond(500)
    with pytest.raises(httpx.HTTPStatusError):
        send_draft("draft-1")
    assert DraftRegistry(profile="default", base_dir=isolated_registry).get("draft-1") is not None


# ---------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------


def test_send_rejects_empty_id(fresh_token: None, isolated_registry: Path) -> None:
    del fresh_token, isolated_registry
    with pytest.raises(ValueError, match="non-empty"):
        send_draft("")
