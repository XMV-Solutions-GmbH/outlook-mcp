# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for ol_email_search."""

from __future__ import annotations

import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from outlook_mcp.auth import get_token
from outlook_mcp.auth.tokens import CachedToken
from outlook_mcp.tools.email_search import search

GRAPH_URL = "https://graph.microsoft.com/v1.0/me/messages"


class _MemStore:
    def __init__(self, token: CachedToken | None = None) -> None:
        self._d: dict[str, bytes] = {}
        if token is not None:
            self._d["default"] = token.to_json().encode()

    def get(self, profile: str) -> bytes | None:
        return self._d.get(profile)

    def set(self, profile: str, value: bytes) -> None:
        self._d[profile] = value

    def delete(self, profile: str) -> None:
        self._d.pop(profile, None)


@pytest.fixture
def fresh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch get_token to return a deterministic bearer without hitting Identity."""
    fresh = CachedToken(
        access_token="AT", refresh_token="RT", expires_at=time.time() + 3600, scope=""
    )
    store = _MemStore(token=fresh)
    monkeypatch.setattr(
        "outlook_mcp.tools.email_search.get_token",
        lambda profile="default": get_token(profile=profile, store=store),
    )


@respx.mock
def test_search_happy_path(fresh_token: None) -> None:
    del fresh_token  # fixture side-effect only
    respx.get(GRAPH_URL).respond(
        json={
            "value": [
                {
                    "id": "msg-1",
                    "subject": "Hello",
                    "from": {"emailAddress": {"name": "Anna", "address": "anna@x.de"}},
                    "receivedDateTime": "2026-05-01T12:00:00Z",
                    "bodyPreview": "Snippet",
                    "webLink": "https://outlook.office.com/m/msg-1",
                    "hasAttachments": False,
                }
            ]
        },
    )
    hits = search("availability")
    assert hits == [
        {
            "id": "msg-1",
            "subject": "Hello",
            "from": {"name": "Anna", "address": "anna@x.de"},
            "received_at": "2026-05-01T12:00:00Z",
            "snippet": "Snippet",
            "web_url": "https://outlook.office.com/m/msg-1",
            "has_attachments": False,
        }
    ]


@respx.mock
def test_search_passes_search_param(fresh_token: None) -> None:
    del fresh_token
    route = respx.get(GRAPH_URL).respond(json={"value": []})
    search("Q1 review")
    request = route.calls.last.request
    params = parse_qs(urlparse(str(request.url)).query)
    assert params["$search"] == ['"Q1 review"']
    assert params["$top"] == ["25"]


@respx.mock
def test_search_with_filter_combines_args(fresh_token: None) -> None:
    del fresh_token
    route = respx.get(GRAPH_URL).respond(json={"value": []})
    search(
        "anna",
        from_address="anna@x.de",
        modified_after="2026-04-01T00:00:00Z",
        has_attachment=True,
    )
    params = parse_qs(urlparse(str(route.calls.last.request.url)).query)
    f = params["$filter"][0]
    assert "from/emailAddress/address eq 'anna@x.de'" in f
    assert "receivedDateTime ge 2026-04-01T00:00:00Z" in f
    assert "hasAttachments eq true" in f


@respx.mock
def test_search_folder_swaps_url(fresh_token: None) -> None:
    del fresh_token
    route = respx.get("https://graph.microsoft.com/v1.0/me/mailFolders/Inbox/messages").respond(
        json={"value": []}
    )
    search("hi", folder="Inbox")
    assert route.call_count == 1


def test_search_empty_query_raises(fresh_token: None) -> None:
    del fresh_token
    with pytest.raises(ValueError, match="non-empty"):
        search("   ")


def test_search_negative_limit_raises(fresh_token: None) -> None:
    del fresh_token
    with pytest.raises(ValueError, match="positive"):
        search("hi", limit=0)


@respx.mock
def test_search_propagates_http_errors(fresh_token: None) -> None:
    del fresh_token
    respx.get(GRAPH_URL).respond(500)
    with pytest.raises(httpx.HTTPStatusError):
        search("hi")
