# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for ol_calendar_list_events."""

from __future__ import annotations

import time
from urllib.parse import parse_qs, urlparse

import pytest
import respx

from outlook_mcp.auth import get_token
from outlook_mcp.auth.tokens import CachedToken
from outlook_mcp.tools.calendar_list_events import list_events

PRIMARY_VIEW = "https://graph.microsoft.com/v1.0/me/calendarView"


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
        "outlook_mcp.tools.calendar_list_events.get_token",
        lambda profile="default": get_token(profile=profile, store=store),
    )


@respx.mock
def test_list_events_uses_calendarView_for_primary(fresh_token: None) -> None:
    del fresh_token
    route = respx.get(PRIMARY_VIEW).respond(json={"value": []})
    list_events(from_date="2026-05-01T00:00:00Z", to_date="2026-05-08T00:00:00Z")
    params = parse_qs(urlparse(str(route.calls.last.request.url)).query)
    assert params["startDateTime"] == ["2026-05-01T00:00:00Z"]
    assert params["endDateTime"] == ["2026-05-08T00:00:00Z"]
    assert params["$orderby"] == ["start/dateTime asc"]


@respx.mock
def test_list_events_named_calendar_uses_other_url(fresh_token: None) -> None:
    del fresh_token
    route = respx.get("https://graph.microsoft.com/v1.0/me/calendars/work/calendarView").respond(
        json={"value": []}
    )
    list_events(
        from_date="2026-05-01T00:00:00Z",
        to_date="2026-05-08T00:00:00Z",
        calendar="work",
    )
    assert route.call_count == 1


@respx.mock
def test_list_events_returns_dicts(fresh_token: None) -> None:
    del fresh_token
    respx.get(PRIMARY_VIEW).respond(
        json={
            "value": [
                {
                    "id": "ev",
                    "subject": "Daily",
                    "organizer": {"emailAddress": {"name": "B", "address": "b@x.de"}},
                    "start": {"dateTime": "2026-05-09T09:00:00", "timeZone": "UTC"},
                    "end": {"dateTime": "2026-05-09T09:30:00", "timeZone": "UTC"},
                    "location": {"displayName": "Room A"},
                    "attendees": [],
                    "webLink": "https://outlook.office.com/x/ev",
                    "isAllDay": False,
                    "isCancelled": False,
                }
            ]
        }
    )
    out = list_events(from_date="2026-05-01T00:00:00Z", to_date="2026-05-10T00:00:00Z")
    assert len(out) == 1
    assert out[0]["id"] == "ev"


def test_list_events_empty_from_raises(fresh_token: None) -> None:
    del fresh_token
    with pytest.raises(ValueError, match="from_date"):
        list_events(from_date="", to_date="2026-05-10T00:00:00Z")


def test_list_events_empty_to_raises(fresh_token: None) -> None:
    del fresh_token
    with pytest.raises(ValueError, match="to_date"):
        list_events(from_date="2026-05-01T00:00:00Z", to_date="")
