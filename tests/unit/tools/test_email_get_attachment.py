# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for ol_email_get_attachment (#69).

Covers:

- Happy-path download to a default temp dir and to an explicit save_dir.
- `size` (decoded bytes written) vs `graph_size` (Graph's stored size).
- Shared-mailbox routing (/me vs /users/{upn}) with call-count assertions.
- The request carries NO bytes-excluding $select (so contentBytes comes back).
- Filename sanitisation / path-traversal refusal.
- overwrite guard.
- itemAttachment / referenceAttachment rejection.
- fileAttachment without contentBytes, and invalid base64.
- 403 / 404 propagate; empty message_id / attachment_id / mailbox rejected.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path

import httpx
import pytest
import respx

from outlook_mcp.auth import get_token
from outlook_mcp.auth.tokens import CachedToken
from outlook_mcp.tools.email_get_attachment import (
    UnsupportedAttachmentTypeError,
    get_attachment,
)

GRAPH = "https://graph.microsoft.com/v1.0"
ATT_URL = f"{GRAPH}/me/messages/m1/attachments/att1"
SHARED_ATT_URL = f"{GRAPH}/users/sekretariat@xmv.de/messages/m1/attachments/att1"

RAW_BYTES = b"hello, this is a small file"
B64 = base64.b64encode(RAW_BYTES).decode("ascii")


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
        "outlook_mcp.tools.email_get_attachment.get_token",
        lambda profile="default": get_token(profile=profile, store=store),
    )


def _file_attachment(
    *,
    name: str = "report.pdf",
    content_type: str = "application/pdf",
    b64: str = B64,
    size: int = 4242,
    is_inline: bool = False,
    include_content: bool = True,
) -> dict[str, object]:
    body: dict[str, object] = {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "id": "att1",
        "name": name,
        "contentType": content_type,
        "size": size,
        "isInline": is_inline,
    }
    if include_content:
        body["contentBytes"] = b64
    return body


# ── happy path ────────────────────────────────────────────────────────────


@respx.mock
def test_download_to_default_tempdir(fresh_token: None, tmp_path: Path) -> None:
    del fresh_token
    del tmp_path
    respx.get(ATT_URL).respond(json=_file_attachment())

    result = get_attachment("m1", "att1")

    written = Path(result["path"])
    assert written.exists()
    assert written.read_bytes() == RAW_BYTES
    assert written.name == "report.pdf"
    assert result["name"] == "report.pdf"
    assert result["content_type"] == "application/pdf"
    assert result["attachment_id"] == "att1"
    assert result["message_id"] == "m1"
    assert result["mailbox"] is None
    assert result["is_inline"] is False


@respx.mock
def test_download_to_explicit_save_dir(fresh_token: None, tmp_path: Path) -> None:
    del fresh_token
    respx.get(ATT_URL).respond(json=_file_attachment())

    result = get_attachment("m1", "att1", save_dir=str(tmp_path))

    assert Path(result["path"]).parent == tmp_path.resolve()
    assert Path(result["path"]).read_bytes() == RAW_BYTES


@respx.mock
def test_size_is_decoded_length_not_graph_size(fresh_token: None, tmp_path: Path) -> None:
    """`size` == bytes written (decoded); `graph_size` == Graph's stored
    size. They intentionally differ — Graph's includes encoding overhead."""
    del fresh_token
    respx.get(ATT_URL).respond(json=_file_attachment(size=9999))

    result = get_attachment("m1", "att1", save_dir=str(tmp_path))

    assert result["size"] == len(RAW_BYTES)
    assert result["graph_size"] == 9999
    assert result["size"] != result["graph_size"]


@respx.mock
def test_explicit_filename_override(fresh_token: None, tmp_path: Path) -> None:
    del fresh_token
    respx.get(ATT_URL).respond(json=_file_attachment())

    result = get_attachment("m1", "att1", save_dir=str(tmp_path), filename="renamed.bin")

    assert Path(result["path"]).name == "renamed.bin"
    assert Path(result["path"]).read_bytes() == RAW_BYTES


