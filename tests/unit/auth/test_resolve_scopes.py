# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the lazy-scope resolver in auth/flow.py.

Pins the load-bearing property of Option B: the OAuth scope request
appends `Mail.Send` only when `OUTLOOK_ALLOW_SEND` is truthy. Default
installs see a drafts-only consent screen.
"""

from __future__ import annotations

import pytest

from outlook_mcp.auth.flow import resolve_scopes, send_enabled

_BASE = (
    "Mail.Read",
    "Calendars.Read",
    "Mail.ReadWrite",
    "Calendars.ReadWrite",
    "User.Read",
    "offline_access",
)


# ---------------------------------------------------------------------
# send_enabled — env-var parsing (mirrors drafts_enabled / writes_enabled)
# ---------------------------------------------------------------------


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "YES", "on", "ON"])
def test_send_enabled_truthy(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("OUTLOOK_ALLOW_SEND", value)
    assert send_enabled() is True


@pytest.mark.parametrize("value", ["", "false", "0", "no", "off", "garbage"])
def test_send_enabled_falsy(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("OUTLOOK_ALLOW_SEND", value)
    assert send_enabled() is False


def test_send_enabled_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OUTLOOK_ALLOW_SEND", raising=False)
    assert send_enabled() is False


def test_send_enabled_whitespace_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OUTLOOK_ALLOW_SEND", " true ")
    assert send_enabled() is True


# ---------------------------------------------------------------------
# resolve_scopes — the load-bearing lazy-scope behaviour
# ---------------------------------------------------------------------


def test_resolve_scopes_default_omits_mail_send(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default install: consent screen does NOT include 'send mail
    as you'. This is the primary compliance property of the v0.3
    Option B design."""
    monkeypatch.delenv("OUTLOOK_ALLOW_SEND", raising=False)
    scopes = resolve_scopes()
    assert "Mail.Send" not in scopes
    assert set(scopes) == set(_BASE)


def test_resolve_scopes_with_flag_appends_mail_send(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opt-in install: Mail.Send is added to the request. The user
    will see it on the next consent screen."""
    monkeypatch.setenv("OUTLOOK_ALLOW_SEND", "true")
    scopes = resolve_scopes()
    assert "Mail.Send" in scopes
    assert set(scopes) == set(_BASE) | {"Mail.Send"}


def test_resolve_scopes_falsy_value_omits_mail_send(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OUTLOOK_ALLOW_SEND", "false")
    scopes = resolve_scopes()
    assert "Mail.Send" not in scopes


def test_resolve_scopes_returns_tuple(monkeypatch: pytest.MonkeyPatch) -> None:
    """API contract: tuple, not list — the lib's request_device_code
    accepts either, but tuple is the canonical immutable form."""
    monkeypatch.delenv("OUTLOOK_ALLOW_SEND", raising=False)
    assert isinstance(resolve_scopes(), tuple)


def test_resolve_scopes_runtime_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """Calling resolve_scopes() flips behaviour at runtime when the
    env var changes between calls. This is what makes test
    monkeypatching work without re-imports."""
    monkeypatch.delenv("OUTLOOK_ALLOW_SEND", raising=False)
    assert "Mail.Send" not in resolve_scopes()

    monkeypatch.setenv("OUTLOOK_ALLOW_SEND", "true")
    assert "Mail.Send" in resolve_scopes()

    monkeypatch.delenv("OUTLOOK_ALLOW_SEND")
    assert "Mail.Send" not in resolve_scopes()
