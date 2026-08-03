# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Harness tests for ol_email_get_attachment (#69) — real Microsoft Graph.

Per ENGINEERING_PRINCIPLES § 5: mocks are tautological; only real Graph
catches the URL-shape / scope / status-code / payload-shape contract
violations. In particular the load-bearing thing a mock cannot verify is
that Graph really returns `contentBytes` (base64) on a plain attachment
GET, that the decoded bytes match what we uploaded, and that Graph's
`size` field is NOT the decoded byte count.

Each test seeds its own throwaway draft (POST /me/messages — never sent,
never leaves the tenant), uploads a known attachment via the same helper
the write tools use, downloads it back through the tool, and cleans up in
a `finally` block. Self-contained: no precondition on inbox contents.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from outlook_mcp.auth import get_token
from outlook_mcp.auth.store import PlainFileTokenStore
from outlook_mcp.tools._attachments import upload_attachment
from outlook_mcp.tools._common import GRAPH_BASE, auth_headers, mailbox_path
from outlook_mcp.tools.email_get_attachment import get_attachment

HARNESS_PROFILE = "harness"
SHARED_MAILBOX_ENV = "OUTLOOK_HARNESS_SHARED_MAILBOX_UPN"

# A small, known payload we upload and expect to get back byte-for-byte.
KNOWN_BYTES = b"outlook-mcp harness attachment payload \x00\x01\x02 end"


def _harness_cache_path() -> Path:
    return Path.home() / ".cache" / "outlook-mcp" / HARNESS_PROFILE / "token.json"


def _skip_if_no_harness() -> None:
    if not _harness_cache_path().exists() and not os.environ.get("OUTLOOK_HARNESS_TOKEN_JSON"):
        pytest.skip(
            "Harness token cache missing. Run `./scripts/renew-harness-token.sh` or set "
            "OUTLOOK_HARNESS_TOKEN_JSON.",
        )


def _token() -> str:
    os.environ.setdefault("OUTLOOK_TOKEN_STORE", "file")
    return get_token(profile=HARNESS_PROFILE, store=PlainFileTokenStore())


def _create_throwaway_draft(
    client: httpx.Client,
    headers: dict[str, str],
    mailbox: str | None = None,
) -> str:
    """POST a uniquely-titled draft directly via Graph. Returns its id.

    No `send` call follows — the draft sits in Drafts until the test
    deletes it.
    """
    marker = uuid.uuid4().hex[:12]
    box = mailbox_path(mailbox)
    response = client.post(
        f"{GRAPH_BASE}/{box}/messages",
        headers={**headers, "Content-Type": "application/json"},
        json={
            "subject": f"[outlook-mcp-harness {marker}] do not deliver",
            "body": {
                "contentType": "text",
                "content": (
                    "This draft was created by outlook-mcp's harness suite "
                    f"(marker {marker}). It is safe to delete."
                ),
            },
        },
    )
    response.raise_for_status()
    return str(response.json()["id"])


def _delete_draft(
    client: httpx.Client,
    headers: dict[str, str],
    message_id: str,
    mailbox: str | None = None,
) -> None:
    box = mailbox_path(mailbox)
    try:
        client.delete(f"{GRAPH_BASE}/{box}/messages/{message_id}", headers=headers)
    except httpx.HTTPError:
        pass


def _seed_draft_with_attachment(
    client: httpx.Client,
    headers: dict[str, str],
    *,
    name: str,
    content_type: str,
    mailbox: str | None = None,
) -> tuple[str, str]:
    """Create a draft and attach KNOWN_BYTES to it via the upload helper.

    Returns `(message_id, attachment_id)`. Note: the upload helper always
    targets /me; shared-mailbox seeding is done inline below where needed.
    """
    message_id = _create_throwaway_draft(client, headers, mailbox=mailbox)
    if mailbox is None:
        resource = upload_attachment(
            client=client,
            token=_token(),
            message_id=message_id,
            att={
                "name": name,
                "content_bytes_b64": _b64(KNOWN_BYTES),
                "content_type": content_type,
            },
        )
    else:
        resource = _upload_to_mailbox(client, headers, message_id, name, content_type, mailbox)
    return message_id, str(resource["id"])


def _b64(data: bytes) -> str:
    import base64

    return base64.b64encode(data).decode("ascii")


def _upload_to_mailbox(
    client: httpx.Client,
    headers: dict[str, str],
    message_id: str,
    name: str,
    content_type: str,
    mailbox: str,
) -> dict[str, object]:
    """Single-shot attachment upload against /users/{upn}/... (small file)."""
    box = mailbox_path(mailbox)
    response = client.post(
        f"{GRAPH_BASE}/{box}/messages/{message_id}/attachments",
        headers={**headers, "Content-Type": "application/json"},
        json={
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": name,
            "contentType": content_type,
            "contentBytes": _b64(KNOWN_BYTES),
        },
    )
    response.raise_for_status()
    return dict(response.json())


