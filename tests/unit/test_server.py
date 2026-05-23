# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the MCP server's read-only-default tool registration.

Verifies that:
- Read tools are always registered.
- Truthy values for `OUTLOOK_ALLOW_DRAFTS` are recognised consistently
  (the v0.2 gate; in v0.1 setting it just logs a notice).
- Annotations are populated on every tool (the security signal Claude
  Code's permission prompt depends on).
"""

from __future__ import annotations

import asyncio

import pytest
from mcp.server.fastmcp import FastMCP

from outlook_mcp.auth.flow import OutlookConsentNotConfiguredError
from outlook_mcp.server import (
    drafts_enabled,
    register_read_tools,
    register_send_tools,
    register_write_tools,
)


def _list_tool_names(server: FastMCP) -> set[str]:
    """Synchronously fetch tool names from a FastMCP server."""
    return {t.name for t in asyncio.run(server.list_tools())}


def _set_consent(monkeypatch: pytest.MonkeyPatch, drafts: str | None, send: str | None) -> None:
    """Helper: set / unset the two consent env vars in one go."""
    for name, value in [("OUTLOOK_ALLOW_DRAFTS", drafts), ("OUTLOOK_ALLOW_SEND", send)]:
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


# ---------------------------------------------------------------------
# drafts_enabled — strict env-var parsing (v0.4)
# ---------------------------------------------------------------------


@pytest.mark.parametrize("value", ["true", "TRUE", " true ", "True"])
def test_drafts_enabled_true_accepts_case_and_whitespace(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    _set_consent(monkeypatch, drafts=value, send="false")
    assert drafts_enabled() is True


@pytest.mark.parametrize("value", ["false", "FALSE", " false "])
def test_drafts_enabled_false_accepts_case_and_whitespace(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    _set_consent(monkeypatch, drafts=value, send=None)
    assert drafts_enabled() is False


@pytest.mark.parametrize("value", ["1", "yes", "on", "garbage", "", "0", "no", "off"])
def test_drafts_enabled_strict_rejects_legacy_and_other_values(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """v0.4 breaking change: only exactly 'true' / 'false' accepted.
    Legacy v0.3 truthy values (1/yes/on) and any other string raise."""
    _set_consent(monkeypatch, drafts=value, send=None)
    with pytest.raises(OutlookConsentNotConfiguredError, match="OUTLOOK_ALLOW_DRAFTS"):
        drafts_enabled()


def test_drafts_enabled_unset_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_consent(monkeypatch, drafts=None, send=None)
    with pytest.raises(OutlookConsentNotConfiguredError, match="not set"):
        drafts_enabled()


def test_drafts_true_without_send_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """When DRAFTS=true, SEND must be explicitly set too."""
    _set_consent(monkeypatch, drafts="true", send=None)
    with pytest.raises(OutlookConsentNotConfiguredError, match="OUTLOOK_ALLOW_SEND"):
        drafts_enabled()


def test_drafts_true_send_legacy_truthy_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Legacy truthy value for SEND is rejected just like DRAFTS."""
    _set_consent(monkeypatch, drafts="true", send="yes")
    with pytest.raises(OutlookConsentNotConfiguredError, match="OUTLOOK_ALLOW_SEND"):
        drafts_enabled()


def test_drafts_false_skips_send_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """When DRAFTS=false, SEND is not checked (it'd be dead config)."""
    _set_consent(monkeypatch, drafts="false", send=None)
    assert drafts_enabled() is False  # no exception


# ---------------------------------------------------------------------
# register_read_tools
# ---------------------------------------------------------------------


def test_register_read_tools_adds_all_read_tools() -> None:
    server = FastMCP("test-read-only")
    register_read_tools(server)
    names = _list_tool_names(server)
    assert names == {
        "ol_email_search",
        "ol_email_list_unread",
        "ol_email_read",
        "ol_email_list_drafts",
        "ol_calendar_search",
        "ol_calendar_list_events",
        "ol_status",
        "ol_login_status",
        "ol_login_begin",
    }


def test_login_tool_descriptions_carry_agent_instructions_marker() -> None:
    """Both ol_login_begin and ol_login_status MUST embed the literal
    `AGENT_INSTRUCTIONS:` marker — closes #42. The marker is the contract
    with pattern-matching MCP clients; rephrasing it breaks them."""
    server = FastMCP("test-read-only")
    register_read_tools(server)
    tools = asyncio.run(server.list_tools())
    login_tools = {t.name: t for t in tools if t.name in ("ol_login_begin", "ol_login_status")}
    assert set(login_tools.keys()) == {"ol_login_begin", "ol_login_status"}
    for name, tool in login_tools.items():
        assert tool.description is not None, f"{name} missing description"
        assert "AGENT_INSTRUCTIONS:" in tool.description, (
            f"{name} description must include the literal "
            f"'AGENT_INSTRUCTIONS:' marker; got: {tool.description!r}"
        )
        assert "fenced code block" in tool.description
        assert "markdown link" in tool.description


def test_login_begin_tool_annotations() -> None:
    """ol_login_begin mutates local state (writes a token to disk on
    success) but does NOT mutate any mailbox state — readOnlyHint=False,
    destructiveHint=False. Idempotent because re-calling while a
    pending session exists returns the same session."""
    server = FastMCP("test-read-only")
    register_read_tools(server)
    [login_begin_tool] = [t for t in asyncio.run(server.list_tools()) if t.name == "ol_login_begin"]
    assert login_begin_tool.annotations is not None
    assert login_begin_tool.annotations.readOnlyHint is False
    assert login_begin_tool.annotations.destructiveHint is False
    assert login_begin_tool.annotations.idempotentHint is True


def test_read_tools_have_readonly_annotation() -> None:
    """All read tools must have readOnlyHint=True so Claude Code's prompt is right.

    Exception: ol_login_begin writes to local disk on success (token
    persistence) — readOnlyHint=False is correct for that one.
    """
    _readwrite_exceptions = {"ol_login_begin"}

    server = FastMCP("test-read-only")
    register_read_tools(server)
    tools = asyncio.run(server.list_tools())
    for tool in tools:
        assert tool.annotations is not None, f"{tool.name} missing annotations"
        if tool.name in _readwrite_exceptions:
            continue
        assert tool.annotations.readOnlyHint is True, (
            f"{tool.name} should be readOnlyHint=True; got {tool.annotations}"
        )


# ---------------------------------------------------------------------
# Module-level mcp object respects OUTLOOK_ALLOW_DRAFTS at import time
# ---------------------------------------------------------------------


def test_module_level_server_includes_read_tools_in_explicit_readonly_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit DRAFTS=false → read-only mode; read tools registered."""
    _set_consent(monkeypatch, drafts="false", send=None)
    from outlook_mcp.server import _build_server

    server = _build_server()
    names = _list_tool_names(server)
    assert "ol_email_search" in names
    assert "ol_status" in names


def test_module_level_server_with_drafts_true_registers_write_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DRAFTS=true + SEND=false: the draft tools register alongside read."""
    _set_consent(monkeypatch, drafts="true", send="false")
    from outlook_mcp.server import _build_server

    server = _build_server()
    names = _list_tool_names(server)
    assert "ol_email_create_draft" in names
    # Read tools still there
    assert "ol_email_search" in names


def test_module_level_server_drafts_false_omits_write_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DRAFTS=false: no draft tools."""
    _set_consent(monkeypatch, drafts="false", send=None)
    from outlook_mcp.server import _build_server

    server = _build_server()
    names = _list_tool_names(server)
    assert "ol_email_create_draft" not in names


def test_module_level_server_refuses_when_consent_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_build_server raises OutlookConsentNotConfiguredError when DRAFTS unset."""
    _set_consent(monkeypatch, drafts=None, send=None)
    from outlook_mcp.server import _build_server

    with pytest.raises(OutlookConsentNotConfiguredError, match="not set"):
        _build_server()


def test_module_level_server_refuses_when_drafts_true_send_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_build_server raises when DRAFTS=true but SEND unset."""
    _set_consent(monkeypatch, drafts="true", send=None)
    from outlook_mcp.server import _build_server

    with pytest.raises(OutlookConsentNotConfiguredError, match="OUTLOOK_ALLOW_SEND"):
        _build_server()


# ---------------------------------------------------------------------
# register_write_tools — annotations + tool surface
# ---------------------------------------------------------------------


def test_register_write_tools_adds_email_create_draft() -> None:
    server = FastMCP("test-with-drafts")
    register_write_tools(server)
    names = _list_tool_names(server)
    assert "ol_email_create_draft" in names


def test_register_write_tools_adds_email_update_draft() -> None:
    server = FastMCP("test-with-drafts")
    register_write_tools(server)
    names = _list_tool_names(server)
    assert "ol_email_update_draft" in names


def test_register_write_tools_adds_email_discard_draft() -> None:
    server = FastMCP("test-with-drafts")
    register_write_tools(server)
    names = _list_tool_names(server)
    assert "ol_email_discard_draft" in names


def test_register_write_tools_adds_calendar_create_event_draft() -> None:
    server = FastMCP("test-with-drafts")
    register_write_tools(server)
    names = _list_tool_names(server)
    assert "ol_calendar_create_event_draft" in names


def test_register_write_tools_adds_calendar_discard_event_draft() -> None:
    server = FastMCP("test-with-drafts")
    register_write_tools(server)
    names = _list_tool_names(server)
    assert "ol_calendar_discard_event_draft" in names


def test_calendar_create_event_draft_is_not_destructive() -> None:
    """Creating a tentative event APPENDS to the calendar — same
    semantic as creating an email draft. Not destructive."""
    server = FastMCP("test-with-drafts")
    register_write_tools(server)
    [tool] = [
        t for t in asyncio.run(server.list_tools()) if t.name == "ol_calendar_create_event_draft"
    ]
    assert tool.annotations is not None
    assert tool.annotations.readOnlyHint is False
    assert tool.annotations.destructiveHint is False


def test_discard_draft_tool_is_destructive_and_idempotent() -> None:
    """DELETE on a draft removes it permanently — destructiveHint=True.
    Idempotent because re-deleting an already-gone draft is a no-op."""
    server = FastMCP("test-with-drafts")
    register_write_tools(server)
    [discard_tool] = [
        t for t in asyncio.run(server.list_tools()) if t.name == "ol_email_discard_draft"
    ]
    assert discard_tool.annotations is not None
    assert discard_tool.annotations.readOnlyHint is False
    assert discard_tool.annotations.destructiveHint is True
    assert discard_tool.annotations.idempotentHint is True


def test_create_draft_tool_is_not_readonly_not_destructive() -> None:
    """Creating a draft mutates the user's mailbox state (a draft
    appears in their Drafts folder), so readOnlyHint=False. It is
    NOT destructive — drafts don't overwrite or delete anything,
    they just append. The annotation pair lets Claude Code's
    permission prompt render the right messaging."""
    server = FastMCP("test-with-drafts")
    register_write_tools(server)
    [draft_tool] = [
        t for t in asyncio.run(server.list_tools()) if t.name == "ol_email_create_draft"
    ]
    assert draft_tool.annotations is not None
    assert draft_tool.annotations.readOnlyHint is False
    assert draft_tool.annotations.destructiveHint is False


def test_update_draft_tool_is_destructive() -> None:
    """A PATCH overwrites the previous draft state on Graph, so
    destructiveHint=True. Idempotent because re-applying the same
    PATCH yields the same result."""
    server = FastMCP("test-with-drafts")
    register_write_tools(server)
    [update_tool] = [
        t for t in asyncio.run(server.list_tools()) if t.name == "ol_email_update_draft"
    ]
    assert update_tool.annotations is not None
    assert update_tool.annotations.readOnlyHint is False
    assert update_tool.annotations.destructiveHint is True
    assert update_tool.annotations.idempotentHint is True


def test_no_send_tool_in_default_config() -> None:
    """The default config invariant: NO send_* tool is registered
    when only `OUTLOOK_ALLOW_DRAFTS` is set (and `OUTLOOK_ALLOW_SEND`
    is unset). The default install is drafts-only.

    From v0.3 onwards, send is opt-in via OUTLOOK_ALLOW_SEND=true
    (covered by test_register_send_tools_adds_email_send_draft below).
    Without that explicit second flag, no send_* tool exists — that's
    the load-bearing invariant for the default consent posture."""
    server = FastMCP("test-with-drafts-only")
    register_read_tools(server)
    register_write_tools(server)
    # Crucially: NO register_send_tools call here.
    names = _list_tool_names(server)
    for name in names:
        assert "send" not in name.lower(), (
            f"Tool {name!r} contains 'send' — when OUTLOOK_ALLOW_SEND "
            f"is not explicitly set, no send_* tool may be registered."
        )


# ---------------------------------------------------------------------
# register_send_tools — opt-in via OUTLOOK_ALLOW_SEND
# ---------------------------------------------------------------------


def test_register_send_tools_adds_email_send_draft() -> None:
    """When the OUTLOOK_ALLOW_SEND opt-in is active and
    register_send_tools is invoked, the ol_email_send_draft tool
    becomes visible to the agent."""
    server = FastMCP("test-with-send")
    register_write_tools(server)
    register_send_tools(server)
    names = _list_tool_names(server)
    assert "ol_email_send_draft" in names


def test_send_draft_tool_is_destructive_not_idempotent() -> None:
    """Sending a draft is irreversible (the mail leaves the user's
    mailbox and is delivered) — destructiveHint=True. Re-sending an
    already-sent draft yields a 404 from Graph — idempotentHint=False."""
    server = FastMCP("test-with-send")
    register_send_tools(server)
    [send_tool] = [t for t in asyncio.run(server.list_tools()) if t.name == "ol_email_send_draft"]
    assert send_tool.annotations is not None
    assert send_tool.annotations.readOnlyHint is False
    assert send_tool.annotations.destructiveHint is True
    assert send_tool.annotations.idempotentHint is False


def test_module_level_server_registers_send_when_both_flags_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DRAFTS=true + SEND=true → ol_email_send_draft is registered."""
    _set_consent(monkeypatch, drafts="true", send="true")
    from outlook_mcp.server import _build_server

    server = _build_server()
    names = _list_tool_names(server)
    assert "ol_email_send_draft" in names


