# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Attachment-handling helpers for `ol_email_create_draft` /
`ol_email_update_draft`.

Microsoft Graph offers two attachment-upload paths:

- **Single-shot POST** (`POST /me/messages/{id}/attachments`) — works
  up to ~3 MB raw content. Encodes the bytes as base64 inside the
  JSON payload.
- **Resumable upload session** (`POST /me/messages/{id}/attachments/
  createUploadSession` → chunked `PUT` to the returned uploadUrl) —
  required above ~3 MB; works up to the mailbox's per-message size
  limit (typically 150 MB).

This module abstracts both paths behind a single `upload_attachment`
function that picks the right path from the content length. Callers
supply an `Attachment` dict; we validate it, load the content from
its declared source (`content_path` / `content_bytes_b64` /
`content_url`), then upload.

Content sources are mutually exclusive: exactly one must be set per
attachment. The schema is enforced before any HTTP call.
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

import httpx

from outlook_mcp.tools._common import GRAPH_BASE, auth_headers

# 3 MiB threshold — Graph's documented limit for the single-shot
# POST. Above this we MUST use createUploadSession + chunked PUT.
SINGLE_SHOT_LIMIT_BYTES = 3 * 1024 * 1024

# Chunk size for resumable uploads. Graph recommends 4-10 MiB chunks
# aligned to 320 KiB boundaries (327680). 8 MiB = 25 x 320 KiB.
CHUNK_SIZE_BYTES = 8 * 1024 * 1024


class AttachmentSchemaError(ValueError):
    """Raised when an Attachment dict is malformed — wrong shape,
    missing required field, conflicting content sources, etc.

    Subclass of ValueError so existing `except ValueError:` blocks
    catch it without code changes."""


def validate_attachment(att: Any, index: int = 0) -> dict[str, Any]:
    """Validate a single Attachment dict before any HTTP work.

    Returns the dict on success (unchanged). Raises
    `AttachmentSchemaError` with `index` baked into the message so
    multi-attachment lists pinpoint the offender.

    Schema: `{name: str, content_path|content_bytes_b64|content_url:
    str, content_type?: str}`. Exactly one of the three content
    sources must be present.
    """
    prefix = f"attachments[{index}]"
    if not isinstance(att, dict):
        raise AttachmentSchemaError(f"{prefix}: must be a dict, got {type(att).__name__}")
    name = att.get("name")
    if not isinstance(name, str) or not name.strip():
        raise AttachmentSchemaError(f"{prefix}: `name` must be a non-empty string")
    sources = [k for k in ("content_path", "content_bytes_b64", "content_url") if k in att]
    if len(sources) != 1:
        raise AttachmentSchemaError(
            f"{prefix}: exactly one of `content_path`, `content_bytes_b64`, "
            f"`content_url` must be set (got: {sources or '(none)'})",
        )
    src_key = sources[0]
    src_value = att[src_key]
    if not isinstance(src_value, str) or not src_value:
        raise AttachmentSchemaError(
            f"{prefix}: `{src_key}` must be a non-empty string",
        )
    content_type = att.get("content_type")
    if content_type is not None and not isinstance(content_type, str):
        raise AttachmentSchemaError(
            f"{prefix}: `content_type`, when given, must be a string",
        )
    return att


def load_attachment_bytes(
    att: dict[str, Any],
    *,
    http: httpx.Client | None = None,
) -> tuple[bytes, str]:
    """Resolve an Attachment's content source to raw bytes + content type.

    Returns `(content_bytes, content_type)`. Content type is taken
    from the explicit `content_type` field if present, else inferred
    from the filename's extension via the stdlib `mimetypes` module,
    else falls back to `application/octet-stream`.

    Raises:
        AttachmentSchemaError: malformed Attachment (wraps as expected).
        FileNotFoundError / IsADirectoryError: `content_path` doesn't
            point at a readable file.
        ValueError: `content_bytes_b64` is not valid base64.
        httpx.HTTPStatusError: `content_url` fetch failed.
    """
    name = att["name"]
    if "content_path" in att:
        path = Path(att["content_path"]).expanduser()
        data = path.read_bytes()
    elif "content_bytes_b64" in att:
        try:
            data = base64.b64decode(att["content_bytes_b64"], validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"attachment {name!r}: content_bytes_b64 is not valid base64: {exc}",
            ) from exc
    else:
        # content_url
        url = att["content_url"]
        client = http if http is not None else httpx.Client(timeout=60.0)
        try:
            response = client.get(url)
            response.raise_for_status()
            data = response.content
        finally:
            if http is None:
                client.close()

    content_type = att.get("content_type")
    if not content_type:
        guessed, _ = mimetypes.guess_type(name)
        content_type = guessed or "application/octet-stream"
    return data, content_type


