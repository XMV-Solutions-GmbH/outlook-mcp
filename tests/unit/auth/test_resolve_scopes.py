# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the lazy-scope resolver in auth/flow.py.

Pins the load-bearing property of Option B: the OAuth scope request
appends `Mail.Send` only when `OUTLOOK_ALLOW_SEND` is exactly `"true"`
AND `OUTLOOK_ALLOW_DRAFTS=true`. Default installs see a drafts-only
consent screen.

v0.4 makes the env-var parsing strict — only `"true"` / `"false"`
accepted, anything else raises `OutlookConsentNotConfiguredError`.
"""

from __future__ import annotations

import pytest

from outlook_mcp.auth.flow import (
    OutlookConsentNotConfiguredError,
    resolve_scopes,
    send_enabled,
)

_BASE = (
    "Mail.Read",
    "Calendars.Read",
    "Mail.ReadWrite",
    "Calendars.ReadWrite",
    "User.Read",
    "offline_access",
)


def _set_consent(monkeypatch: pytest.MonkeyPatch, drafts: str | None, send: str | None) -> None:
    for name, value in [("OUTLOOK_ALLOW_DRAFTS", drafts), ("OUTLOOK_ALLOW_SEND", send)]:
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


# ---------------------------------------------------------------------
# send_enabled — strict env-var parsing (v0.4)
# ---------------------------------------------------------------------


@pytest.mark.parametrize("value", ["true", "TRUE", " true ", "True"])
def test_send_enabled_true_accepts_case_and_whitespace(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    _set_consent(monkeypatch, drafts="true", send=value)
    assert send_enabled() is True


@pytest.mark.parametrize("value", ["false", "FALSE", " false "])
def test_send_enabled_false_accepts_case_and_whitespace(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    _set_consent(monkeypatch, drafts="true", send=value)
    assert send_enabled() is False


@pytest.mark.parametrize("value", ["1", "yes", "on", "", "0", "no", "off", "garbage"])
def test_send_enabled_strict_rejects_legacy_and_other_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    _set_consent(monkeypatch, drafts="true", send=value)
    with pytest.raises(OutlookConsentNotConfiguredError, match="OUTLOOK_ALLOW_SEND"):
        send_enabled()


def test_send_enabled_unset_when_drafts_true_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_consent(monkeypatch, drafts="true", send=None)
    with pytest.raises(OutlookConsentNotConfiguredError, match="OUTLOOK_ALLOW_SEND"):
        send_enabled()


def test_send_enabled_when_drafts_false_returns_false_no_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DRAFTS=false short-circuits the SEND check (it'd be dead config)."""
    _set_consent(monkeypatch, drafts="false", send=None)
    assert send_enabled() is False


# ---------------------------------------------------------------------
# resolve_scopes — load-bearing scope-derivation
# ---------------------------------------------------------------------


def test_resolve_scopes_drafts_only_omits_mail_send(monkeypatch: pytest.MonkeyPatch) -> None:
    """DRAFTS=true + SEND=false: consent screen does NOT include 'send mail
    as you'. Primary compliance property."""
    _set_consent(monkeypatch, drafts="true", send="false")
    scopes = resolve_scopes()
    assert "Mail.Send" not in scopes
    assert set(scopes) == set(_BASE)


def test_resolve_scopes_with_send_appends_mail_send(monkeypatch: pytest.MonkeyPatch) -> None:
    """DRAFTS=true + SEND=true: Mail.Send is added to the request."""
    _set_consent(monkeypatch, drafts="true", send="true")
    scopes = resolve_scopes()
    assert "Mail.Send" in scopes
    assert set(scopes) == set(_BASE) | {"Mail.Send"}


def test_resolve_scopes_drafts_false_omits_mail_send(monkeypatch: pytest.MonkeyPatch) -> None:
    """DRAFTS=false: scopes are just the base set (no Mail.Send regardless of SEND)."""
    _set_consent(monkeypatch, drafts="false", send=None)
    scopes = resolve_scopes()
    assert "Mail.Send" not in scopes
    assert set(scopes) == set(_BASE)


def test_resolve_scopes_returns_tuple(monkeypatch: pytest.MonkeyPatch) -> None:
    """API contract: tuple, not list."""
    _set_consent(monkeypatch, drafts="false", send=None)
    assert isinstance(resolve_scopes(), tuple)


def test_resolve_scopes_runtime_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_scopes() flips at runtime when env vars change between calls."""
    _set_consent(monkeypatch, drafts="true", send="false")
    assert "Mail.Send" not in resolve_scopes()

    _set_consent(monkeypatch, drafts="true", send="true")
    assert "Mail.Send" in resolve_scopes()

    _set_consent(monkeypatch, drafts="false", send=None)
    assert "Mail.Send" not in resolve_scopes()


def test_resolve_scopes_consent_unset_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_consent(monkeypatch, drafts=None, send=None)
    with pytest.raises(OutlookConsentNotConfiguredError):
        resolve_scopes()
