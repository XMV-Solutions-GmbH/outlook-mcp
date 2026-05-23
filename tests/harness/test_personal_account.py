# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Harness tests for the personal-Microsoft-account path (#48).

Closes the gap left by the existing work/school harness: when the
operator signs in with an outlook.com / hotmail.com / live.com
account, does the OAuth flow complete, does `/me` round-trip, and
does the `_guard_mailbox` runtime check correctly reject the
`mailbox` parameter with a Microsoft-platform-restriction error?

Skipped silently when the `harness-personal` profile's token cache
is missing — populated by
`./scripts/renew-harness-token.sh harness-personal` locally or by
the `OUTLOOK_HARNESS_PERSONAL_TOKEN_JSON` repo secret in CI.

This isn't a comprehensive personal-account suite — Outlook.com
inboxes are usually personal data and aren't safe to assert against
in a public CI log. We verify the **routing contract** (auth works,
mailbox guard fires correctly), nothing about message content.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from outlook_mcp.auth import get_token, is_personal_account
from outlook_mcp.auth.store import PlainFileTokenStore

PERSONAL_PROFILE = "harness-personal"


def _personal_cache_path() -> Path:
    return Path.home() / ".cache" / "outlook-mcp" / PERSONAL_PROFILE / "token.json"


def _skip_if_no_personal_harness() -> None:
    if not _personal_cache_path().exists():
        pytest.skip(
            "Personal-account harness token cache missing. Run "
            "`./scripts/renew-harness-token.sh harness-personal` or set "
            "OUTLOOK_HARNESS_PERSONAL_TOKEN_JSON in the CI repo secrets.",
        )


def _token() -> str:
    os.environ.setdefault("OUTLOOK_TOKEN_STORE", "file")
    return get_token(profile=PERSONAL_PROFILE, store=PlainFileTokenStore())


# ── token + identity sanity ───────────────────────────────────────────────


def test_personal_token_decodes_as_personal_account() -> None:
    """The token cached under `harness-personal` IS actually from a
    consumer Microsoft account. If this fails the cache was populated
    with the wrong account — re-run the renew script with the right
    sign-in."""
    _skip_if_no_personal_harness()
    token = _token()
    assert is_personal_account(token) is True, (
        "harness-personal cached token does NOT have the consumer-tenant "
        "tid claim. Was the profile signed in with a work/school account "
        "by mistake?"
    )


def test_personal_token_can_call_graph_me() -> None:
    """/me works against personal accounts via Graph v1.0 (uses the
    `/common` authority that the v0.7 default sends to). Proves the
    end-to-end auth pipeline for personal accounts: token-cache →
    refresh-if-expired → Bearer-on-Graph → 200 OK."""
    _skip_if_no_personal_harness()
    response = httpx.get(
        "https://graph.microsoft.com/v1.0/me",
        headers={"Authorization": f"Bearer {_token()}"},
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    assert payload.get("id"), f"/me missing id on personal token: {payload}"


# ── mailbox guard refuses personal accounts ───────────────────────────────


def test_guard_mailbox_refuses_personal_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: when SHARED_MAILBOXES=true AND the signed-in account
    is personal, `_guard_mailbox` raises the platform-restriction error.
    The error mentions 'personal Microsoft account' so the agent can
    surface a meaningful message to the user."""
    _skip_if_no_personal_harness()

    # Set up consent so the first guard branch (XMV policy) doesn't
    # short-circuit before the personal-account check runs.
    monkeypatch.setenv("OUTLOOK_ALLOW_DRAFTS", "false")
    monkeypatch.setenv("OUTLOOK_ALLOW_SHARED_MAILBOXES", "true")
    monkeypatch.setenv("OUTLOOK_TOKEN_STORE", "file")
    monkeypatch.setenv("OUTLOOK_PROFILE", PERSONAL_PROFILE)

    from outlook_mcp.server import _guard_mailbox

    with pytest.raises(PermissionError, match="personal Microsoft account"):
        _guard_mailbox("shared@example.com", profile=PERSONAL_PROFILE)


def test_guard_mailbox_allows_none_mailbox_on_personal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`mailbox=None` (the /me path) is allowed on personal accounts —
    nothing in Microsoft platform-restricts that. Personal accounts use
    /me/messages and /me/events just like work/school."""
    _skip_if_no_personal_harness()
    monkeypatch.setenv("OUTLOOK_ALLOW_DRAFTS", "false")
    monkeypatch.setenv("OUTLOOK_ALLOW_SHARED_MAILBOXES", "true")
    monkeypatch.setenv("OUTLOOK_TOKEN_STORE", "file")
    monkeypatch.setenv("OUTLOOK_PROFILE", PERSONAL_PROFILE)

    from outlook_mcp.server import _guard_mailbox

    _guard_mailbox(None, profile=PERSONAL_PROFILE)  # no exception
