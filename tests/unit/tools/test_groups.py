# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for Microsoft 365 group-mailbox reads."""

from __future__ import annotations

import time

import httpx
import pytest
import respx

from outlook_mcp.auth import get_token
from outlook_mcp.auth.tokens import CachedToken
from outlook_mcp.tools._common import (
    group_id,
    group_path,
    is_group_mailbox,
    mailbox_path,
)
from outlook_mcp.tools._groups import read_thread, search_threads
from outlook_mcp.tools.email_search import search

GID = "cdf5cd73-94c4-4c56-bdd1-0467dba73667"
MAILBOX = f"group:{GID}"
THREADS_URL = f"https://graph.microsoft.com/v1.0/groups/{GID}/threads"

# The form Graph ACTUALLY returns: we request `String 0x0E04` and get
# `String 0xe04` back, normalised. Fixtures use the response form on
# purpose — an earlier version of these tests echoed the request form
# and therefore passed while the live call found nothing.
DISPLAY_TO = "String 0xe04"


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
    fresh = CachedToken(
        access_token="AT", refresh_token="RT", expires_at=time.time() + 3600, scope=""
    )
    store = _MemStore(token=fresh)
    monkeypatch.setattr(
        "outlook_mcp.tools.email_search.get_token",
        lambda profile="default": get_token(profile=profile, store=store),
    )


def _thread(tid: str = "t1", topic: str = "Verify your address") -> dict[str, object]:
    return {
        "id": tid,
        "topic": topic,
        "preview": "Please confirm",
        "uniqueSenders": ["XMV Authenticity"],
        "lastDeliveredDateTime": "2026-08-08T21:39:53Z",
        "hasAttachments": False,
    }


def _post(to: str | None = "harness+authenticity_signup01@xmv.de") -> dict[str, object]:
    post: dict[str, object] = {
        "id": "p1",
        "from": {"emailAddress": {"name": "XMV", "address": "no-reply@xmv.de"}},
        "receivedDateTime": "2026-08-08T21:39:53Z",
        "body": {"contentType": "text", "content": "Confirm: https://auth/x"},
        "hasAttachments": False,
    }
    if to is not None:
        post["singleValueExtendedProperties"] = [{"id": DISPLAY_TO, "value": to}]
    return post


# --- addressing -----------------------------------------------------


def test_is_group_mailbox_detects_prefix() -> None:
    assert is_group_mailbox(MAILBOX)
    assert is_group_mailbox(f"GROUP:{GID}")
    assert not is_group_mailbox("sekretariat@xmv.de")
    assert not is_group_mailbox(None)


def test_group_id_extracts_guid() -> None:
    assert group_id(MAILBOX) == GID
    assert group_path(MAILBOX) == f"groups/{GID}"


def test_group_id_rejects_an_address() -> None:
    """A group's address cannot stand in for its id — we cannot resolve it."""
    with pytest.raises(ValueError, match="Entra object id"):
        group_id("group:harness@xmv.de")


def test_group_id_rejects_path_traversal() -> None:
    with pytest.raises(ValueError):
        group_id("group:../../users/victim@xmv.de")


def test_mailbox_path_refuses_group_form() -> None:
    """Group mail is not under /users/ — Exchange rejects that outright."""
    with pytest.raises(ValueError, match="not addressable under /users/"):
        mailbox_path(MAILBOX)


# --- search ---------------------------------------------------------


@respx.mock
def test_search_threads_returns_recipient_from_mapi_property() -> None:
    respx.get(THREADS_URL).respond(json={"value": [_thread()]})
    respx.get(f"{THREADS_URL}/t1/posts").respond(json={"value": [_post()]})

    with httpx.Client() as client:
        hits = search_threads(MAILBOX, "verify", token="AT", client=client)

    assert len(hits) == 1
    assert hits[0]["to"] == "harness+authenticity_signup01@xmv.de"
    assert hits[0]["from"] == {"name": "XMV", "address": "no-reply@xmv.de"}
    assert hits[0]["id"] == "t1"
    # Threads have no Outlook web link; say so rather than inventing one.
    assert hits[0]["web_url"] is None