def test_module_level_server_drafts_true_send_false_omits_send_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DRAFTS=true + SEND=false: drafts registered but no send tool."""
    _set_consent(monkeypatch, drafts="true", send="false")
    from outlook_mcp.server import _build_server

    server = _build_server()
    names = _list_tool_names(server)
    assert "ol_email_create_draft" in names
    assert "ol_email_send_draft" not in names


# ---------------------------------------------------------------------
# #45: shared-mailbox + delete opt-ins
# ---------------------------------------------------------------------


def _set_full_consent(
    monkeypatch: pytest.MonkeyPatch,
    *,
    drafts: str = "false",
    send: str | None = None,
    shared: str | None = None,
    delete: str | None = None,
) -> None:
    _set_consent(monkeypatch, drafts=drafts, send=send)
    for name, value in [
        ("OUTLOOK_ALLOW_SHARED_MAILBOXES", shared),
        ("OUTLOOK_ALLOW_DELETE", delete),
    ]:
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


# ── shared_mailboxes_enabled / delete_enabled accessors ──────────────────


def test_shared_mailboxes_enabled_default_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset = False — preserves existing-install behaviour."""
    from outlook_mcp.server import shared_mailboxes_enabled

    _set_full_consent(monkeypatch, drafts="false")
    assert shared_mailboxes_enabled() is False


