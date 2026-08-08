# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Reading Microsoft 365 **group** mailboxes.

A group mailbox is a different Graph surface from a user or shared
mailbox, not a variant of it. Three differences drive everything here:

1. **Different path.** Group mail lives under `/groups/{id}/threads`
   and `/groups/{id}/threads/{tid}/posts`. `/users/{upn}/messages`
   answers `ErrorGroupIsUsedInNonGroupURI` even for a group's own
   members.

2. **No `$search`.** `conversationThread` does not support Graph's
   full-text search, so `ol_email_search` on a group filters
   client-side over the fields a thread actually carries (`topic`,
   `preview`, `uniqueSenders`). This is a genuinely weaker match than
   the mailbox path — it never sees message bodies — and the tool
   description says so rather than pretending the two are equivalent.

3. **No recipient fields.** A `post` carries `from` and `sender` but no
   `toRecipients`. That matters more than it sounds: a group mailbox
   collecting plus-addressed mail (`box+case@example.com`) would be
   unreadable as to *which* address a message arrived on — exactly the
   thing such a scheme exists to distinguish. The address is still
   recoverable from the MAPI property `PidTagDisplayTo`, which we
   `$expand` and surface as `to`.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from outlook_mcp.tools._common import GRAPH_BASE, auth_headers, group_path

# PidTagDisplayTo — the message's To: line as delivered. The only route
# to the recipient address on a group post; see the module docstring.
_DISPLAY_TO_PROP = "String 0x0E04"

_THREAD_FIELDS = "id,topic,preview,uniqueSenders,lastDeliveredDateTime,hasAttachments"


def _expand_display_to() -> str:
    """Build the `$expand` value that pulls PidTagDisplayTo onto a post.

    Returned **unencoded**: every caller passes it through httpx's
    `params=`, which percent-encodes it once. Pre-encoding here produced
    a double-encoded `$expand` that Graph answered with 400, which cost
    a live debugging round — the unit tests could not see it because
    respx matched the URL regardless of the query string.
    """
    return f"singleValueExtendedProperties($filter=id eq '{_DISPLAY_TO_PROP}')"


def _same_property(returned: object, wanted: str) -> bool:
    """Compare two MAPI property tags tolerantly.

    Graph does NOT echo the tag as sent: request `String 0x0E04` and the
    response carries `String 0xe04` — lower-cased, leading zero dropped.
    Comparing the strings verbatim silently finds nothing, so compare
    the numeric tag instead.
    """
    if not isinstance(returned, str):
        return False

    def parts(tag: str) -> tuple[str, int] | None:
        kind, _, value = tag.partition(" ")
        try:
            return kind.strip().lower(), int(value.strip(), 16)
        except ValueError:
            return None

    left, right = parts(returned), parts(wanted)
    return left is not None and left == right


def _display_to(post: dict[str, Any]) -> str | None:
    """Read the recipient address off an expanded post, if present."""
    props = post.get("singleValueExtendedProperties")
    if not isinstance(props, list):
        return None
    for prop in props:
        if isinstance(prop, dict) and _same_property(prop.get("id"), _DISPLAY_TO_PROP):
            value = prop.get("value")
            return value if isinstance(value, str) and value else None
    return None


def _address(raw: dict[str, Any] | None) -> dict[str, str | None] | None:
    """Flatten Graph's nested {emailAddress: {name, address}}."""
    if not isinstance(raw, dict):
        return None
    inner = raw.get("emailAddress")
    if not isinstance(inner, dict):
        return None
    return {"name": inner.get("name"), "address": inner.get("address")}


def _matches(thread: dict[str, Any], needle: str) -> bool:
    """Case-insensitive substring match over a thread's visible fields."""
    haystack = [
        str(thread.get("topic") or ""),
        str(thread.get("preview") or ""),
        " ".join(str(s) for s in (thread.get("uniqueSenders") or [])),
    ]
    return any(needle in part.lower() for part in haystack)


