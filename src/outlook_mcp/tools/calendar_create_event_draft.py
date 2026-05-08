# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""ol_calendar_create_event_draft — create a tentative event with no auto-invite.

Wraps `POST /me/events`. The crucial property: `responseRequested=False`
on the payload, which tells Microsoft Graph "don't email anyone an
invitation". The event lands on the user's calendar as a tentative
plan; the human reviews it in Outlook and clicks Send Invitation
manually if they want attendees notified.

**Never sends invitations.** There is no `send_invitation` tool. This
tool's reach ends at "tentative event saved on calendar".

Per docs/spikes/2026-05-08-v02-drafts-spikes.md § 3, this tool
**warns and creates** on overlap rather than refusing — matches
Outlook's own UX. The response carries a `warnings` array; the agent
+ human decide what to do with it. Calling code that wants strict
no-overlap behaviour can inspect `warnings` and call
`ol_calendar_discard_event_draft` to roll back.

Body shape mirrors `ol_email_create_draft`: `body=` is Markdown
(rendered safe), `body_html=` is raw HTML, mutually exclusive.
"""

from __future__ import annotations

from typing import Any

import httpx

from outlook_mcp.auth import get_token
from outlook_mcp.draft_registry import DraftEntry, DraftRegistry, now
from outlook_mcp.markdown import markdown_to_html
from outlook_mcp.tools._common import GRAPH_BASE, auth_headers


def create_event_draft(
    *,
    subject: str,
    start: str,
    end: str,
    time_zone: str = "UTC",
    attendees: list[str] | None = None,
    body: str | None = None,
    body_html: str | None = None,
    location: str | None = None,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> dict[str, Any]:
    """Create a tentative calendar event. Returns
    `{ event_id, web_url, warnings: list[dict] }`.

    `start` / `end` are ISO 8601 datetimes. `time_zone` is the
    IANA-style name Microsoft accepts (e.g. "Europe/Berlin",
    "Pacific Standard Time", "UTC"). The default is UTC for
    determinism.

    `responseRequested=False` is hard-coded on the payload so Graph
    never auto-sends invitations. The human reviews + decides.

    Conflict detection (per spike § 3): after creating, the tool does
    one extra Graph round-trip on `/me/calendarView` for the
    [start, end] window and reports any overlapping events as
    `warnings = [{type: "overlap", with: {subject, start, end, organizer}}]`.
    The draft is created either way — the agent decides how to react.

    Raises:
        ValueError: empty subject / start / end, both body kinds set.
        httpx.HTTPStatusError: non-2xx Graph response.
        outlook_mcp.auth.AuthRequiredError: no usable cached token.
    """
    if not subject or not subject.strip():
        raise ValueError("ol_calendar_create_event_draft: subject must be non-empty")
    if not start or not start.strip():
        raise ValueError("ol_calendar_create_event_draft: start must be non-empty")
    if not end or not end.strip():
        raise ValueError("ol_calendar_create_event_draft: end must be non-empty")
    if body is not None and body_html is not None:
        raise ValueError(
            "ol_calendar_create_event_draft: pass `body` (Markdown) OR `body_html`, not both",
        )

    if body_html is not None:
        body_payload: dict[str, str] | None = {"contentType": "html", "content": body_html}
    elif body is not None:
        body_payload = {"contentType": "html", "content": markdown_to_html(body)}
    else:
        body_payload = None

    payload: dict[str, Any] = {
        "subject": subject,
        "start": {"dateTime": start, "timeZone": time_zone},
        "end": {"dateTime": end, "timeZone": time_zone},
        # The defining property of this tool: never auto-send invites.
        "responseRequested": False,
    }
    if body_payload is not None:
        payload["body"] = body_payload
    if attendees:
        payload["attendees"] = [
            {"emailAddress": {"address": addr}, "type": "required"} for addr in attendees
        ]
    if location:
        payload["location"] = {"displayName": location}

    token = get_token(profile)
    headers = {**auth_headers(token), "Content-Type": "application/json"}
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        create_response = client.post(
            f"{GRAPH_BASE}/me/events",
            headers=headers,
            json=payload,
        )
        create_response.raise_for_status()
        event = create_response.json()
        event_id = str(event["id"])
        web_url_raw = event.get("webLink")

        # Conflict detection round-trip. Anything overlapping the
        # window that ISN'T this just-created event becomes a warning.
        warnings = _detect_overlaps(
            client,
            headers={
                "Authorization": headers["Authorization"],
                "User-Agent": headers["User-Agent"],
            },
            start=start,
            end=end,
            self_id=event_id,
        )
    finally:
        if http is None:
            client.close()

    web_url = str(web_url_raw) if web_url_raw else None

    DraftRegistry(profile=profile).add(
        DraftEntry(
            kind="event",
            graph_id=event_id,
            web_url=web_url,
            subject=subject,
            created_at=now(),
        )
    )

    return {"event_id": event_id, "web_url": web_url, "warnings": warnings}


def _detect_overlaps(
    client: httpx.Client,
    *,
    headers: dict[str, str],
    start: str,
    end: str,
    self_id: str,
) -> list[dict[str, Any]]:
    """Query /me/calendarView for the [start, end] window and report
    any events that aren't `self_id` as overlap warnings.

    Failures are non-fatal — if Graph returns an error here we still
    return the empty warnings list rather than blow up the just-created
    draft. The user sees the draft on their calendar regardless.
    """
    try:
        response = client.get(
            f"{GRAPH_BASE}/me/calendarView",
            headers=headers,
            params={
                "startDateTime": start,
                "endDateTime": end,
                "$select": "id,subject,start,end,organizer",
            },
        )
        response.raise_for_status()
        raw = response.json().get("value", []) or []
    except httpx.HTTPError:
        return []

    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for event in raw:
        if not isinstance(event, dict):
            continue
        if event.get("id") == self_id:
            continue
        organizer = (event.get("organizer") or {}).get("emailAddress") or {}
        out.append(
            {
                "type": "overlap",
                "with": {
                    "subject": event.get("subject"),
                    "start": (event.get("start") or {}).get("dateTime"),
                    "end": (event.get("end") or {}).get("dateTime"),
                    "organizer": organizer.get("address") or organizer.get("name"),
                },
            }
        )
    return out
