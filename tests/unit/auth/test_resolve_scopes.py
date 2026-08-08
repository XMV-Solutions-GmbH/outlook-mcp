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


# ---------------------------------------------------------------------
# OUTLOOK_ALLOW_SHARED_MAILBOXES scope handling — #45
# ---------------------------------------------------------------------


def _set_full_consent(
    monkeypatch: pytest.MonkeyPatch,
    *,
    drafts: str = "false",
    send: str | None = None,
    shared: str | None = None,
    delete: str | None = None,
) -> None:
    """Wrapper that also flips the two v0.5 optional flags. Defaults
    keep tests focused on a single flag at a time."""
    _set_consent(monkeypatch, drafts=drafts, send=send)
    for name, value in [
        ("OUTLOOK_ALLOW_SHARED_MAILBOXES", shared),
        ("OUTLOOK_ALLOW_DELETE", delete),
    ]:
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


def test_resolve_scopes_shared_mailboxes_false_omits_shared_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default (flag unset) keeps the old scope set — no breakage for
    existing installs."""
    _set_full_consent(monkeypatch, drafts="false")
    scopes = resolve_scopes()
    assert "Mail.ReadWrite.Shared" not in scopes


def test_resolve_scopes_shared_mailboxes_true_appends_shared_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SHARED_MAILBOXES=true: consent screen exposes shared-mailbox
    read+write — the load-bearing property for #45."""
    _set_full_consent(monkeypatch, drafts="false", shared="true")
    scopes = resolve_scopes()
    assert "Mail.ReadWrite.Shared" in scopes


def test_resolve_scopes_shared_mailboxes_explicit_false_no_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit 'false' is the same as unset for scope purposes."""
    _set_full_consent(monkeypatch, drafts="false", shared="false")
    scopes = resolve_scopes()
    assert "Mail.ReadWrite.Shared" not in scopes


def test_resolve_scopes_shared_mailboxes_typo_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A typo (yes/1/on) raises — silent fall-through to safe-off would
    confuse the operator who thinks they enabled shared access."""
    _set_full_consent(monkeypatch, drafts="false", shared="yes")
    with pytest.raises(OutlookConsentNotConfiguredError, match="OUTLOOK_ALLOW_SHARED_MAILBOXES"):
        resolve_scopes()


def test_resolve_scopes_all_four_flags_compose(monkeypatch: pytest.MonkeyPatch) -> None:
    """Full surface enabled: BASE + Mail.Send + Mail.ReadWrite.Shared."""
    _set_full_consent(
        monkeypatch,
        drafts="true",
        send="true",
        shared="true",
        delete="true",
    )
    scopes = resolve_scopes()
    assert "Mail.Send" in scopes
    assert "Mail.ReadWrite.Shared" in scopes


def test_resolve_scopes_delete_alone_does_not_add_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OUTLOOK_ALLOW_DELETE doesn't require an extra OAuth scope — the
    base Mail.ReadWrite already covers DELETE on /me/messages. The
    flag only gates tool registration."""
    _set_full_consent(monkeypatch, drafts="false", delete="true")
    scopes = resolve_scopes()
    # No new scope from delete-only.
    assert "Mail.ReadWrite.Shared" not in scopes
    assert "Mail.Send" not in scopes


def test_resolve_scopes_delete_typo_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_full_consent(monkeypatch, drafts="false", delete="enabled")
    with pytest.raises(OutlookConsentNotConfiguredError, match="OUTLOOK_ALLOW_DELETE"):
        resolve_scopes()


def test_group_mailboxes_adds_least_privileged_group_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Group-Conversation.Read.All, NOT Group.Read.All: the latter would
    also grant tenant-wide directory reads this server never performs."""
    monkeypatch.setenv("OUTLOOK_ALLOW_DRAFTS", "false")
    monkeypatch.setenv("OUTLOOK_ALLOW_GROUP_MAILBOXES", "true")
    scopes = resolve_scopes()
    assert "Group-Conversation.Read.All" in scopes
    assert "Group.Read.All" not in scopes


def test_group_scope_absent_when_flag_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OUTLOOK_ALLOW_DRAFTS", "false")
    monkeypatch.delenv("OUTLOOK_ALLOW_GROUP_MAILBOXES", raising=False)
    assert "Group-Conversation.Read.All" not in resolve_scopes()
