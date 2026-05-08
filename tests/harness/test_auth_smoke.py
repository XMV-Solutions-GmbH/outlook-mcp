# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Harness smoke test — proves end-to-end auth against the real Microsoft Graph.

This is the gate per ENGINEERING_PRINCIPLES.md § 5: before any feature
ticket can enter "Doing", this test must be green against the real
sandbox tenant. It exercises the full auth pipeline:

1. PlainFileTokenStore reads `~/.cache/outlook-mcp/harness/token.json`.
2. Refresh-token round-trip against Microsoft Identity if needed.
3. `GET /me` against Microsoft Graph with the resulting access token.
4. Verify the response contains an `id` + `userPrincipalName`.

Skips silently when the harness token cache isn't present locally
(the typical case for a fresh contributor) — CI restores the cache
from a repo secret so the test runs there even if not locally.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from outlook_mcp.auth import get_token
from outlook_mcp.auth.store import PlainFileTokenStore

HARNESS_PROFILE = "harness"


def _harness_cache_path() -> Path:
    return Path.home() / ".cache" / "outlook-mcp" / HARNESS_PROFILE / "token.json"


@pytest.mark.skipif(
    not _harness_cache_path().exists() and not os.environ.get("OUTLOOK_HARNESS_TOKEN_JSON"),
    reason=(
        "Harness token cache missing. Run "
        "`./scripts/renew-harness-token.sh` to install one, or set "
        "OUTLOOK_HARNESS_TOKEN_JSON in the environment."
    ),
)
def test_get_token_then_call_graph_me() -> None:
    """The single must-pass-before-features harness gate."""
    # Pin to plain-file backend explicitly so the test behaves the same
    # locally and in CI (where there is no OS keyring).
    os.environ.setdefault("OUTLOOK_TOKEN_STORE", "file")

    store = PlainFileTokenStore()
    access_token = get_token(profile=HARNESS_PROFILE, store=store)
    assert access_token, "auth pipeline returned an empty access token"

    response = httpx.get(
        "https://graph.microsoft.com/v1.0/me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    assert payload.get("id"), f"/me missing id: {payload}"
    assert payload.get("userPrincipalName"), f"/me missing userPrincipalName: {payload}"