@respx.mock
def test_search_threads_filters_on_topic_client_side() -> None:
    respx.get(THREADS_URL).respond(
        json={"value": [_thread("t1", "Verify"), _thread("t2", "Newsletter")]},
    )
    respx.get(f"{THREADS_URL}/t1/posts").respond(json={"value": [_post()]})

    with httpx.Client() as client:
        hits = search_threads(MAILBOX, "verify", token="AT", client=client)

    assert [h["id"] for h in hits] == ["t1"]


@respx.mock
def test_search_threads_filters_on_to_address() -> None:
    """The plus-address filter is the point of the whole group path."""
    respx.get(THREADS_URL).respond(
        json={"value": [_thread("t1", "Verify"), _thread("t2", "Verify")]},
    )
    respx.get(f"{THREADS_URL}/t1/posts").respond(
        json={"value": [_post("harness+app_case01@xmv.de")]},
    )
    respx.get(f"{THREADS_URL}/t2/posts").respond(
        json={"value": [_post("harness+app_case02@xmv.de")]},
    )

    with httpx.Client() as client:
        hits = search_threads(
            MAILBOX,
            "verify",
            token="AT",
            client=client,
            to_address="harness+app_case02@xmv.de",
        )

    assert [h["id"] for h in hits] == ["t2"]


@respx.mock
def test_search_threads_survives_unreadable_posts() -> None:
    """A thread whose posts 403 still lists, just without recipient data."""
    respx.get(THREADS_URL).respond(json={"value": [_thread()]})
    respx.get(f"{THREADS_URL}/t1/posts").respond(403, json={"error": {"code": "denied"}})

    with httpx.Client() as client:
        hits = search_threads(MAILBOX, "verify", token="AT", client=client)

    assert len(hits) == 1
    assert hits[0]["to"] is None


@respx.mock
def test_search_threads_respects_limit() -> None:
    respx.get(THREADS_URL).respond(
        json={"value": [_thread(f"t{i}", "Verify") for i in range(5)]},
    )
    for i in range(5):
        respx.get(f"{THREADS_URL}/t{i}/posts").respond(json={"value": [_post()]})

    with httpx.Client() as client:
        hits = search_threads(MAILBOX, "verify", token="AT", client=client, limit=2)

    assert len(hits) == 2


@respx.mock
def test_email_search_routes_group_mailbox(fresh_token: None) -> None:
    """The public search entry point dispatches on the mailbox form."""
    del fresh_token
    respx.get(THREADS_URL).respond(json={"value": [_thread()]})
    respx.get(f"{THREADS_URL}/t1/posts").respond(json={"value": [_post()]})

    hits = search("verify", mailbox=MAILBOX)

    assert hits[0]["to"] == "harness+authenticity_signup01@xmv.de"


def test_email_search_rejects_folder_on_group(fresh_token: None) -> None:
    del fresh_token
    with pytest.raises(ValueError, match="not available on group mailboxes"):
        search("verify", mailbox=MAILBOX, folder="Inbox")


# --- read -----------------------------------------------------------


def test_property_tag_comparison_is_normalisation_tolerant() -> None:
    """Graph normalises the tag it echoes; both forms must match."""
    from outlook_mcp.tools._groups import _same_property

    assert _same_property("String 0xe04", "String 0x0E04")
    assert _same_property("String 0x0E04", "String 0x0E04")
    assert not _same_property("String 0xe05", "String 0x0E04")
    assert not _same_property("Binary 0xe04", "String 0x0E04")
    assert not _same_property(None, "String 0x0E04")


@respx.mock
def test_read_thread_returns_posts_and_body() -> None:
    respx.get(f"{THREADS_URL}/t1/posts").respond(json={"value": [_post()]})

    with httpx.Client() as client:
        result = read_thread(MAILBOX, "t1", token="AT", client=client)

    assert result["id"] == "t1"
    assert result["to"] == "harness+authenticity_signup01@xmv.de"
    assert result["body_text"] == "Confirm: https://auth/x"
    assert result["body_html"] is None
    assert len(result["posts"]) == 1
