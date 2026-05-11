# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for `outlook_mcp.tools._attachments`.

Covers schema validation, content loading (path / b64 / url),
single-shot vs resumable upload-path selection, and remove-attachment
idempotence."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest
import respx

from outlook_mcp.tools._attachments import (
    SINGLE_SHOT_LIMIT_BYTES,
    AttachmentSchemaError,
    attach_to_draft,
    load_attachment_bytes,
    remove_attachments,
    upload_attachment,
    validate_attachment,
)

GRAPH = "https://graph.microsoft.com/v1.0"
MSG_ID = "AAMkAGI2THISISATESTDRAFTID"


# ---------------------------------------------------------------------
# validate_attachment — schema rules
# ---------------------------------------------------------------------


def test_validate_accepts_path_form() -> None:
    validate_attachment({"name": "spec.pdf", "content_path": "/tmp/spec.pdf"})


def test_validate_accepts_b64_form() -> None:
    validate_attachment({"name": "x.bin", "content_bytes_b64": "AAAA"})


def test_validate_accepts_url_form() -> None:
    validate_attachment({"name": "logo.png", "content_url": "https://example.com/logo.png"})


def test_validate_accepts_explicit_content_type() -> None:
    validate_attachment(
        {"name": "x.bin", "content_path": "/tmp/x", "content_type": "application/octet-stream"},
    )


def test_validate_rejects_non_dict() -> None:
    with pytest.raises(AttachmentSchemaError, match="must be a dict"):
        validate_attachment("not-a-dict", index=2)


def test_validate_rejects_missing_name() -> None:
    with pytest.raises(AttachmentSchemaError, match="`name` must be"):
        validate_attachment({"content_path": "/tmp/x"})


def test_validate_rejects_empty_name() -> None:
    with pytest.raises(AttachmentSchemaError, match="`name` must be"):
        validate_attachment({"name": "  ", "content_path": "/tmp/x"})


def test_validate_rejects_zero_sources() -> None:
    with pytest.raises(AttachmentSchemaError, match="exactly one of"):
        validate_attachment({"name": "x"})


def test_validate_rejects_two_sources() -> None:
    with pytest.raises(AttachmentSchemaError, match="exactly one of"):
        validate_attachment(
            {"name": "x", "content_path": "/tmp/x", "content_bytes_b64": "AAAA"},
        )


def test_validate_rejects_three_sources() -> None:
    with pytest.raises(AttachmentSchemaError, match="exactly one of"):
        validate_attachment(
            {
                "name": "x",
                "content_path": "/tmp/x",
                "content_bytes_b64": "AAAA",
                "content_url": "https://example.com/x",
            },
        )


def test_validate_rejects_empty_source_value() -> None:
    with pytest.raises(AttachmentSchemaError, match="must be a non-empty string"):
        validate_attachment({"name": "x", "content_path": ""})


def test_validate_index_pinpoints_offender() -> None:
    """Multi-attachment lists: the error message points at the bad entry."""
    with pytest.raises(AttachmentSchemaError, match=r"attachments\[3\]"):
        validate_attachment({"name": "x"}, index=3)


# ---------------------------------------------------------------------
# load_attachment_bytes — three content sources
# ---------------------------------------------------------------------


def test_load_from_path(tmp_path: Path) -> None:
    p = tmp_path / "spec.txt"
    p.write_bytes(b"hello, world")
    data, ctype = load_attachment_bytes({"name": "spec.txt", "content_path": str(p)})
    assert data == b"hello, world"
    assert ctype == "text/plain"


def test_load_from_b64() -> None:
    raw = b"\x00\x01\x02hello"
    encoded = base64.b64encode(raw).decode("ascii")
    data, ctype = load_attachment_bytes(
        {"name": "x.bin", "content_bytes_b64": encoded},
    )
    assert data == raw
    assert ctype == "application/octet-stream"


def test_load_from_b64_invalid_raises() -> None:
    with pytest.raises(ValueError, match="not valid base64"):
        load_attachment_bytes({"name": "x.bin", "content_bytes_b64": "!!! not base64 !!!"})


@respx.mock
def test_load_from_url() -> None:
    respx.get("https://example.com/logo.png").respond(content=b"PNG-bytes")
    data, ctype = load_attachment_bytes(
        {"name": "logo.png", "content_url": "https://example.com/logo.png"},
    )
    assert data == b"PNG-bytes"
    assert ctype == "image/png"


def test_load_explicit_content_type_wins() -> None:
    """If `content_type` is set, it takes precedence over inference."""
    raw = b"abc"
    encoded = base64.b64encode(raw).decode("ascii")
    data, ctype = load_attachment_bytes(
        {"name": "x.txt", "content_bytes_b64": encoded, "content_type": "application/x-special"},
    )
    assert data == raw
    assert ctype == "application/x-special"


# ---------------------------------------------------------------------
# upload_attachment — single-shot vs resumable path selection
# ---------------------------------------------------------------------


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


