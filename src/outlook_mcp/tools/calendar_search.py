# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""ol_calendar_search — free-text search over the user's calendar events.

Wraps `GET /me/events` with `$search` for full-text matching plus
optional from/to date filters. Read-only, idempotent.

Microsoft Graph note: when `$search` is used on /events, Graph
disallows `$orderby` (relevance ranking). For a date-windowed list
sorted by start time, prefer `ol_calendar_list_events`, which uses
`/calendarView` and supports range + ordering.
"""

from __future__ import annotations

from typing import Any

import httpx

from outlook_mcp.auth import get_token
from outlook_mcp.tools._common import GRAPH_BASE, auth_headers


def search(
    query: str,
    *,
    calendar: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 25,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Search calendar events on the signed-in user's calendar.

    Returns at most `limit` hits with `id`, `subject`, `organizer`,
    `start` (ISO 8601 + timezone), `end`, `location`, `attendees`
    (list of `{name, address, response_status}`), `web_url`,
    `is_all_day`, `is_cancelled`. Empty list is valid.

    Filter args:

    - `calendar="primary"` — by default uses the primary calendar.
      Pass another well-known calendar name or a calendar id to scope
      to a different one.
    - `from_date="2024-01-01T00:00:00Z"` — ISO 8601 lower bound on
      `start.dateTime`.
    - `to_date="2024-12-31T23:59:59Z"` — ISO 8601 upper bound.

    Raises:
        ValueError: empty query / non-positive limit.
        httpx.HTTPStatusError: on a non-2xx response from Graph.
        outlook_mcp.auth.AuthRequiredError: no cached token.
    """
    if not query or not query.strip():
        raise ValueError("ol_calendar_search requires a non-empty query")
    if limit <= 0:
        raise ValueError(f"limit must be positive, got {limit}")

    if calendar:
        url = f"{GRAPH_BASE}/me/calendars/{calendar}/events"
    else:
        url = f"{GRAPH_BASE}/me/events"

    params: dict[str, str | int] = {
        "$search": f'"{query.strip()}"',
        "$top": limit,
        "$select": (
            "id,subject,organizer,start,end,location,attendees,webLink,isAllDay,isCancelled"
        ),
    }
    filter_parts: list[str] = []
    if from_date:
        filter_parts.append(f"start/dateTime ge '{from_date}'")
    if to_date:
        filter_parts.append(f"end/dateTime le '{to_date}'")
    if filter_parts:
        params["$filter"] = " and ".join(filter_parts)

    token = get_token(profile)
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        response = client.get(url, headers=auth_headers(token), params=params)
        response.raise_for_status()
        return _extract(response.json())
    finally:
        if http is None:
            client.close()


def _extract(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("value", [])
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for event in raw:
        if not isinstance(event, dict):
            continue
        out.append(_event_to_dict(event))
    return out


def _event_to_dict(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": event.get("id"),
        "subject": event.get("subject"),
        "organizer": _extract_address(event.get("organizer")),
        "start": _extract_datetime(event.get("start")),
        "end": _extract_datetime(event.get("end")),
        "location": _extract_location(event.get("location")),
        "attendees": _extract_attendees(event.get("attendees")),
        "web_url": event.get("webLink"),
        "is_all_day": bool(event.get("isAllDay", False)),
        "is_cancelled": bool(event.get("isCancelled", False)),
    }


def _extract_datetime(raw: dict[str, Any] | None) -> dict[str, str | None] | None:
    if not isinstance(raw, dict):
        return None
    return {
        "date_time": raw.get("dateTime"),
        "time_zone": raw.get("timeZone"),
    }


def _extract_location(raw: dict[str, Any] | None) -> str | None:
    if not isinstance(raw, dict):
        return None
    name = raw.get("displayName")
    return str(name) if name else None


def _extract_address(raw: dict[str, Any] | None) -> dict[str, str | None] | None:
    if not isinstance(raw, dict):
        return None
    inner = raw.get("emailAddress")
    if not isinstance(inner, dict):
        return None
    return {
        "name": inner.get("name"),
        "address": inner.get("address"),
    }


def _extract_attendees(raw: list[Any] | None) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        flat = _extract_address(item)
        if flat is None:
            continue
        status = item.get("status") or {}
        out.append(
            {
                "name": flat.get("name"),
                "address": flat.get("address"),
                "response_status": (status.get("response") if isinstance(status, dict) else None),
            }
        )
    return out
