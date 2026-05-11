# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for ol_email_update_draft.

Pins:

- The "only-mutate-our-own-drafts" defensive: drafts not present in
  the per-profile registry must produce DraftNotOwnedError, with no
  Graph call made.
- The PATCH payload only includes keys for fields the caller actually
  passed (None = leave unchanged), and empty list `[]` correctly
  serialises as "clear this field".
- The body-vs-body_html mutual exclusion mirrors the create tool.
- The registry entry is refreshed when subject changes (so ol_status
  reflects the new title).
- The User-Agent + Authorization header invariant.
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
from outlook_mcp.draft_registry import DraftEntry, DraftRegistry
from outlook_mcp.tools.email_update_draft import DraftNotOwnedError, update_draft

GRAPH_URL = "https://graph.microsoft.com/v1.0/me/messages/draft-1"


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
        "outlook_mcp.tools.email_update_draft.get_token",
        lambda profile="default": get_token(profile=profile, store=store),
    )


@pytest.fixture
def isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect DraftRegistry's default base dir to tmp_path; pre-seed
    a single draft entry the tests can reference."""
    monkeypatch.setattr(
        "outlook_mcp.tools.email_update_draft.DraftRegistry",
        lambda profile: DraftRegistry(profile=profile, base_dir=tmp_path),
    )
    DraftRegistry(profile="default", base_dir=tmp_path).add(
        DraftEntry(
            kind="email",
            graph_id="draft-1",
            web_url="https://outlook.office.com/mail/drafts/draft-1",
            subject="Original",
            created_at=1715000000.0,
        )
    )
    return tmp_path


# ---------------------------------------------------------------------
# Defensive: not-owned draft refused
# ---------------------------------------------------------------------


def test_update_unknown_draft_raises_DraftNotOwnedError(
    fresh_token: None, isolated_registry: Path
) -> None:
    """Crucial property: hand-typed drafts in Outlook are NEVER in
    the registry. update_draft refuses to touch them. No Graph call
    should be made for an unowned id."""
    del fresh_token, isolated_registry
    with respx.mock(base_url="https://graph.microsoft.com") as router:
        with pytest.raises(DraftNotOwnedError, match="not created by profile"):
            update_draft("never-created-by-us", subject="evil")
        # Make sure no Graph call leaked.
        assert not router.calls


# ---------------------------------------------------------------------
# Happy paths — payload shape
# ---------------------------------------------------------------------


@respx.mock
def test_update_subject_only(fresh_token: None, isolated_registry: Path) -> None:
    del fresh_token
    route = respx.patch(GRAPH_URL).respond(
        json={
            "id": "draft-1",
            "webLink": "https://outlook.office.com/mail/drafts/draft-1",
        }
    )
    result = update_draft("draft-1", subject="Updated Subject")
    sent = json.loads(route.calls.last.request.read())
    assert sent == {"subject": "Updated Subject"}
    assert result["draft_id"] == "draft-1"
    # Registry refreshed
    entry = DraftRegistry(profile="default", base_dir=isolated_registry).get("draft-1")
    assert entry is not None
    assert entry.subject == "Updated Subject"


@respx.mock
def test_update_body_markdown_renders_to_html(fresh_token: None, isolated_registry: Path) -> None:
    del fresh_token, isolated_registry
    route = respx.patch(GRAPH_URL).respond(json={"id": "draft-1"})
    update_draft("draft-1", body="**hello**")
    sent = json.loads(route.calls.last.request.read())
    assert sent["body"]["contentType"] == "html"
    assert "<strong>hello</strong>" in sent["body"]["content"]


@respx.mock
def test_update_body_html_passes_through(fresh_token: None, isolated_registry: Path) -> None:
    del fresh_token, isolated_registry
    route = respx.patch(GRAPH_URL).respond(json={"id": "draft-1"})
    update_draft("draft-1", body_html="<p>raw</p>")
    sent = json.loads(route.calls.last.request.read())
    assert sent["body"] == {"contentType": "html", "content": "<p>raw</p>"}


@respx.mock
def test_update_recipients_set(fresh_token: None, isolated_registry: Path) -> None:
    del fresh_token, isolated_registry
    route = respx.patch(GRAPH_URL).respond(json={"id": "draft-1"})
    update_draft(
        "draft-1",
        to=["new@x.de"],
        cc=["c@x.de"],
        bcc=["b@x.de"],
    )
    sent = json.loads(route.calls.last.request.read())
    assert sent["toRecipients"] == [{"emailAddress": {"address": "new@x.de"}}]
    assert sent["ccRecipients"] == [{"emailAddress": {"address": "c@x.de"}}]
    assert sent["bccRecipients"] == [{"emailAddress": {"address": "b@x.de"}}]


@respx.mock
def test_update_empty_list_clears_recipients(fresh_token: None, isolated_registry: Path) -> None:
    """Empty list `[]` clears the field. None = leave unchanged."""
    del fresh_token, isolated_registry
    route = respx.patch(GRAPH_URL).respond(json={"id": "draft-1"})
    update_draft("draft-1", cc=[])
    sent = json.loads(route.calls.last.request.read())
    # cc is present but empty
    assert sent["ccRecipients"] == []
    # to / bcc not present at all (None = leave unchanged)
    assert "toRecipients" not in sent
    assert "bccRecipients" not in sent


@respx.mock
def test_update_only_includes_passed_fields(fresh_token: None, isolated_registry: Path) -> None:
    """A subject-only update must NOT send body / recipients keys."""
    del fresh_token, isolated_registry
    route = respx.patch(GRAPH_URL).respond(json={"id": "draft-1"})
    update_draft("draft-1", subject="just-subject")
    sent = json.loads(route.calls.last.request.read())
    assert set(sent.keys()) == {"subject"}


# ---------------------------------------------------------------------
# Validation errors (no Graph call should be made)
# ---------------------------------------------------------------------


def test_update_rejects_empty_draft_id(fresh_token: None, isolated_registry: Path) -> None:
    del fresh_token, isolated_registry
    with pytest.raises(ValueError, match="non-empty draft_id"):
        update_draft("", subject="x")


def test_update_rejects_both_body_kinds(fresh_token: None, isolated_registry: Path) -> None:
    del fresh_token, isolated_registry
    with pytest.raises(ValueError, match="not both"):
        update_draft("draft-1", body="md", body_html="<p>html</p>")


def test_update_rejects_no_change(fresh_token: None, isolated_registry: Path) -> None:
    """Calling update with all None must error — otherwise we'd silently
    no-op a Graph call and confuse the agent."""
    del fresh_token, isolated_registry
    with pytest.raises(ValueError, match="nothing to update"):
        update_draft("draft-1")


# ---------------------------------------------------------------------
# Headers (User-Agent + Bearer)
# ---------------------------------------------------------------------


@respx.mock
def test_update_sends_authorization_and_user_agent(
    fresh_token: None, isolated_registry: Path
) -> None:
    del fresh_token, isolated_registry
    route = respx.patch(GRAPH_URL).respond(json={"id": "draft-1"})
    update_draft("draft-1", subject="X")
    headers = route.calls.last.request.headers
    assert headers["Authorization"] == "Bearer AT"
    assert headers["User-Agent"].startswith("mcp-server-outlook/")
    assert headers["Content-Type"] == "application/json"


# ---------------------------------------------------------------------
# Registry refresh: subject change updates registry; body-only does not
# ---------------------------------------------------------------------


@respx.mock
def test_update_body_only_does_not_change_registry(
    fresh_token: None, isolated_registry: Path
) -> None:
    """Body changes don't surface in ol_status (which only shows
    subject). Avoid pointless registry writes."""
    del fresh_token
    respx.patch(GRAPH_URL).respond(json={"id": "draft-1"})

    before = DraftRegistry(profile="default", base_dir=isolated_registry).get("draft-1")
    update_draft("draft-1", body="new body")
    after = DraftRegistry(profile="default", base_dir=isolated_registry).get("draft-1")

    assert before is not None
    assert after is not None
    # Same subject, same created_at
    assert after.subject == before.subject
    assert after.created_at == before.created_at


# ---------------------------------------------------------------------
# HTTP error propagation
# ---------------------------------------------------------------------


@respx.mock
def test_update_propagates_404(fresh_token: None, isolated_registry: Path) -> None:
    """If the draft was deleted server-side (or never existed), Graph
    returns 404. We propagate so the agent surfaces a clear error."""
    del fresh_token, isolated_registry
    respx.patch(GRAPH_URL).respond(404, json={"error": {"code": "ItemNotFound"}})
    with pytest.raises(httpx.HTTPStatusError):
        update_draft("draft-1", subject="x")


# ---------------------------------------------------------------------
# Attachments (v0.4) — add / remove
# ---------------------------------------------------------------------


@respx.mock
def test_update_add_attachment_no_patch_when_only_attachment_op(
    fresh_token: None, isolated_registry: Path
) -> None:
    """Only attachments to add → no PATCH on the message body, just
    a GET for the return envelope plus the attachment POST."""
    del fresh_token, isolated_registry
    import base64

    patch_route = respx.patch(GRAPH_URL)  # should NOT be called
    respx.get(GRAPH_URL).respond(json={"id": "draft-1", "webLink": "https://outlook.example/x"})
    att_route = respx.post(f"{GRAPH_URL}/attachments").respond(
        201, json={"id": "att-new", "name": "addendum.txt", "size": 4}
    )
    result = update_draft(
        "draft-1",
        add_attachments=[
            {"name": "addendum.txt", "content_bytes_b64": base64.b64encode(b"new!").decode()}
        ],
    )
    assert patch_route.call_count == 0
    assert att_route.call_count == 1
    assert result["added_attachments"] == [{"id": "att-new", "name": "addendum.txt", "size": 4}]


@respx.mock
def test_update_remove_attachment_idempotent(fresh_token: None, isolated_registry: Path) -> None:
    """remove_attachment_ids with a stale id → 404 swallowed; result still returned."""
    del fresh_token, isolated_registry

    respx.get(GRAPH_URL).respond(json={"id": "draft-1", "webLink": "x"})
    respx.delete(f"{GRAPH_URL}/attachments/already-gone").respond(404)
    result = update_draft("draft-1", remove_attachment_ids=["already-gone"])
    assert result["removed_attachment_ids"] == ["already-gone"]


@respx.mock
def test_update_combines_subject_and_attachments(
    fresh_token: None, isolated_registry: Path
) -> None:
    """PATCH subject AND add attachment in one call: both ops fire."""
    del fresh_token, isolated_registry
    import base64

    patch_route = respx.patch(GRAPH_URL).respond(
        json={"id": "draft-1", "subject": "New", "webLink": "x"}
    )
    att_route = respx.post(f"{GRAPH_URL}/attachments").respond(
        201, json={"id": "att-c", "name": "f.bin", "size": 3}
    )
    result = update_draft(
        "draft-1",
        subject="New",
        add_attachments=[{"name": "f.bin", "content_bytes_b64": base64.b64encode(b"abc").decode()}],
    )
    assert patch_route.call_count == 1
    assert att_route.call_count == 1
    assert "added_attachments" in result


def test_update_rejects_no_op_call(fresh_token: None, isolated_registry: Path) -> None:
    """No core field, no attachments → ValueError."""
    del fresh_token, isolated_registry
    with pytest.raises(ValueError, match="nothing to update"):
        update_draft("draft-1")
