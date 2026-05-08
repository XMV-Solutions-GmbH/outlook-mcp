# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for ol_calendar_discard_event_draft.

Mirrors the email-discard tests: registry-defensive, 404-as-success,
500-propagates-and-keeps-registry, header invariants.
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
from outlook_mcp.tools.calendar_discard_event_draft import discard_event_draft
from outlook_mcp.tools.email_update_draft import DraftNotOwnedError

GRAPH_URL = "https://graph.microsoft.com/v1.0/me/events/ev-1"


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
        "outlook_mcp.tools.calendar_discard_event_draft.get_token",
        lambda profile="default": get_token(profile=profile, store=store),
    )


@pytest.fixture
def isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        "outlook_mcp.tools.calendar_discard_event_draft.DraftRegistry",
        lambda profile: DraftRegistry(profile=profile, base_dir=tmp_path),
    )
    DraftRegistry(profile="default", base_dir=tmp_path).add(
        DraftEntry(
            kind="event",
            graph_id="ev-1",
            web_url="https://outlook.office.com/calendar/ev-1",
            subject="Quick chat",
            created_at=1715000000.0,
        )
    )
    return tmp_path


def test_discard_unknown_event_raises_DraftNotOwnedError(
    fresh_token: None, isolated_registry: Path
) -> None:
    del fresh_token, isolated_registry
    with respx.mock(base_url="https://graph.microsoft.com") as router:
        with pytest.raises(DraftNotOwnedError, match="not created by profile"):
            discard_event_draft("not-ours")
        assert not router.calls


@respx.mock
def test_discard_owned_event_deletes_and_cleans_registry(
    fresh_token: None, isolated_registry: Path
) -> None:
    del fresh_token
    respx.delete(GRAPH_URL).respond(204)
    discard_event_draft("ev-1")
    assert DraftRegistry(profile="default", base_dir=isolated_registry).get("ev-1") is None


@respx.mock
def test_discard_event_404_treated_as_success(fresh_token: None, isolated_registry: Path) -> None:
    del fresh_token
    respx.delete(GRAPH_URL).respond(404)
    discard_event_draft("ev-1")
    assert DraftRegistry(profile="default", base_dir=isolated_registry).get("ev-1") is None


@respx.mock
def test_discard_event_500_propagates_and_keeps_registry(
    fresh_token: None, isolated_registry: Path
) -> None:
    del fresh_token
    respx.delete(GRAPH_URL).respond(500)
    with pytest.raises(httpx.HTTPStatusError):
        discard_event_draft("ev-1")
    assert DraftRegistry(profile="default", base_dir=isolated_registry).get("ev-1") is not None


@respx.mock
def test_discard_event_sends_user_agent(fresh_token: None, isolated_registry: Path) -> None:
    del fresh_token, isolated_registry
    route = respx.delete(GRAPH_URL).respond(204)
    discard_event_draft("ev-1")
    headers = route.calls.last.request.headers
    assert headers["User-Agent"].startswith("mcp-server-outlook/")


def test_discard_event_rejects_empty_id(fresh_token: None, isolated_registry: Path) -> None:
    del fresh_token, isolated_registry
    with pytest.raises(ValueError, match="non-empty"):
        discard_event_draft("")
