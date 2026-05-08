# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Integration tests with boundary mocks (no real Microsoft Graph).

Exercises end-to-end paths within our own codebase: token cache →
get_token refresh → tool HTTP call → response shape, all glued
together via respx as the boundary.
"""

from __future__ import annotations

import time
from pathlib import Path

import respx

from outlook_mcp.auth import get_token
from outlook_mcp.auth.flow import DEFAULT_AUTHORITY_TENANT
from outlook_mcp.auth.store import PlainFileTokenStore
from outlook_mcp.auth.tokens import CachedToken
from outlook_mcp.tools.email_list_unread import list_unread


@respx.mock
def test_refresh_then_list_unread(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Full path: stale cache → refresh against AAD → call Graph → return entries."""
    # Stale token in plain-file backend
    store = PlainFileTokenStore(base_dir=tmp_path)
    store.set(
        "default",
        CachedToken(
            access_token="OLD",
            refresh_token="RT",
            expires_at=time.time() - 1,
            scope="",
        )
        .to_json()
        .encode(),
    )

    # Patch the tool's get_token so it routes through our test store rather
    # than the auto-detected real one.
    monkeypatch.setattr(
        "outlook_mcp.tools.email_list_unread.get_token",
        lambda profile="default": get_token(profile=profile, store=store),
    )

    aad = f"https://login.microsoftonline.com/{DEFAULT_AUTHORITY_TENANT}/oauth2/v2.0/token"
    respx.post(aad).respond(
        json={
            "access_token": "NEW",
            "refresh_token": "RT2",
            "expires_in": 3600,
            "scope": "",
            "token_type": "Bearer",
        }
    )
    respx.get("https://graph.microsoft.com/v1.0/me/mailFolders/Inbox/messages").respond(
        json={"value": []}
    )

    result = list_unread()
    assert result == []

    # Cache was refreshed in place
    raw = store.get("default")
    assert raw is not None
    assert CachedToken.from_json(raw.decode()).access_token == "NEW"
