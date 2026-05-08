# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for ol_calendar_search."""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest
import respx

from outlook_mcp.auth import get_token
from outlook_mcp.auth.tokens import CachedToken
from outlook_mcp.tools.calendar_search import search

EVENTS_URL = "https://graph.microsoft.com/v1.0/me/events"


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
        "outlook_mcp.tools.calendar_search.get_token",
        lambda profile="default": get_token(profile=profile, store=store),
    )


def _event_payload(*, eid: str = "ev1", subject: str = "Standup") -> dict[str, Any]:
    return {
        "id": eid,
        "subject": subject,
        "organizer": {"emailAddress": {"name": "Boss", "address": "boss@x.de"}},
        "start": {"dateTime": "2026-05-09T09:00:00", "timeZone": "Europe/Berlin"},
        "end": {"dateTime": "2026-05-09T09:30:00", "timeZone": "Europe/Berlin"},
        "location": {"displayName": "Office"},
        "attendees": [
            {
                "emailAddress": {"name": "Me", "address": "me@x.de"},
                "status": {"response": "accepted"},
            }
        ],
        "webLink": "https://outlook.office.com/calendar/" + eid,
        "isAllDay": False,
        "isCancelled": False,
    }


@respx.mock
def test_search_happy_path(fresh_token: None) -> None:
    del fresh_token
    respx.get(EVENTS_URL).respond(json={"value": [_event_payload()]})
    hits = search("standup")
    assert len(hits) == 1
    assert hits[0]["id"] == "ev1"
    assert hits[0]["organizer"] == {"name": "Boss", "address": "boss@x.de"}
    assert hits[0]["start"] == {
        "date_time": "2026-05-09T09:00:00",
        "time_zone": "Europe/Berlin",
    }
    assert hits[0]["location"] == "Office"
    assert hits[0]["attendees"] == [
        {"name": "Me", "address": "me@x.de", "response_status": "accepted"}
    ]


@respx.mock
def test_search_with_calendar_arg_swaps_url(fresh_token: None) -> None:
    del fresh_token
    route = respx.get("https://graph.microsoft.com/v1.0/me/calendars/work-cal/events").respond(
        json={"value": []}
    )
    search("hi", calendar="work-cal")
    assert route.call_count == 1


def test_search_empty_query_raises(fresh_token: None) -> None:
    del fresh_token
    with pytest.raises(ValueError, match="non-empty"):
        search("")


def test_search_negative_limit_raises(fresh_token: None) -> None:
    del fresh_token
    with pytest.raises(ValueError, match="positive"):
        search("hi", limit=0)


@respx.mock
def test_search_propagates_http_error(fresh_token: None) -> None:
    del fresh_token
    respx.get(EVENTS_URL).respond(500)
    with pytest.raises(httpx.HTTPStatusError):
        search("x")