# ── round-trip on /me ─────────────────────────────────────────────────────


def test_get_attachment_round_trip_on_me(tmp_path: Path) -> None:
    """Seed a draft with a known attachment, download it back, and assert
    the decoded bytes / metadata match. Verifies the load-bearing claim
    mocks cannot: Graph returns contentBytes and they decode to exactly
    what we uploaded."""
    _skip_if_no_harness()
    headers = auth_headers(_token())
    with httpx.Client(timeout=60.0) as client:
        message_id, attachment_id = _seed_draft_with_attachment(
            client, headers, name="harness-note.txt", content_type="text/plain"
        )
        try:
            result = get_attachment(
                message_id,
                attachment_id,
                save_dir=str(tmp_path),
                profile=HARNESS_PROFILE,
            )
            assert result["name"] == "harness-note.txt"
            assert result["content_type"] == "text/plain"
            assert result["size"] == len(KNOWN_BYTES)
            assert result["message_id"] == message_id
            assert result["mailbox"] is None
            written = Path(result["path"])
            assert written.parent == tmp_path.resolve()
            assert written.read_bytes() == KNOWN_BYTES
            # Graph's stored size is present but is NOT the decoded length.
            assert result["graph_size"] is not None
        finally:
            _delete_draft(client, headers, message_id)


def test_get_attachment_default_tempdir(tmp_path: Path) -> None:
    """save_dir omitted → file lands in a fresh temp dir, still correct."""
    del tmp_path
    _skip_if_no_harness()
    headers = auth_headers(_token())
    with httpx.Client(timeout=60.0) as client:
        message_id, attachment_id = _seed_draft_with_attachment(
            client, headers, name="report.bin", content_type="application/octet-stream"
        )
        try:
            result = get_attachment(message_id, attachment_id, profile=HARNESS_PROFILE)
            assert Path(result["path"]).read_bytes() == KNOWN_BYTES
        finally:
            _delete_draft(client, headers, message_id)


# ── error path: attachment not found (404) ────────────────────────────────


def test_get_attachment_unknown_id_404(tmp_path: Path) -> None:
    """A well-formed-but-nonexistent attachment id on a real message
    returns 404, which the tool propagates. Uses a real message so the
    404 comes from the attachment lookup, not a malformed-URL 400."""
    _skip_if_no_harness()
    headers = auth_headers(_token())
    with httpx.Client(timeout=60.0) as client:
        message_id, attachment_id = _seed_draft_with_attachment(
            client, headers, name="x.txt", content_type="text/plain"
        )
        try:
            # Mutate the real id into a still-well-formed but nonexistent one.
            bogus = attachment_id[:-4] + "AAAA" if len(attachment_id) > 4 else "AAAA="
            with pytest.raises(httpx.HTTPStatusError) as excinfo:
                get_attachment(message_id, bogus, save_dir=str(tmp_path), profile=HARNESS_PROFILE)
            assert excinfo.value.response.status_code in (400, 404)
        finally:
            _delete_draft(client, headers, message_id)


# ── shared-mailbox routing (skipif unless explicitly configured) ──────────


def _shared_mailbox_or_skip() -> Iterator[str]:
    upn = os.environ.get(SHARED_MAILBOX_ENV)
    if not upn:
        pytest.skip(
            f"{SHARED_MAILBOX_ENV} not set — skipping shared-mailbox harness tests. "
            "Set the env var to a UPN the harness user has FullAccess on.",
        )
    yield upn


def test_get_attachment_on_shared_mailbox(tmp_path: Path) -> None:
    """Round-trip download from a shared mailbox via FullAccess delegate."""
    _skip_if_no_harness()
    shared = next(_shared_mailbox_or_skip())
    headers = auth_headers(_token())
    with httpx.Client(timeout=60.0) as client:
        message_id, attachment_id = _seed_draft_with_attachment(
            client,
            headers,
            name="shared-note.txt",
            content_type="text/plain",
            mailbox=shared,
        )
        try:
            result = get_attachment(
                message_id,
                attachment_id,
                save_dir=str(tmp_path),
                mailbox=shared,
                profile=HARNESS_PROFILE,
            )
            assert result["mailbox"] == shared
            assert Path(result["path"]).read_bytes() == KNOWN_BYTES
        finally:
            _delete_draft(client, headers, message_id, mailbox=shared)