def test_shared_mailboxes_enabled_true(monkeypatch: pytest.MonkeyPatch) -> None:
    from outlook_mcp.server import shared_mailboxes_enabled

    _set_full_consent(monkeypatch, drafts="false", shared="true")
    assert shared_mailboxes_enabled() is True


def test_shared_mailboxes_enabled_typo_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from outlook_mcp.auth.flow import OutlookConsentNotConfiguredError
    from outlook_mcp.server import shared_mailboxes_enabled

    _set_full_consent(monkeypatch, drafts="false", shared="enabled")
    with pytest.raises(OutlookConsentNotConfiguredError, match="OUTLOOK_ALLOW_SHARED_MAILBOXES"):
        shared_mailboxes_enabled()


def test_delete_enabled_default_false(monkeypatch: pytest.MonkeyPatch) -> None:
    from outlook_mcp.server import delete_enabled

    _set_full_consent(monkeypatch, drafts="false")
    assert delete_enabled() is False


def test_delete_enabled_true(monkeypatch: pytest.MonkeyPatch) -> None:
    from outlook_mcp.server import delete_enabled

    _set_full_consent(monkeypatch, drafts="false", delete="true")
    assert delete_enabled() is True


# ── _guard_mailbox enforcement ────────────────────────────────────────────


def test_guard_mailbox_allows_none_when_shared_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default (mailbox=None) is always allowed — that's the unchanged
    /me code path. Short-circuits before token-fetch, so no fixture needed."""
    from outlook_mcp.server import _guard_mailbox

    _set_full_consent(monkeypatch, drafts="false")
    _guard_mailbox(None, profile="default")  # no exception


def test_guard_mailbox_refuses_non_none_when_shared_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point of the guard: tell the operator about the env-var
    requirement before Graph returns a confusing 403. Short-circuits before
    token-fetch (config check wins), so no fixture needed."""
    from outlook_mcp.server import _guard_mailbox

    _set_full_consent(monkeypatch, drafts="false")
    with pytest.raises(PermissionError, match="OUTLOOK_ALLOW_SHARED_MAILBOXES"):
        _guard_mailbox("shared@xmv.de", profile="default")


