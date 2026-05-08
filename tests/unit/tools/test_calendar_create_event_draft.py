# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for ol_calendar_create_event_draft.

Pins three load-bearing properties:

1. `responseRequested: False` is on every outbound payload — the
   never-auto-invite rule.
2. Conflict detection runs after create and reports overlaps as
   structured warnings, but does NOT abort the create.
3. Registry side effect: the new event is recorded as kind="event".
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import pytest
import respx

from outlook_mcp.auth import get_token
from outlook_mcp.auth.tokens import CachedToken
from outlook_mcp.draft_registry import DraftRegistry
from outlook_mcp.tools.calendar_create_event_draft import create_event_draft

EVENTS_URL = "https://graph.microsoft.com/v1.0/me/events"
CAL_VIEW_URL = "https://graph.microsoft.com/v1.0/me/calendarView"


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
        "outlook_mcp.tools.calendar_create_event_draft.get_token",
        lambda profile="default": get_token(profile=profile, store=store),
    )


@pytest.fixture
def isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        "outlook_mcp.tools.calendar_create_event_draft.DraftRegistry",
        lambda profile: DraftRegistry(profile=profile, base_dir=tmp_path),
    )
    return tmp_path


# ---------------------------------------------------------------------
# The defining never-auto-invite invariant
# ---------------------------------------------------------------------


@respx.mock
def test_create_event_draft_sets_response_requested_false(
    fresh_token: None, isolated_registry: Path
) -> None:
    """Hard-coded `responseRequested: False` MUST be on every payload.
    If this regresses, attendees would receive surprise meeting
    invitations from a tool the user thought was creating drafts."""
    del fresh_token, isolated_registry
    create_route = respx.post(EVENTS_URL).respond(json={"id": "ev-1", "webLink": "x"})
    respx.get(CAL_VIEW_URL).respond(json={"value": []})
    create_event_draft(
        subject="Quick chat",
        start="2026-05-09T14:00:00",
        end="2026-05-09T14:30:00",
        attendees=["anna@example.com"],
    )
    sent = json.loads(create_route.calls.last.request.read())
    assert sent["responseRequested"] is False


# ---------------------------------------------------------------------
# Payload shape
# ---------------------------------------------------------------------


@respx.mock
def test_create_event_draft_payload_shape(fresh_token: None, isolated_registry: Path) -> None:
    del fresh_token, isolated_registry
    create_route = respx.post(EVENTS_URL).respond(json={"id": "ev-1", "webLink": "x"})
    respx.get(CAL_VIEW_URL).respond(json={"value": []})
    create_event_draft(
        subject="Q1 planning",
        start="2026-05-09T09:00:00",
        end="2026-05-09T10:00:00",
        time_zone="Europe/Berlin",
        attendees=["anna@example.com", "bob@example.com"],
        body="**agenda**",
        location="Office",
    )
    sent = json.loads(create_route.calls.last.request.read())
    assert sent["subject"] == "Q1 planning"
    assert sent["start"] == {"dateTime": "2026-05-09T09:00:00", "timeZone": "Europe/Berlin"}
    assert sent["end"] == {"dateTime": "2026-05-09T10:00:00", "timeZone": "Europe/Berlin"}
    assert sent["attendees"] == [
        {"emailAddress": {"address": "anna@example.com"}, "type": "required"},
        {"emailAddress": {"address": "bob@example.com"}, "type": "required"},
    ]
    assert sent["body"]["contentType"] == "html"
    assert "<strong>agenda</strong>" in sent["body"]["content"]
    assert sent["location"]["displayName"] == "Office"


@respx.mock
def test_create_event_draft_minimal_payload(fresh_token: None, isolated_registry: Path) -> None:
    """No attendees / body / location: those keys should be absent
    from the payload (don't send empty arrays)."""
    del fresh_token, isolated_registry
    create_route = respx.post(EVENTS_URL).respond(json={"id": "ev-1", "webLink": "x"})
    respx.get(CAL_VIEW_URL).respond(json={"value": []})
    create_event_draft(
        subject="Solo block",
        start="2026-05-09T14:00:00",
        end="2026-05-09T15:00:00",
    )
    sent = json.loads(create_route.calls.last.request.read())
    assert "attendees" not in sent
    assert "body" not in sent
    assert "location" not in sent


# ---------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------


@respx.mock
def test_create_event_draft_no_overlap_returns_empty_warnings(
    fresh_token: None, isolated_registry: Path
) -> None:
    del fresh_token, isolated_registry
    respx.post(EVENTS_URL).respond(json={"id": "ev-new", "webLink": "x"})
    # calendarView returns only the just-created event itself — no
    # overlap.
    respx.get(CAL_VIEW_URL).respond(
        json={
            "value": [
                {
                    "id": "ev-new",
                    "subject": "Solo block",
                    "start": {"dateTime": "2026-05-09T14:00:00"},
                    "end": {"dateTime": "2026-05-09T15:00:00"},
                    "organizer": {"emailAddress": {"address": "me@example.com"}},
                }
            ]
        }
    )
    result = create_event_draft(
        subject="Solo block",
        start="2026-05-09T14:00:00",
        end="2026-05-09T15:00:00",
    )
    assert result["warnings"] == []


