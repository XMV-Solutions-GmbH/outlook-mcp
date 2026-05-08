# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""ol_calendar_list_events — list events in a date range.

Wraps `GET /me/calendarView?startDateTime=…&endDateTime=…`. Read-only.
The `calendarView` endpoint expands recurring events into individual
occurrences within the window — that's what the agent almost always
wants when answering "what's on my calendar this week?".

Sorts by start time ascending. Returns the same per-event shape as
`ol_calendar_search`. Times are returned in the timezone Microsoft
issued them in; the caller chooses how to render them.
"""

from __future__ import annotations

from typing import Any

import httpx

from outlook_mcp.auth import get_token
from outlook_mcp.tools._common import GRAPH_BASE, auth_headers
from outlook_mcp.tools.calendar_search import _event_to_dict


def list_events(
    *,
    from_date: str,
    to_date: str,
    calendar: str = "primary",
    limit: int = 100,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """List events on `calendar` between `from_date` and `to_date`.

    `from_date` and `to_date` are ISO 8601 datetimes (UTC `Z` or with
    explicit offset). `calendar="primary"` uses the user's default
    calendar — switch to another calendar's well-known name or id to
    list a different one.

    Returns up to `limit` events ordered by start time ascending.

    Raises:
        ValueError: empty from/to / non-positive limit.
        httpx.HTTPStatusError: on a non-2xx response from Graph.
        outlook_mcp.auth.AuthRequiredError: no cached token.
    """
    if not from_date or not from_date.strip():
        raise ValueError("ol_calendar_list_events requires a non-empty from_date")
    if not to_date or not to_date.strip():
        raise ValueError("ol_calendar_list_events requires a non-empty to_date")
    if limit <= 0:
        raise ValueError(f"limit must be positive, got {limit}")

    if calendar == "primary":
        url = f"{GRAPH_BASE}/me/calendarView"
    else:
        url = f"{GRAPH_BASE}/me/calendars/{calendar}/calendarView"

    params: dict[str, str | int] = {
        "startDateTime": from_date,
        "endDateTime": to_date,
        "$orderby": "start/dateTime asc",
        "$top": limit,
        "$select": (
            "id,subject,organizer,start,end,location,attendees,webLink,isAllDay,isCancelled"
        ),
    }

    token = get_token(profile)
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        response = client.get(url, headers=auth_headers(token), params=params)
        response.raise_for_status()
        raw = response.json().get("value", []) or []
        if not isinstance(raw, list):
            return []
        return [_event_to_dict(e) for e in raw if isinstance(e, dict)]
    finally:
        if http is None:
            client.close()
