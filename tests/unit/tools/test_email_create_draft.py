# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for ol_email_create_draft.

Covers the happy-path POST shape Microsoft Graph expects, the
mutually-exclusive body/body_html guard, the registry-side-effect
that lets ol_status / future update / discard tools find the draft,
and the input-validation errors.
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
from outlook_mcp.tools.email_create_draft import create_draft

GRAPH_URL = "https://graph.microsoft.com/v1.0/me/messages"


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
        "outlook_mcp.tools.email_create_draft.get_token",
        lambda profile="default": get_token(profile=profile, store=store),
    )


@pytest.fixture
def isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect DraftRegistry's default base dir to a tmp path so the
    test doesn't pollute the developer's real ~/.cache/outlook-mcp."""
    monkeypatch.setattr(
        "outlook_mcp.tools.email_create_draft.DraftRegistry",
        lambda profile: DraftRegistry(profile=profile, base_dir=tmp_path),
    )
    return tmp_path


# ---------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------


@respx.mock
def test_create_draft_happy_path_with_markdown_body(
    fresh_token: None, isolated_registry: Path
) -> None:
    del fresh_token
    route = respx.post(GRAPH_URL).respond(
        json={
            "id": "draft-123",
            "webLink": "https://outlook.office.com/mail/drafts/id/draft-123",
        }
    )
    result = create_draft(
        to=["anna@example.com"],
        subject="Re: Friday meeting",
        body="**Yes** — Friday at 14:00 works.",
    )
    assert result == {
        "draft_id": "draft-123",
        "web_url": "https://outlook.office.com/mail/drafts/id/draft-123",
    }

    sent = json.loads(route.calls.last.request.read())
    assert sent["subject"] == "Re: Friday meeting"
    # Markdown was rendered to HTML
    assert sent["body"]["contentType"] == "html"
    assert "<strong>Yes</strong>" in sent["body"]["content"]
    assert sent["toRecipients"] == [{"emailAddress": {"address": "anna@example.com"}}]
    # No cc/bcc were sent because none were passed
    assert "ccRecipients" not in sent
    assert "bccRecipients" not in sent


@respx.mock
def test_create_draft_with_body_html_passes_through(
    fresh_token: None, isolated_registry: Path
) -> None:
    del fresh_token
    route = respx.post(GRAPH_URL).respond(json={"id": "d1", "webLink": "x"})
    create_draft(
        to=["a@x.de"],
        subject="Subj",
        body_html="<p>Custom <em>HTML</em></p>",
    )
    sent = json.loads(route.calls.last.request.read())
    assert sent["body"]["contentType"] == "html"
    assert sent["body"]["content"] == "<p>Custom <em>HTML</em></p>"


@respx.mock
def test_create_draft_with_no_body_sends_empty_text(
    fresh_token: None, isolated_registry: Path
) -> None:
    del fresh_token
    route = respx.post(GRAPH_URL).respond(json={"id": "d1", "webLink": "x"})
    create_draft(to=["a@x.de"], subject="Subj")
    sent = json.loads(route.calls.last.request.read())
    assert sent["body"] == {"contentType": "text", "content": ""}


@respx.mock
def test_create_draft_with_cc_and_bcc(fresh_token: None, isolated_registry: Path) -> None:
    del fresh_token
    route = respx.post(GRAPH_URL).respond(json={"id": "d1", "webLink": "x"})
    create_draft(
        to=["a@x.de"],
        subject="Subj",
        body="hi",
        cc=["c@x.de", "c2@x.de"],
        bcc=["b@x.de"],
    )
    sent = json.loads(route.calls.last.request.read())
    assert sent["ccRecipients"] == [
        {"emailAddress": {"address": "c@x.de"}},
        {"emailAddress": {"address": "c2@x.de"}},
    ]
    assert sent["bccRecipients"] == [{"emailAddress": {"address": "b@x.de"}}]


# ---------------------------------------------------------------------
# Registry side effect
# ---------------------------------------------------------------------


@respx.mock
def test_create_draft_records_to_registry(fresh_token: None, isolated_registry: Path) -> None:
    del fresh_token
    respx.post(GRAPH_URL).respond(
        json={"id": "draft-456", "webLink": "https://outlook.office.com/mail/draft-456"}
    )
    create_draft(to=["a@x.de"], subject="Hello", body="world")

    registry = DraftRegistry(profile="default", base_dir=isolated_registry)
    entries = registry.list_all()
    assert len(entries) == 1
    entry = entries[0]
    assert entry.kind == "email"
    assert entry.graph_id == "draft-456"
    assert entry.web_url == "https://outlook.office.com/mail/draft-456"
    assert entry.subject == "Hello"


@respx.mock
def test_create_draft_when_weblink_missing_records_none(
    fresh_token: None, isolated_registry: Path
) -> None:
    """Graph occasionally omits webLink on freshly-created drafts;
    registry should still record the entry with web_url=None."""
    del fresh_token
    respx.post(GRAPH_URL).respond(json={"id": "draft-no-link"})  # no webLink
    result = create_draft(to=["a@x.de"], subject="S", body="b")
    assert result["web_url"] is None
    entry = DraftRegistry(profile="default", base_dir=isolated_registry).get("draft-no-link")
    assert entry is not None
    assert entry.web_url is None


# ---------------------------------------------------------------------
# Validation errors (no Graph call should be made)
# ---------------------------------------------------------------------


def test_create_draft_rejects_both_body_kinds(fresh_token: None, isolated_registry: Path) -> None:
    del fresh_token, isolated_registry
    with pytest.raises(ValueError, match="not both"):
        create_draft(
            to=["a@x.de"],
            subject="x",
            body="markdown",
            body_html="<p>html</p>",
        )


def test_create_draft_rejects_empty_to_list(fresh_token: None, isolated_registry: Path) -> None:
    del fresh_token, isolated_registry
    with pytest.raises(ValueError, match="non-empty"):
        create_draft(to=[], subject="x", body="hi")


def test_create_draft_rejects_blank_subject(fresh_token: None, isolated_registry: Path) -> None:
    del fresh_token, isolated_registry
    with pytest.raises(ValueError, match="non-empty"):
        create_draft(to=["a@x.de"], subject="   ", body="hi")


# ---------------------------------------------------------------------
# Auth headers carried through (User-Agent + bearer)
# ---------------------------------------------------------------------


@respx.mock
def test_create_draft_sends_authorization_and_user_agent(
    fresh_token: None, isolated_registry: Path
) -> None:
    """Graph audit-trail invariant: every outbound request from any
    ol_* tool carries the Bearer token AND the
    mcp-server-outlook/<version> User-Agent."""
    del fresh_token, isolated_registry
    route = respx.post(GRAPH_URL).respond(json={"id": "d", "webLink": "x"})
    create_draft(to=["a@x.de"], subject="S", body="b")
    headers = route.calls.last.request.headers
    assert headers["Authorization"] == "Bearer AT"
    assert headers["User-Agent"].startswith("mcp-server-outlook/")
    assert headers["Content-Type"] == "application/json"


# ---------------------------------------------------------------------
# HTTP error propagation
# ---------------------------------------------------------------------


@respx.mock
def test_create_draft_propagates_403(fresh_token: None, isolated_registry: Path) -> None:
    """If Mail.ReadWrite isn't consented, Graph returns 403. We
    propagate so the agent surfaces a clear "re-login needed" path."""
    del fresh_token, isolated_registry
    respx.post(GRAPH_URL).respond(403, json={"error": {"code": "Forbidden"}})
    with pytest.raises(httpx.HTTPStatusError):
        create_draft(to=["a@x.de"], subject="S", body="b")


# ---------------------------------------------------------------------
# Attachments (v0.4)
# ---------------------------------------------------------------------


@respx.mock
def test_create_draft_with_small_attachment(fresh_token: None, isolated_registry: Path) -> None:
    """Happy path: small attachment uploaded via single-shot POST."""
    del fresh_token, isolated_registry
    import base64

    respx.post(GRAPH_URL).respond(json={"id": "draft-1", "webLink": "https://outlook.example/x"})
    att_route = respx.post(
        "https://graph.microsoft.com/v1.0/me/messages/draft-1/attachments"
    ).respond(201, json={"id": "att-1", "name": "spec.pdf", "size": 128})
    result = create_draft(
        to=["a@x.de"],
        subject="S",
        body="b",
        attachments=[
            {"name": "spec.pdf", "content_bytes_b64": base64.b64encode(b"x" * 128).decode()},
        ],
    )
    assert result["draft_id"] == "draft-1"
    assert result["attachments"] == [{"id": "att-1", "name": "spec.pdf", "size": 128}]
    assert att_route.call_count == 1


def test_create_draft_validates_attachments_before_post(
    fresh_token: None, isolated_registry: Path
) -> None:
    """Malformed attachment → no Graph POST is made (validation is pre-HTTP)."""
    del fresh_token, isolated_registry
    with respx.mock:
        msg_route = respx.post(GRAPH_URL)
        from outlook_mcp.tools._attachments import AttachmentSchemaError

        with pytest.raises(AttachmentSchemaError):
            create_draft(
                to=["a@x.de"],
                subject="S",
                body="b",
                attachments=[{"name": "ok.txt", "content_bytes_b64": "AAAA"}, {"name": "bad"}],
            )
        assert msg_route.call_count == 0
