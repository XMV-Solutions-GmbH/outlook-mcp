# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for ol_email_list_unread."""

from __future__ import annotations

import time
from urllib.parse import parse_qs, urlparse

import pytest
import respx

from outlook_mcp.auth import get_token
from outlook_mcp.auth.tokens import CachedToken
from outlook_mcp.tools.email_list_unread import list_unread

INBOX_URL = "https://graph.microsoft.com/v1.0/me/mailFolders/Inbox/messages"


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
        "outlook_mcp.tools.email_list_unread.get_token",
        lambda profile="default": get_token(profile=profile, store=store),
    )


@respx.mock
def test_list_unread_happy_path(fresh_token: None) -> None:
    del fresh_token
    respx.get(INBOX_URL).respond(
        json={
            "value": [
                {
                    "id": "u1",
                    "subject": "Need reply",
                    "from": {"emailAddress": {"name": "Boss", "address": "boss@x.de"}},
                    "receivedDateTime": "2026-05-08T08:00:00Z",
                    "bodyPreview": "PTO?",
                    "webLink": "https://outlook.office.com/m/u1",
                    "hasAttachments": False,
                }
            ]
        }
    )
    out = list_unread()
    assert len(out) == 1
    assert out[0]["id"] == "u1"
    assert out[0]["from"] == {"name": "Boss", "address": "boss@x.de"}


@respx.mock
def test_list_unread_passes_filter_and_orderby(fresh_token: None) -> None:
    del fresh_token
    route = respx.get(INBOX_URL).respond(json={"value": []})
    list_unread()
    params = parse_qs(urlparse(str(route.calls.last.request.url)).query)
    assert params["$filter"] == ["isRead eq false"]
    assert params["$orderby"] == ["receivedDateTime desc"]
    assert params["$top"] == ["50"]


@respx.mock
def test_list_unread_custom_folder(fresh_token: None) -> None:
    del fresh_token
    route = respx.get("https://graph.microsoft.com/v1.0/me/mailFolders/Archive/messages").respond(
        json={"value": []}
    )
    list_unread(folder="Archive", limit=10)
    assert route.call_count == 1


def test_list_unread_empty_folder_raises(fresh_token: None) -> None:
    del fresh_token
    with pytest.raises(ValueError, match="non-empty folder"):
        list_unread(folder="")


def test_list_unread_negative_limit_raises(fresh_token: None) -> None:
    del fresh_token
    with pytest.raises(ValueError, match="positive"):
        list_unread(limit=-1)
