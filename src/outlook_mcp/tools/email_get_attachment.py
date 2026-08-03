# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""ol_email_get_attachment — download one file attachment to a local file.

Wraps `GET /me/messages/{message_id}/attachments/{attachment_id}`.
Read-only. The single JSON GET returns the attachment resource with
`name`, `contentType`, `size`, `isInline` and — for a
`fileAttachment` — `contentBytes` (base64 of the raw file). We decode
those bytes and write them to a local file, returning the local path
plus metadata.

Only **file** attachments carry bytes. `itemAttachment` (an embedded
Outlook item) and `referenceAttachment` (a link to a OneDrive /
SharePoint file) have no `contentBytes`; we reject them with a clear
error rather than write an empty file. Reference attachments live in
document storage — reach them with the SharePoint MCP sibling.

The on-disk filename is derived from an **untrusted** source (the
sender picked the attachment name), so it is sanitised to a bare
basename and the resolved path is asserted to stay inside `save_dir`
before any bytes are written — a hostile `../../etc/...` name cannot
escape the download directory.
"""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path
from typing import Any

import httpx

from outlook_mcp.auth import get_token
from outlook_mcp.tools._common import GRAPH_BASE, auth_headers, mailbox_path

FILE_ATTACHMENT_TYPE = "#microsoft.graph.fileAttachment"


class UnsupportedAttachmentTypeError(ValueError):
    """Raised when the attachment is not a downloadable file attachment.

    `itemAttachment` (embedded Outlook item) and `referenceAttachment`
    (cloud-file link) carry no raw bytes in Microsoft Graph, so there is
    nothing to write to disk. Subclass of ValueError so existing
    `except ValueError:` handlers catch it without code changes.
    """


def _safe_filename(candidate: str | None, *, fallback: str) -> str:
    """Reduce an untrusted attachment name to a safe bare filename.

    Strips any directory components (both `/` and `\\`, so a Windows-style
    name can't smuggle a path either), then rejects the traversal
    sentinels (`.`, `..`, empty). Returns `fallback` when nothing usable
    remains. The caller still re-checks the resolved path is inside
    `save_dir` — this is the first of two lines of defence.
    """
    name = (candidate or "").replace("\\", "/").strip()
    # Take the last path segment only — drops any leading directories
    # and absolute-path prefixes.
    name = name.rsplit("/", 1)[-1].strip()
    # Drop NUL and other path-hostile control characters.
    name = name.replace("\x00", "")
    if name in ("", ".", ".."):
        return fallback
    return name


def get_attachment(
    message_id: str,
    attachment_id: str,
    *,
    save_dir: str | None = None,
    filename: str | None = None,
    overwrite: bool = False,
    mailbox: str | None = None,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> dict[str, Any]:
    """Download a single file attachment of a mail to a local file.

    `mailbox=None` (default): the signed-in user's mailbox (`/me/...`).
    `mailbox="<upn>"`: a shared mailbox the signed-in user has
    FullAccess on (`/users/{upn}/...`). The runtime guard that turns
    `mailbox` off when `OUTLOOK_ALLOW_SHARED_MAILBOXES` is unset/false
    lives in the MCP-tool wrapper (server.py), so callers that bypass
    the MCP layer must opt in explicitly via the env var or get a
    Graph-side 403.

    `save_dir=None` (default): a fresh per-call temp directory under the
    OS tmp root (`tempfile.mkdtemp`) — parallel calls never collide and
    no caller-supplied directory is needed for the common case.
    Otherwise the given directory is used (created if missing).

    `filename=None` (default): the attachment's own name, sanitised to a
    bare basename. Pass `filename` to override. Either way the resolved
    target is asserted to stay inside `save_dir`.

    `overwrite=False` (default): refuse to clobber an existing target
    file (`FileExistsError`). Pass `overwrite=True` to replace it.

    Returns a dict with: path (absolute local path written), name (Graph
    attachment name), content_type, size (bytes written), attachment_id,
    message_id, mailbox (echoed), is_inline.

    Raises:
        ValueError: empty message_id / attachment_id, or empty `mailbox`
            (non-None but whitespace-only).
        UnsupportedAttachmentTypeError: the attachment is an item- or
            reference-attachment (no downloadable bytes).
        FileExistsError: target exists and `overwrite=False`.
        httpx.HTTPStatusError: 404 if the message/attachment doesn't
            exist or is not visible; 403 if `mailbox` is set but the
            signed-in user has no FullAccess on it; other non-2xx
            propagate.
        outlook_mcp.auth.AuthRequiredError: no cached token.
    """
    if not message_id or not message_id.strip():
        raise ValueError("ol_email_get_attachment requires a non-empty message_id")
    if not attachment_id or not attachment_id.strip():
        raise ValueError("ol_email_get_attachment requires a non-empty attachment_id")

    box = mailbox_path(mailbox)
    token = get_token(profile)
    headers = auth_headers(token)
    client = http if http is not None else httpx.Client(timeout=60.0)
    try:
        response = client.get(
            f"{GRAPH_BASE}/{box}/messages/{message_id}/attachments/{attachment_id}",
            headers=headers,
        )
        response.raise_for_status()
        attachment = response.json()
    finally:
        if http is None:
            client.close()

    odata_type = attachment.get("@odata.type")
    if odata_type != FILE_ATTACHMENT_TYPE:
        raise UnsupportedAttachmentTypeError(
            f"attachment {attachment_id!r} is a {odata_type or 'non-file attachment'}, "
            "which carries no downloadable bytes. Only file attachments "
            f"({FILE_ATTACHMENT_TYPE}) can be downloaded. Embedded Outlook items and "
            "reference (cloud-file) attachments are out of scope — a reference "
            "attachment points at a OneDrive/SharePoint file, reachable via the "
            "SharePoint MCP server."
        )

    content_bytes_b64 = attachment.get("contentBytes")
    if not isinstance(content_bytes_b64, str):
        raise ValueError(
            f"attachment {attachment_id!r}: Graph returned a fileAttachment without "
            "contentBytes — cannot download."
        )
    try:
        data = base64.b64decode(content_bytes_b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"attachment {attachment_id!r}: contentBytes is not valid base64: {exc}",
        ) from exc

    name = attachment.get("name")
    safe_name = _safe_filename(
        filename if filename is not None else name,
        fallback=f"attachment-{attachment_id[:16]}",
    )

    if save_dir is None:
        directory = Path(tempfile.mkdtemp(prefix="outlook-mcp-att-"))
    else:
        directory = Path(save_dir).expanduser()
        directory.mkdir(parents=True, exist_ok=True)
    directory = directory.resolve()

    target = (directory / safe_name).resolve()
    # Second line of defence: the resolved target must stay inside the
    # resolved download directory. Guards against any residual traversal
    # the basename reduction missed (symlinks, exotic encodings).
    if directory != target.parent:
        raise ValueError(
            f"refusing to write attachment outside the download directory "
            f"(resolved target {str(target)!r} escapes {str(directory)!r})"
        )

    if target.exists() and not overwrite:
        raise FileExistsError(
            f"{str(target)!r} already exists; pass overwrite=True to replace it "
            "or choose a different save_dir / filename."
        )

    target.write_bytes(data)

    return {
        "path": str(target),
        "name": name,
        "content_type": attachment.get("contentType"),
        # `size` is the number of bytes actually written to disk (the
        # decoded length). Microsoft Graph's own `size` field is the
        # attachment's *stored* size (includes MIME/base64 overhead) and
        # therefore does NOT equal the decoded byte count — it is echoed
        # separately as `graph_size` so callers can see both without
        # conflating them.
        "size": len(data),
        "graph_size": attachment.get("size"),
        "attachment_id": attachment.get("id", attachment_id),
        "message_id": message_id,
        "mailbox": mailbox,
        "is_inline": bool(attachment.get("isInline", False)),
    }