def search_threads(
    mailbox: str,
    query: str,
    *,
    token: str,
    client: httpx.Client,
    limit: int = 25,
    from_address: str | None = None,
    modified_after: str | None = None,
    has_attachment: bool | None = None,
    to_address: str | None = None,
) -> list[dict[str, Any]]:
    """Search a group's conversation threads.

    Returns hits shaped like `ol_email_search`'s mailbox results, so the
    tool contract does not fork: `id` (the thread id, which
    `read_thread` accepts), `subject`, `from`, `received_at`, `snippet`,
    `web_url` (always None — threads have no Outlook web link),
    `has_attachments`, plus `to` (the delivered-to address).

    Recipients are resolved with one extra request per surviving hit, so
    the cost is bounded by `limit`, not by the size of the group.
    """
    base = f"{GRAPH_BASE}/{group_path(mailbox)}/threads"
    headers = auth_headers(token)

    # Over-fetch: the text match happens here rather than in Graph, so
    # narrowing to `limit` before filtering would silently drop hits.
    response = client.get(
        base,
        headers=headers,
        params={"$top": max(limit * 4, 50), "$select": _THREAD_FIELDS},
    )
    response.raise_for_status()
    threads = response.json().get("value", [])
    if not isinstance(threads, list):
        return []

    needle = query.strip().lower()
    out: list[dict[str, Any]] = []
    for thread in threads:
        if not isinstance(thread, dict):
            continue
        if needle and not _matches(thread, needle):
            continue
        if modified_after and str(thread.get("lastDeliveredDateTime") or "") < modified_after:
            continue
        if has_attachment is not None and bool(thread.get("hasAttachments")) is not has_attachment:
            continue

        hit = _thread_hit(thread)
        first = _first_post(
            mailbox,
            str(thread.get("id")),
            token=token,
            client=client,
        )
        if first is not None:
            hit["from"] = _address(first.get("from")) or hit["from"]
            hit["to"] = _display_to(first)
            hit["received_at"] = first.get("receivedDateTime") or hit["received_at"]

        # `address` is legitimately None on a thread whose posts could
        # not be read, so normalise before comparing rather than
        # assuming a string.
        if from_address:
            sender = ((hit.get("from") or {}).get("address") or "").lower()
            if sender != from_address.lower():
                continue
        if to_address and (hit.get("to") or "").lower() != to_address.lower():
            continue

        out.append(hit)
        if len(out) >= limit:
            break
    return out


def _thread_hit(thread: dict[str, Any]) -> dict[str, Any]:
    """Shape a thread into the shared search-hit contract."""
    senders = thread.get("uniqueSenders") or []
    return {
        "id": thread.get("id"),
        "subject": thread.get("topic"),
        # Best effort until the post is fetched: a thread only exposes
        # sender *names*, never addresses.
        "from": {"name": senders[0], "address": None} if senders else None,
        "received_at": thread.get("lastDeliveredDateTime"),
        "snippet": thread.get("preview"),
        "web_url": None,
        "has_attachments": bool(thread.get("hasAttachments", False)),
        "to": None,
    }


def _first_post(
    mailbox: str,
    thread_id: str,
    *,
    token: str,
    client: httpx.Client,
) -> dict[str, Any] | None:
    """Fetch a thread's first post, with PidTagDisplayTo expanded."""
    url = f"{GRAPH_BASE}/{group_path(mailbox)}/threads/{quote(thread_id, safe='')}/posts"
    response = client.get(
        url,
        headers=auth_headers(token),
        params={"$top": 1, "$expand": _expand_display_to()},
    )
    if response.status_code >= 400:
        # A thread that lists but whose posts are unreadable should
        # degrade to a hit without recipient data, not fail the search.
        return None
    posts = response.json().get("value", [])
    return posts[0] if isinstance(posts, list) and posts and isinstance(posts[0], dict) else None


def read_thread(
    mailbox: str,
    thread_id: str,
    *,
    token: str,
    client: httpx.Client,
) -> dict[str, Any]:
    """Read every post in a group conversation thread.

    Returns the `ol_email_read` shape where it maps, with `posts`
    carrying the per-post detail a thread has instead of a single body.
    """
    url = f"{GRAPH_BASE}/{group_path(mailbox)}/threads/{quote(thread_id, safe='')}/posts"
    response = client.get(
        url,
        headers=auth_headers(token),
        params={"$expand": _expand_display_to()},
    )
    response.raise_for_status()
    raw = response.json().get("value", [])
    posts = [p for p in raw if isinstance(p, dict)] if isinstance(raw, list) else []

    rendered = [
        {
            "id": post.get("id"),
            "from": _address(post.get("from")),
            "to": _display_to(post),
            "received_at": post.get("receivedDateTime"),
            "body_text": _body(post, "text"),
            "body_html": _body(post, "html"),
            "has_attachments": bool(post.get("hasAttachments", False)),
        }
        for post in posts
    ]
    first = rendered[0] if rendered else {}
    return {
        "id": thread_id,
        "mailbox": mailbox,
        "from": first.get("from"),
        "to": first.get("to"),
        "received_at": first.get("received_at"),
        "body_text": first.get("body_text"),
        "body_html": first.get("body_html"),
        "has_attachments": any(p["has_attachments"] for p in rendered),
        "posts": rendered,
    }


def _body(post: dict[str, Any], want: str) -> str | None:
    """Return the post body when it is of the requested content type."""
    body = post.get("body")
    if not isinstance(body, dict):
        return None
    content_type = str(body.get("contentType") or "").lower()
    if content_type != want:
        return None
    content = body.get("content")
    return content if isinstance(content, str) else None
