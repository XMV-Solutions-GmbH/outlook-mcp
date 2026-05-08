# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for ol_email_discard_draft.

Covers the registry-defensive (no-Graph-call when not owned), the
happy-path DELETE, the 404-as-success idempotence, and the registry
cleanup.
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
from outlook_mcp.tools.email_discard_draft import discard_draft
from outlook_mcp.tools.email_update_draft import DraftNotOwnedError

GRAPH_URL = "https://graph.microsoft.com/v1.0/me/messages/draft-1"


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
        "outlook_mcp.tools.email_discard_draft.get_token",
        lambda profile="default": get_token(profile=profile, store=store),
    )


@pytest.fixture
def isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        "outlook_mcp.tools.email_discard_draft.DraftRegistry",
        lambda profile: DraftRegistry(profile=profile, base_dir=tmp_path),
    )
    DraftRegistry(profile="default", base_dir=tmp_path).add(
        DraftEntry(
            kind="email",
            graph_id="draft-1",
            web_url="https://outlook.office.com/m/draft-1",
            subject="Original",
            created_at=1715000000.0,
        )
    )
    return tmp_path


# ---------------------------------------------------------------------
# Defensive — not-owned drafts refused, no Graph call
# ---------------------------------------------------------------------


def test_discard_unknown_draft_raises_DraftNotOwnedError(
    fresh_token: None, isolated_registry: Path
) -> None:
    del fresh_token, isolated_registry
    with respx.mock(base_url="https://graph.microsoft.com") as router:
        with pytest.raises(DraftNotOwnedError, match="not created by profile"):
            discard_draft("not-ours")
        assert not router.calls


# ---------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------


@respx.mock
def test_discard_owned_draft_deletes_and_cleans_registry(
    fresh_token: None, isolated_registry: Path
) -> None:
    del fresh_token
    respx.delete(GRAPH_URL).respond(204)
    discard_draft("draft-1")
    # Registry cleaned up
    assert DraftRegistry(profile="default", base_dir=isolated_registry).get("draft-1") is None


@respx.mock
def test_discard_404_treated_as_success(fresh_token: None, isolated_registry: Path) -> None:
    """If the draft was already deleted server-side (e.g. user
    discarded it manually in Outlook), Graph returns 404. The
    agent's intent ('make this draft go away') is already
    satisfied — clean up the registry and return success."""
    del fresh_token
    respx.delete(GRAPH_URL).respond(404, json={"error": {"code": "ItemNotFound"}})
    discard_draft("draft-1")
    assert DraftRegistry(profile="default", base_dir=isolated_registry).get("draft-1") is None


@respx.mock
def test_discard_500_propagates_and_keeps_registry(
    fresh_token: None, isolated_registry: Path
) -> None:
    """Server errors are NOT swallowed — the agent should know the
    draft might still exist. Registry stays intact so the agent can
    retry."""
    del fresh_token
    respx.delete(GRAPH_URL).respond(500)
    with pytest.raises(httpx.HTTPStatusError):
        discard_draft("draft-1")
    # Registry entry NOT removed (delete didn't actually succeed)
    entry = DraftRegistry(profile="default", base_dir=isolated_registry).get("draft-1")
    assert entry is not None


@respx.mock
def test_discard_sends_user_agent(fresh_token: None, isolated_registry: Path) -> None:
    del fresh_token, isolated_registry
    route = respx.delete(GRAPH_URL).respond(204)
    discard_draft("draft-1")
    headers = route.calls.last.request.headers
    assert headers["User-Agent"].startswith("mcp-server-outlook/")
    assert headers["Authorization"] == "Bearer AT"


# ---------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------


def test_discard_rejects_empty_id(fresh_token: None, isolated_registry: Path) -> None:
    del fresh_token, isolated_registry
    with pytest.raises(ValueError, match="non-empty"):
        discard_draft("")
