# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for ol_email_read."""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest
import respx

from outlook_mcp.auth import get_token
from outlook_mcp.auth.tokens import CachedToken
from outlook_mcp.tools.email_read import read_email

MESSAGE_URL = "https://graph.microsoft.com/v1.0/me/messages/m1"
ATTACHMENTS_URL = "https://graph.microsoft.com/v1.0/me/messages/m1/attachments"


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
        "outlook_mcp.tools.email_read.get_token",
        lambda profile="default": get_token(profile=profile, store=store),
    )


def _message_payload(*, body_type: str = "html", has_attachments: bool = False) -> dict[str, Any]:
    return {
        "id": "m1",
        "subject": "Re: Friday",
        "from": {"emailAddress": {"name": "Anna", "address": "anna@x.de"}},
        "toRecipients": [
            {"emailAddress": {"name": "Me", "address": "me@x.de"}},
        ],
        "ccRecipients": [],
        "bccRecipients": [],
        "replyTo": [],
        "receivedDateTime": "2026-05-08T09:00:00Z",
        "sentDateTime": "2026-05-08T08:59:30Z",
        "body": {"contentType": body_type, "content": "<p>Hi</p>"},
        "webLink": "https://outlook.office.com/m/m1",
        "conversationId": "conv-1",
        "internetMessageId": "<abc@x.de>",
        "hasAttachments": has_attachments,
    }


@respx.mock
def test_read_happy_path(fresh_token: None) -> None:
    del fresh_token
    respx.get(MESSAGE_URL).respond(json=_message_payload())
    result = read_email("m1")
    assert result["id"] == "m1"
    assert result["from"] == {"name": "Anna", "address": "anna@x.de"}
    assert result["to"] == [{"name": "Me", "address": "me@x.de"}]
    assert result["body_html"] == "<p>Hi</p>"
    assert result["body_text"] is None
    assert result["attachments"] is None  # not requested


@respx.mock
def test_read_text_body(fresh_token: None) -> None:
    del fresh_token
    respx.get(MESSAGE_URL).respond(json=_message_payload(body_type="text"))
    result = read_email("m1")
    assert result["body_text"] == "<p>Hi</p>"
    assert result["body_html"] is None


@respx.mock
def test_read_with_attachments(fresh_token: None) -> None:
    del fresh_token
    respx.get(MESSAGE_URL).respond(json=_message_payload(has_attachments=True))
    respx.get(ATTACHMENTS_URL).respond(
        json={
            "value": [
                {
                    "id": "att1",
                    "name": "report.pdf",
                    "contentType": "application/pdf",
                    "size": 12345,
                    "isInline": False,
                }
            ]
        }
    )
    result = read_email("m1", include_attachments=True)
    assert result["attachments"] == [
        {
            "id": "att1",
            "name": "report.pdf",
            "content_type": "application/pdf",
            "size": 12345,
            "is_inline": False,
        }
    ]


@respx.mock
def test_read_skips_attachment_call_when_none_present(fresh_token: None) -> None:
    del fresh_token
    respx.get(MESSAGE_URL).respond(json=_message_payload(has_attachments=False))
    att_route = respx.get(ATTACHMENTS_URL).respond(json={"value": []})
    read_email("m1", include_attachments=True)
    # `has_attachments=False` short-circuits — no follow-up request.
    assert att_route.call_count == 0


def test_read_empty_id_raises(fresh_token: None) -> None:
    del fresh_token
    with pytest.raises(ValueError, match="non-empty message_id"):
        read_email("")


@respx.mock
def test_read_propagates_http_error(fresh_token: None) -> None:
    del fresh_token
    respx.get(MESSAGE_URL).respond(404)
    with pytest.raises(httpx.HTTPStatusError):
        read_email("m1")