def test_guard_mailbox_allows_non_none_when_shared_enabled_and_work_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SHARED on + work/school token → mailbox accepted. Requires faking a
    work/school JWT (tid != consumer GUID) into the token-fetch path."""
    from outlook_mcp.server import _guard_mailbox

    _set_full_consent(monkeypatch, drafts="false", shared="true")
    monkeypatch.setattr(
        "outlook_mcp.server.get_token",
        lambda profile="default": _fake_jwt_with_tid("00000000-0000-0000-0000-000000000001"),
    )
    _guard_mailbox("shared@xmv.de", profile="default")  # no exception


def test_guard_mailbox_refuses_personal_account_even_when_shared_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The new #45-personal-account guard: even with SHARED_MAILBOXES=true,
    a consumer token can't drive `/users/{upn}/...` (Microsoft platform
    restriction, not XMV policy). Error message names the actual
    constraint."""
    from outlook_mcp.auth.account_type import CONSUMER_TENANT_ID
    from outlook_mcp.server import _guard_mailbox

    _set_full_consent(monkeypatch, drafts="false", shared="true")
    monkeypatch.setattr(
        "outlook_mcp.server.get_token",
        lambda profile="default": _fake_jwt_with_tid(CONSUMER_TENANT_ID),
    )
    with pytest.raises(PermissionError, match="personal Microsoft account"):
        _guard_mailbox("shared@example.com", profile="default")