@respx.mock
def test_create_event_draft_overlap_emits_warning_but_creates(
    fresh_token: None, isolated_registry: Path
) -> None:
    """Spike resolution: warn-and-create. The draft IS created even
    when an overlap exists; the agent gets a structured warning to
    decide what to do."""
    del fresh_token, isolated_registry
    respx.post(EVENTS_URL).respond(
        json={"id": "ev-new", "webLink": "https://outlook.office.com/calendar/ev-new"}
    )
    respx.get(CAL_VIEW_URL).respond(
        json={
            "value": [
                {
                    "id": "ev-existing",
                    "subject": "Customer review",
                    "start": {"dateTime": "2026-05-09T14:30:00"},
                    "end": {"dateTime": "2026-05-09T15:30:00"},
                    "organizer": {"emailAddress": {"address": "boss@example.com"}},
                },
                {
                    "id": "ev-new",
                    "subject": "Quick chat",
                    "start": {"dateTime": "2026-05-09T14:00:00"},
                    "end": {"dateTime": "2026-05-09T14:30:00"},
                    "organizer": {"emailAddress": {"address": "me@example.com"}},
                },
            ]
        }
    )
    result = create_event_draft(
        subject="Quick chat",
        start="2026-05-09T14:00:00",
        end="2026-05-09T14:30:00",
    )
    assert result["event_id"] == "ev-new"
    assert result["web_url"] == "https://outlook.office.com/calendar/ev-new"
    assert len(result["warnings"]) == 1
    warning = result["warnings"][0]
    assert warning["type"] == "overlap"
    assert warning["with"]["subject"] == "Customer review"
    assert warning["with"]["organizer"] == "boss@example.com"


@respx.mock
def test_create_event_draft_overlap_check_failure_does_not_abort(
    fresh_token: None, isolated_registry: Path
) -> None:
    """If the overlap-detection round-trip fails for any reason, the
    just-created draft must still be returned. Warnings list is empty
    in that case (we couldn't determine; treat as no overlap)."""
    del fresh_token, isolated_registry
    respx.post(EVENTS_URL).respond(json={"id": "ev-new", "webLink": "x"})
    respx.get(CAL_VIEW_URL).respond(500)
    result = create_event_draft(
        subject="x",
        start="2026-05-09T14:00:00",
        end="2026-05-09T14:30:00",
    )
    assert result["event_id"] == "ev-new"
    assert result["warnings"] == []


# ---------------------------------------------------------------------
# Registry side effect
# ---------------------------------------------------------------------


@respx.mock
def test_create_event_draft_records_event_kind(fresh_token: None, isolated_registry: Path) -> None:
    del fresh_token
    respx.post(EVENTS_URL).respond(
        json={"id": "ev-1", "webLink": "https://outlook.office.com/c/ev-1"}
    )
    respx.get(CAL_VIEW_URL).respond(json={"value": []})
    create_event_draft(
        subject="Meeting",
        start="2026-05-09T14:00:00",
        end="2026-05-09T14:30:00",
    )
    entry = DraftRegistry(profile="default", base_dir=isolated_registry).get("ev-1")
    assert entry is not None
    assert entry.kind == "event"
    assert entry.subject == "Meeting"


# ---------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------


def test_create_event_draft_rejects_blank_subject(
    fresh_token: None, isolated_registry: Path
) -> None:
    del fresh_token, isolated_registry
    with pytest.raises(ValueError, match="subject"):
        create_event_draft(subject="  ", start="2026-05-09T14:00:00", end="2026-05-09T14:30:00")


def test_create_event_draft_rejects_blank_start(fresh_token: None, isolated_registry: Path) -> None:
    del fresh_token, isolated_registry
    with pytest.raises(ValueError, match="start"):
        create_event_draft(subject="x", start="", end="2026-05-09T14:30:00")


def test_create_event_draft_rejects_both_body_kinds(
    fresh_token: None, isolated_registry: Path
) -> None:
    del fresh_token, isolated_registry
    with pytest.raises(ValueError, match="not both"):
        create_event_draft(
            subject="x",
            start="2026-05-09T14:00:00",
            end="2026-05-09T14:30:00",
            body="md",
            body_html="<p>html</p>",
        )


# ---------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------


@respx.mock
def test_create_event_draft_sends_user_agent(fresh_token: None, isolated_registry: Path) -> None:
    del fresh_token, isolated_registry
    create_route = respx.post(EVENTS_URL).respond(json={"id": "ev-1", "webLink": "x"})
    respx.get(CAL_VIEW_URL).respond(json={"value": []})
    create_event_draft(subject="x", start="2026-05-09T14:00:00", end="2026-05-09T14:30:00")
    headers = create_route.calls.last.request.headers
    assert headers["Authorization"] == "Bearer AT"
    assert headers["User-Agent"].startswith("mcp-server-outlook/")


# ---------------------------------------------------------------------
# HTTP error propagation
# ---------------------------------------------------------------------


@respx.mock
def test_create_event_draft_propagates_403(fresh_token: None, isolated_registry: Path) -> None:
    del fresh_token, isolated_registry
    respx.post(EVENTS_URL).respond(403)
    with pytest.raises(httpx.HTTPStatusError):
        create_event_draft(subject="x", start="2026-05-09T14:00:00", end="2026-05-09T14:30:00")