def upload_attachment(
    *,
    client: httpx.Client,
    token: str,
    message_id: str,
    att: dict[str, Any],
) -> dict[str, Any]:
    """Upload one attachment to an existing draft. Picks single-shot
    vs resumable based on content size.

    Returns the Graph attachment resource (dict with `id`, `name`,
    `size`, `contentType`, ...). The `id` is used by
    `ol_email_update_draft(remove_attachment_ids=[...])` to remove it
    later.
    """
    content_bytes, content_type = load_attachment_bytes(att, http=client)
    if len(content_bytes) <= SINGLE_SHOT_LIMIT_BYTES:
        return _upload_single_shot(
            client=client,
            token=token,
            message_id=message_id,
            name=att["name"],
            content_bytes=content_bytes,
            content_type=content_type,
        )
    return _upload_resumable(
        client=client,
        token=token,
        message_id=message_id,
        name=att["name"],
        content_bytes=content_bytes,
        content_type=content_type,
    )


def _upload_single_shot(
    *,
    client: httpx.Client,
    token: str,
    message_id: str,
    name: str,
    content_bytes: bytes,
    content_type: str,
) -> dict[str, Any]:
    """POST /me/messages/{id}/attachments with base64 inline."""
    payload = {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": name,
        "contentType": content_type,
        "contentBytes": base64.b64encode(content_bytes).decode("ascii"),
    }
    response = client.post(
        f"{GRAPH_BASE}/me/messages/{message_id}/attachments",
        headers={**auth_headers(token), "Content-Type": "application/json"},
        json=payload,
    )
    response.raise_for_status()
    result: dict[str, Any] = response.json()
    return result


def _upload_resumable(
    *,
    client: httpx.Client,
    token: str,
    message_id: str,
    name: str,
    content_bytes: bytes,
    content_type: str,
) -> dict[str, Any]:
    """POST createUploadSession then PUT the content in chunks.

    Graph's contract: each chunked PUT carries `Content-Range:
    bytes <start>-<end>/<total>` and `Content-Length` for the chunk.
    The final chunk's response is a 201/200 with the attachment
    resource body (or a Location header pointing at it). 2xx without
    a body means the upload is accepted but not yet committed —
    keep PUT-ing until the final one returns the resource.
    """
    total = len(content_bytes)
    session_response = client.post(
        f"{GRAPH_BASE}/me/messages/{message_id}/attachments/createUploadSession",
        headers={**auth_headers(token), "Content-Type": "application/json"},
        json={
            "AttachmentItem": {
                "attachmentType": "file",
                "name": name,
                "size": total,
                "contentType": content_type,
            }
        },
    )
    session_response.raise_for_status()
    upload_url = session_response.json()["uploadUrl"]

    offset = 0
    final_body: dict[str, Any] | None = None
    while offset < total:
        end = min(offset + CHUNK_SIZE_BYTES, total) - 1
        chunk = content_bytes[offset : end + 1]
        # The upload-session endpoint is pre-authenticated via the URL
        # token; we MUST NOT send our Authorization header to it.
        put_response = client.put(
            upload_url,
            headers={
                "Content-Range": f"bytes {offset}-{end}/{total}",
                "Content-Length": str(len(chunk)),
            },
            content=chunk,
        )
        put_response.raise_for_status()
        offset = end + 1
        if offset >= total:
            try:
                final_body = put_response.json()
            except ValueError:
                final_body = None

    if final_body is None:
        # Graph returned 2xx without a body on the final chunk; fetch
        # the attachment list to find the one we just uploaded by name.
        list_response = client.get(
            f"{GRAPH_BASE}/me/messages/{message_id}/attachments",
            headers=auth_headers(token),
        )
        list_response.raise_for_status()
        candidates = [a for a in list_response.json().get("value", []) if a.get("name") == name]
        if not candidates:
            raise RuntimeError(
                f"attachment {name!r}: upload completed but Graph doesn't show it on the draft",
            )
        # Take the most recently created if multiple match (rare).
        final_body = candidates[-1]
    return final_body


def attach_to_draft(
    *,
    client: httpx.Client,
    token: str,
    message_id: str,
    attachments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate then upload each attachment in `attachments`.

    Validation happens for all attachments BEFORE any upload starts —
    a malformed third entry causes the function to raise without
    leaving partial uploads from the first two. Returns the list of
    Graph attachment resources in the same order.
    """
    for index, att in enumerate(attachments):
        validate_attachment(att, index=index)
    return [
        upload_attachment(client=client, token=token, message_id=message_id, att=att)
        for att in attachments
    ]


def remove_attachments(
    *,
    client: httpx.Client,
    token: str,
    message_id: str,
    attachment_ids: list[str],
) -> None:
    """DELETE one or more attachments from an existing draft.

    Idempotent on 404 (already gone) — silently swallowed. Any
    other 4xx/5xx propagates so the caller sees the failure.
    """
    for att_id in attachment_ids:
        response = client.delete(
            f"{GRAPH_BASE}/me/messages/{message_id}/attachments/{att_id}",
            headers=auth_headers(token),
        )
        if response.status_code == 404:
            continue
        response.raise_for_status()