def _fake_jwt_with_tid(tid: str) -> str:
    """Compose a 3-segment JWT-shaped string with the given `tid` claim.

    Signature is junk — `is_personal_account()` decodes claims without
    verification (the token already passed Microsoft's checks upstream;
    this helper only needs to round-trip the claim for tests).
    """
    import base64
    import json

    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"tid": tid}).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.sig"


# ── register_delete_tools / ol_email_delete registration ──────────────────


def test_register_delete_tools_adds_ol_email_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    """When OUTLOOK_ALLOW_DELETE=true the delete tool is registered."""
    _set_full_consent(monkeypatch, drafts="false", delete="true")
    from outlook_mcp.server import _build_server

    server = _build_server()
    names = _list_tool_names(server)
    assert "ol_email_delete" in names


def test_delete_tool_absent_when_delete_flag_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing-install behaviour: delete flag unset = no delete tool."""
    _set_full_consent(monkeypatch, drafts="false")
    from outlook_mcp.server import _build_server

    server = _build_server()
    names = _list_tool_names(server)
    assert "ol_email_delete" not in names


def test_delete_tool_absent_when_delete_explicitly_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_full_consent(monkeypatch, drafts="false", delete="false")
    from outlook_mcp.server import _build_server

    server = _build_server()
    names = _list_tool_names(server)
    assert "ol_email_delete" not in names


def test_delete_tool_orthogonal_to_drafts_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DELETE flag is independent of DRAFTS/SEND. An operator might want
    delete on the signed-in mailbox without enabling drafts."""
    _set_full_consent(monkeypatch, drafts="false", delete="true")
    from outlook_mcp.server import _build_server

    server = _build_server()
    names = _list_tool_names(server)
    assert "ol_email_delete" in names
    # Drafts/send not registered when DRAFTS=false.
    assert "ol_email_create_draft" not in names
    assert "ol_email_send_draft" not in names


def test_delete_tool_annotations_are_destructive() -> None:
    """ol_email_delete moves data — destructiveHint=True. Idempotent
    because 404 is treated as success."""
    from outlook_mcp.server import register_delete_tools

    server = FastMCP("test-delete")
    register_delete_tools(server)
    [delete_tool] = [t for t in asyncio.run(server.list_tools()) if t.name == "ol_email_delete"]
    assert delete_tool.annotations is not None
    assert delete_tool.annotations.readOnlyHint is False
    assert delete_tool.annotations.destructiveHint is True
    assert delete_tool.annotations.idempotentHint is True