@respx.mock
def test_request_has_no_bytes_excluding_select(fresh_token: None, tmp_path: Path) -> None:
    """Regression guard: the GET must NOT carry a $select that omits
    contentBytes — that would silently return metadata with no bytes."""
    del fresh_token
    route = respx.get(ATT_URL).respond(json=_file_attachment())

    get_attachment("m1", "att1", save_dir=str(tmp_path))

    assert route.calls.call_count == 1
    request_url = str(route.calls.last.request.url)
    assert "$select" not in request_url


# ── shared-mailbox routing ────────────────────────────────────────────────


@respx.mock
def test_targets_shared_mailbox_when_mailbox_set(fresh_token: None, tmp_path: Path) -> None:
    del fresh_token
    me_route = respx.get(ATT_URL).respond(json=_file_attachment())
    shared_route = respx.get(SHARED_ATT_URL).respond(json=_file_attachment())

    result = get_attachment("m1", "att1", save_dir=str(tmp_path), mailbox="sekretariat@xmv.de")

    assert me_route.calls.call_count == 0
    assert shared_route.calls.call_count == 1
    assert result["mailbox"] == "sekretariat@xmv.de"


# ── attachment-type rejection ─────────────────────────────────────────────


@respx.mock
def test_item_attachment_rejected(fresh_token: None, tmp_path: Path) -> None:
    del fresh_token
    respx.get(ATT_URL).respond(
        json={
            "@odata.type": "#microsoft.graph.itemAttachment",
            "id": "att1",
            "name": "Embedded mail",
        }
    )
    with pytest.raises(UnsupportedAttachmentTypeError, match="itemAttachment"):
        get_attachment("m1", "att1", save_dir=str(tmp_path))


@respx.mock
def test_reference_attachment_rejected(fresh_token: None, tmp_path: Path) -> None:
    del fresh_token
    respx.get(ATT_URL).respond(
        json={
            "@odata.type": "#microsoft.graph.referenceAttachment",
            "id": "att1",
            "name": "OneDrive link",
        }
    )
    with pytest.raises(UnsupportedAttachmentTypeError, match="referenceAttachment"):
        get_attachment("m1", "att1", save_dir=str(tmp_path))


@respx.mock
def test_unsupported_type_is_valueerror_subclass(fresh_token: None, tmp_path: Path) -> None:
    """UnsupportedAttachmentTypeError subclasses ValueError so existing
    `except ValueError:` handlers catch it."""
    del fresh_token
    respx.get(ATT_URL).respond(json={"@odata.type": "#microsoft.graph.itemAttachment"})
    with pytest.raises(ValueError):
        get_attachment("m1", "att1", save_dir=str(tmp_path))


@respx.mock
def test_file_attachment_without_content_bytes_raises(fresh_token: None, tmp_path: Path) -> None:
    del fresh_token
    respx.get(ATT_URL).respond(json=_file_attachment(include_content=False))
    with pytest.raises(ValueError, match="without contentBytes"):
        get_attachment("m1", "att1", save_dir=str(tmp_path))


@respx.mock
def test_invalid_base64_raises(fresh_token: None, tmp_path: Path) -> None:
    del fresh_token
    respx.get(ATT_URL).respond(json=_file_attachment(b64="!!!not base64!!!"))
    with pytest.raises(ValueError, match="not valid base64"):
        get_attachment("m1", "att1", save_dir=str(tmp_path))


# ── path-traversal safety ─────────────────────────────────────────────────


@respx.mock
def test_traversal_name_is_sanitised_to_basename(fresh_token: None, tmp_path: Path) -> None:
    """A hostile attachment name must not escape save_dir — only the
    basename survives and the file lands inside save_dir."""
    del fresh_token
    respx.get(ATT_URL).respond(json=_file_attachment(name="../../../../etc/passwd"))

    result = get_attachment("m1", "att1", save_dir=str(tmp_path))

    written = Path(result["path"])
    assert written.parent == tmp_path.resolve()
    assert written.name == "passwd"
    # The write stayed strictly inside save_dir — nothing escaped upward.
    assert written.resolve().is_relative_to(tmp_path.resolve())


