# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for ol_email_list_drafts.

Covers both modes:

- profile_only=True: pure registry read, no Graph call.
- profile_only=False: Graph round-trip + ownership flag overlay.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import respx

from outlook_mcp.auth import get_token
from outlook_mcp.auth.tokens import CachedToken
from outlook_mcp.draft_registry import DraftEntry, DraftRegistry
from outlook_mcp.tools.email_list_drafts import list_drafts

DRAFTS_URL = "https://graph.microsoft.com/v1.0/me/mailFolders/Drafts/messages"


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
        "outlook_mcp.tools.email_list_drafts.get_token",
        lambda profile="default": get_token(profile=profile, store=store),
    )


@pytest.fixture
def populated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Pre-seed the registry with two drafts and redirect the tool to it."""
    monkeypatch.setattr(
        "outlook_mcp.tools.email_list_drafts.DraftRegistry",
        lambda profile: DraftRegistry(profile=profile, base_dir=tmp_path),
    )
    reg = DraftRegistry(profile="default", base_dir=tmp_path)
    reg.add(
        DraftEntry(
            kind="email",
            graph_id="d1",
            web_url="https://outlook.office.com/m/d1",
            subject="First",
            created_at=1715000000.0,
        )
    )
    reg.add(
        DraftEntry(
            kind="email",
            graph_id="d2",
            web_url="https://outlook.office.com/m/d2",
            subject="Second",
            created_at=1715000010.0,
        )
    )
    return tmp_path


# ---------------------------------------------------------------------
# profile_only=True (default) — registry read, no Graph call
# ---------------------------------------------------------------------


def test_list_profile_only_returns_only_owned(populated_registry: Path) -> None:
    del populated_registry
    with respx.mock(base_url="https://graph.microsoft.com") as router:
        out = list_drafts(profile_only=True)
        # No Graph call should have been made.
        assert not router.calls
    assert {entry["id"] for entry in out} == {"d1", "d2"}
    # Ordered newest-first by created_at
    assert out[0]["id"] == "d2"
    assert out[1]["id"] == "d1"
    assert all(entry["created_by_this_profile"] for entry in out)


def test_list_profile_only_empty_when_no_drafts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "outlook_mcp.tools.email_list_drafts.DraftRegistry",
        lambda profile: DraftRegistry(profile=profile, base_dir=tmp_path),
    )
    assert list_drafts(profile_only=True) == []


def test_list_profile_only_respects_limit(populated_registry: Path) -> None:
    del populated_registry
    out = list_drafts(profile_only=True, limit=1)
    assert len(out) == 1
    # Newest first
    assert out[0]["id"] == "d2"


def test_list_negative_limit_raises(populated_registry: Path) -> None:
    del populated_registry
    with pytest.raises(ValueError, match="positive"):
        list_drafts(limit=0)


# ---------------------------------------------------------------------
# profile_only=False — Graph round-trip + ownership overlay
# ---------------------------------------------------------------------


@respx.mock
def test_list_all_overlays_ownership_flag(fresh_token: None, populated_registry: Path) -> None:
    """Three drafts on Graph: two we created (d1, d2), one hand-typed
    in Outlook (d-handtyped). The ownership flag must distinguish."""
    del fresh_token, populated_registry
    respx.get(DRAFTS_URL).respond(
        json={
            "value": [
                {
                    "id": "d-handtyped",
                    "subject": "Hand-written",
                    "lastModifiedDateTime": "2026-05-08T12:00:00Z",
                    "webLink": "https://outlook.office.com/m/d-handtyped",
                },
                {
                    "id": "d2",
                    "subject": "Second",
                    "lastModifiedDateTime": "2026-05-07T15:00:00Z",
                    "webLink": "https://outlook.office.com/m/d2",
                },
                {
                    "id": "d1",
                    "subject": "First",
                    "lastModifiedDateTime": "2026-05-06T10:00:00Z",
                    "webLink": "https://outlook.office.com/m/d1",
                },
            ]
        }
    )
    out = list_drafts(profile_only=False)
    assert len(out) == 3
    by_id = {entry["id"]: entry for entry in out}
    assert by_id["d-handtyped"]["created_by_this_profile"] is False
    assert by_id["d1"]["created_by_this_profile"] is True
    assert by_id["d2"]["created_by_this_profile"] is True


@respx.mock
def test_list_all_passes_orderby_and_top(fresh_token: None, populated_registry: Path) -> None:
    del fresh_token, populated_registry
    route = respx.get(DRAFTS_URL).respond(json={"value": []})
    list_drafts(profile_only=False, limit=42)
    request = route.calls.last.request
    assert "%24orderby=lastModifiedDateTime+desc" in str(request.url)
    assert "%24top=42" in str(request.url)


@respx.mock
def test_list_all_includes_user_agent(fresh_token: None, populated_registry: Path) -> None:
    del fresh_token, populated_registry
    route = respx.get(DRAFTS_URL).respond(json={"value": []})
    list_drafts(profile_only=False)
    headers = route.calls.last.request.headers
    assert headers["User-Agent"].startswith("mcp-server-outlook/")
    assert headers["Authorization"] == "Bearer AT"
