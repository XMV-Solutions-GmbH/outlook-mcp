# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""The gated scopes must not reach Microsoft Identity when their flags are off.

`tests/unit/auth/test_resolve_scopes.py` pins what `resolve_scopes()`
computes. These tests pin the half that actually protects anyone:
that the computed set is what goes **on the wire**, in the `scope`
form field of every request that can widen a grant — the device-code
request that drives the consent screen, and the refresh grant.

A gap between the two would be invisible in the unit tests above and
would silently extend the consent prompt, which is the whole
compliance story of this server.

Note what these tests do NOT claim. They constrain the scopes this
server *requests*. Microsoft Entra decides what the issued token
*carries*, and it returns every scope already consented for the app
on that resource regardless of the narrower set asked for — verified
against a live tenant: a refresh asking for exactly the six base
scopes came back with `Mail.Send`, `Mail.ReadWrite.Shared` and
`Group-Conversation.Read.All` in `scp` as well, because an earlier
sign-in had consented to them. Withholding a scope from an already-
consented app registration is not something a client can do; see
README § "What the flags do and do not control".
"""

from __future__ import annotations

import time
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from outlook_mcp.auth import get_token, interactive_login
from outlook_mcp.auth.tokens import CachedToken

DEVICE_CODE_URL = "https://login.microsoftonline.com/organizations/oauth2/v2.0/devicecode"
ORG_TOKEN_URL = "https://login.microsoftonline.com/organizations/oauth2/v2.0/token"
COMMON_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

GATED_SCOPES = ("Mail.Send", "Mail.ReadWrite.Shared", "Group-Conversation.Read.All")


class _MemStore:
    def __init__(self, raw: bytes | None = None) -> None:
        self._d: dict[str, bytes] = {"default": raw} if raw is not None else {}

    def get(self, profile: str) -> bytes | None:
        return self._d.get(profile)

    def set(self, profile: str, value: bytes) -> None:
        self._d[profile] = value

    def delete(self, profile: str) -> None:
        self._d.pop(profile, None)


def _drafts_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """The deployment under discussion: drafts on, everything else off."""
    monkeypatch.setenv("OUTLOOK_ALLOW_DRAFTS", "true")
    monkeypatch.setenv("OUTLOOK_ALLOW_SEND", "false")
    monkeypatch.delenv("OUTLOOK_ALLOW_SHARED_MAILBOXES", raising=False)
    monkeypatch.delenv("OUTLOOK_ALLOW_GROUP_MAILBOXES", raising=False)


def _requested_scope(request: httpx.Request) -> list[str]:
    return parse_qs(request.content.decode())["scope"][0].split()


def _device_code_json() -> dict[str, object]:
    return {
        "device_code": "DC",
        "user_code": "ABCD-EFGH",
        "verification_uri": "https://microsoft.com/devicelogin",
        "expires_in": 900,
        "interval": 0,
        "message": "sign in",
    }


def _token_json() -> dict[str, object]:
    return {
        "access_token": "AT",
        "refresh_token": "RT",
        "expires_in": 3600,
        # What Entra actually answers for a consented app: MORE than
        # was asked for. The client cannot prevent this.
        "scope": "Mail.Read Mail.ReadWrite Mail.Send User.Read",
        "token_type": "Bearer",
    }


@respx.mock
def test_device_code_request_withholds_every_gated_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _drafts_only(monkeypatch)
    device_route = respx.post(DEVICE_CODE_URL).respond(json=_device_code_json())
    respx.post(ORG_TOKEN_URL).respond(200, json=_token_json())

    interactive_login(
        profile="default",
        account_type="work_or_school",
        store=_MemStore(),
        prompt=lambda challenge: None,
    )

    scopes = _requested_scope(device_route.calls[0].request)
    for gated in GATED_SCOPES:
        assert gated not in scopes, f"{gated} reached the consent screen with its flag off"
    assert "Mail.ReadWrite" in scopes  # the drafts opt-in is still honoured


@respx.mock
def test_device_code_request_includes_a_scope_once_its_flag_is_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The inverse, so the assertion above cannot pass by never
    requesting anything at all."""
    _drafts_only(monkeypatch)
    monkeypatch.setenv("OUTLOOK_ALLOW_SEND", "true")
    monkeypatch.setenv("OUTLOOK_ALLOW_SHARED_MAILBOXES", "true")
    monkeypatch.setenv("OUTLOOK_ALLOW_GROUP_MAILBOXES", "true")
    device_route = respx.post(DEVICE_CODE_URL).respond(json=_device_code_json())
    respx.post(ORG_TOKEN_URL).respond(200, json=_token_json())

    interactive_login(
        profile="default",
        account_type="work_or_school",
        store=_MemStore(),
        prompt=lambda challenge: None,
    )

    scopes = _requested_scope(device_route.calls[0].request)
    for gated in GATED_SCOPES:
        assert gated in scopes


@respx.mock
def test_refresh_grant_withholds_every_gated_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The silent-renewal path runs far more often than sign-in. If it
    asked for more than the flags allow, the narrow consent screen at
    sign-in would be cosmetic."""
    _drafts_only(monkeypatch)
    expired = CachedToken(
        access_token="old", refresh_token="RT", expires_at=time.time() - 60, scope=""
    )
    route = respx.post(COMMON_TOKEN_URL).respond(200, json=_token_json())

    get_token("default", store=_MemStore(expired.to_json().encode()))

    scopes = _requested_scope(route.calls[0].request)
    for gated in GATED_SCOPES:
        assert gated not in scopes, f"{gated} was re-requested on refresh with its flag off"