@respx.mock
def test_backslash_name_is_sanitised(fresh_token: None, tmp_path: Path) -> None:
    del fresh_token
    respx.get(ATT_URL).respond(json=_file_attachment(name=r"..\\..\\windows\\system32\\evil.dll"))

    result = get_attachment("m1", "att1", save_dir=str(tmp_path))

    written = Path(result["path"])
    assert written.parent == tmp_path.resolve()
    assert written.name == "evil.dll"


@respx.mock
def test_dotdot_only_name_falls_back(fresh_token: None, tmp_path: Path) -> None:
    del fresh_token
    respx.get(ATT_URL).respond(json=_file_attachment(name=".."))

    result = get_attachment("m1", "att1", save_dir=str(tmp_path))

    written = Path(result["path"])
    assert written.parent == tmp_path.resolve()
    assert written.name.startswith("attachment-")


# ── overwrite guard ───────────────────────────────────────────────────────


@respx.mock
def test_refuses_to_overwrite_by_default(fresh_token: None, tmp_path: Path) -> None:
    del fresh_token
    respx.get(ATT_URL).respond(json=_file_attachment(name="report.pdf"))
    (tmp_path / "report.pdf").write_bytes(b"existing")

    with pytest.raises(FileExistsError, match="already exists"):
        get_attachment("m1", "att1", save_dir=str(tmp_path))

    # The pre-existing file must be untouched.
    assert (tmp_path / "report.pdf").read_bytes() == b"existing"


@respx.mock
def test_overwrite_true_replaces(fresh_token: None, tmp_path: Path) -> None:
    del fresh_token
    respx.get(ATT_URL).respond(json=_file_attachment(name="report.pdf"))
    (tmp_path / "report.pdf").write_bytes(b"existing")

    result = get_attachment("m1", "att1", save_dir=str(tmp_path), overwrite=True)

    assert Path(result["path"]).read_bytes() == RAW_BYTES


# ── HTTP error propagation ────────────────────────────────────────────────


@respx.mock
def test_404_propagates(fresh_token: None, tmp_path: Path) -> None:
    del fresh_token
    respx.get(ATT_URL).respond(404, json={"error": {"code": "ErrorItemNotFound"}})
    with pytest.raises(httpx.HTTPStatusError):
        get_attachment("m1", "att1", save_dir=str(tmp_path))


@respx.mock
def test_403_propagates(fresh_token: None, tmp_path: Path) -> None:
    del fresh_token
    locked = f"{GRAPH}/users/locked@xmv.de/messages/m1/attachments/att1"
    respx.get(locked).respond(403, json={"error": {"code": "AccessDenied"}})
    with pytest.raises(httpx.HTTPStatusError):
        get_attachment("m1", "att1", save_dir=str(tmp_path), mailbox="locked@xmv.de")


# ── input validation ──────────────────────────────────────────────────────


def test_empty_message_id_raises(fresh_token: None) -> None:
    del fresh_token
    with pytest.raises(ValueError, match="message_id"):
        get_attachment("", "att1")


def test_whitespace_message_id_raises(fresh_token: None) -> None:
    del fresh_token
    with pytest.raises(ValueError, match="message_id"):
        get_attachment("   ", "att1")


def test_empty_attachment_id_raises(fresh_token: None) -> None:
    del fresh_token
    with pytest.raises(ValueError, match="attachment_id"):
        get_attachment("m1", "")


def test_whitespace_mailbox_raises(fresh_token: None) -> None:
    del fresh_token
    with pytest.raises(ValueError, match="non-empty UPN"):
        get_attachment("m1", "att1", mailbox="   ")