@respx.mock
def test_small_file_uses_single_shot() -> None:
    small = b"x" * 1024  # 1 KiB
    att = {"name": "small.bin", "content_bytes_b64": _b64(small)}
    route = respx.post(f"{GRAPH}/me/messages/{MSG_ID}/attachments").respond(
        201,
        json={
            "id": "att-1",
            "name": "small.bin",
            "size": len(small),
            "contentType": "application/octet-stream",
        },
    )
    with httpx.Client() as client:
        result = upload_attachment(client=client, token="AT", message_id=MSG_ID, att=att)
    assert result["id"] == "att-1"
    assert route.call_count == 1
    sent = json.loads(route.calls.last.request.read())
    assert sent["@odata.type"] == "#microsoft.graph.fileAttachment"
    assert sent["contentBytes"] == _b64(small)


@respx.mock
def test_large_file_uses_resumable_session() -> None:
    """File above SINGLE_SHOT_LIMIT_BYTES: createUploadSession + chunked PUT."""
    big = b"y" * (SINGLE_SHOT_LIMIT_BYTES + 1024)
    att = {"name": "big.bin", "content_bytes_b64": _b64(big)}
    session_route = respx.post(
        f"{GRAPH}/me/messages/{MSG_ID}/attachments/createUploadSession"
    ).respond(
        json={
            "uploadUrl": "https://upload.example.com/sess123",
            "expirationDateTime": "2099-01-01T00:00:00Z",
        },
    )
    put_route = respx.put("https://upload.example.com/sess123").respond(
        201,
        json={
            "id": "att-big",
            "name": "big.bin",
            "size": len(big),
            "contentType": "application/octet-stream",
        },
    )
    with httpx.Client() as client:
        result = upload_attachment(client=client, token="AT", message_id=MSG_ID, att=att)
    assert result["id"] == "att-big"
    assert session_route.call_count == 1
    assert put_route.call_count >= 1
    sent_payload = json.loads(session_route.calls.last.request.read())
    assert sent_payload["AttachmentItem"]["size"] == len(big)
    # No Authorization header on the upload PUT (URL is pre-authenticated).
    assert "Authorization" not in put_route.calls.last.request.headers


@respx.mock
def test_resumable_with_204_no_body_fetches_attachment_list() -> None:
    """Some Graph responses return 2xx with no body — fallback to GET."""
    big = b"z" * (SINGLE_SHOT_LIMIT_BYTES + 100)
    att = {"name": "report.dat", "content_bytes_b64": _b64(big)}
    respx.post(f"{GRAPH}/me/messages/{MSG_ID}/attachments/createUploadSession").respond(
        json={"uploadUrl": "https://upload.example.com/sess-noresp", "expirationDateTime": "x"},
    )
    respx.put("https://upload.example.com/sess-noresp").respond(204)
    respx.get(f"{GRAPH}/me/messages/{MSG_ID}/attachments").respond(
        json={"value": [{"id": "att-fetched", "name": "report.dat", "size": len(big)}]},
    )
    with httpx.Client() as client:
        result = upload_attachment(client=client, token="AT", message_id=MSG_ID, att=att)
    assert result["id"] == "att-fetched"


# ---------------------------------------------------------------------
# attach_to_draft — schema-validates all before any upload
# ---------------------------------------------------------------------


def test_attach_to_draft_validates_all_before_uploading() -> None:
    """If the third attachment is malformed, none of the first two upload."""
    with respx.mock:
        # If validation runs FIRST (as it must), this route is never hit.
        route = respx.post(f"{GRAPH}/me/messages/{MSG_ID}/attachments")
        atts = [
            {"name": "a.txt", "content_bytes_b64": _b64(b"a")},
            {"name": "b.txt", "content_bytes_b64": _b64(b"b")},
            {"name": "bad"},  # malformed — no content source
        ]
        with httpx.Client() as client:
            with pytest.raises(AttachmentSchemaError, match=r"\[2\]"):
                attach_to_draft(
                    client=client,
                    token="AT",
                    message_id=MSG_ID,
                    attachments=atts,
                )
        assert route.call_count == 0


# ---------------------------------------------------------------------
# remove_attachments — idempotent on 404
# ---------------------------------------------------------------------


@respx.mock
def test_remove_attachments_idempotent_on_404() -> None:
    respx.delete(f"{GRAPH}/me/messages/{MSG_ID}/attachments/already-gone").respond(404)
    respx.delete(f"{GRAPH}/me/messages/{MSG_ID}/attachments/exists").respond(204)
    with httpx.Client() as client:
        remove_attachments(
            client=client,
            token="AT",
            message_id=MSG_ID,
            attachment_ids=["already-gone", "exists"],
        )  # no exception


@respx.mock
def test_remove_attachments_propagates_other_errors() -> None:
    respx.delete(f"{GRAPH}/me/messages/{MSG_ID}/attachments/forbidden").respond(403)
    with httpx.Client() as client:
        with pytest.raises(httpx.HTTPStatusError):
            remove_attachments(
                client=client,
                token="AT",
                message_id=MSG_ID,
                attachment_ids=["forbidden"],
            )
