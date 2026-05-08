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

from outlook_mcp.server import (
    drafts_enabled,
    register_read_tools,
    register_write_tools,
)


def _list_tool_names(server: FastMCP) -> set[str]:
    """Synchronously fetch tool names from a FastMCP server."""
    return {t.name for t in asyncio.run(server.list_tools())}


# ---------------------------------------------------------------------
# drafts_enabled — env-var parsing
# ---------------------------------------------------------------------


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "YES", "on", "ON"])
def test_drafts_enabled_truthy(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("OUTLOOK_ALLOW_DRAFTS", value)
    assert drafts_enabled() is True


@pytest.mark.parametrize("value", ["", "false", "0", "no", "off", "garbage"])
def test_drafts_enabled_falsy(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("OUTLOOK_ALLOW_DRAFTS", value)
    assert drafts_enabled() is False


def test_drafts_enabled_whitespace_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    """The implementation strips + lowercases — whitespace-padded truthy passes."""
    monkeypatch.setenv("OUTLOOK_ALLOW_DRAFTS", " true ")
    assert drafts_enabled() is True


def test_drafts_enabled_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OUTLOOK_ALLOW_DRAFTS", raising=False)
    assert drafts_enabled() is False


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
    }


def test_read_tools_have_readonly_annotation() -> None:
    """All read tools must have readOnlyHint=True so Claude Code's prompt is right."""
    server = FastMCP("test-read-only")
    register_read_tools(server)
    tools = asyncio.run(server.list_tools())
    for tool in tools:
        assert tool.annotations is not None, f"{tool.name} missing annotations"
        assert tool.annotations.readOnlyHint is True, (
            f"{tool.name} should be readOnlyHint=True; got {tool.annotations}"
        )


# ---------------------------------------------------------------------
# Module-level mcp object respects OUTLOOK_ALLOW_DRAFTS at import time
# ---------------------------------------------------------------------


def test_module_level_server_includes_read_tools_when_drafts_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh server constructed without the env var has the v0.1 read tools."""
    monkeypatch.delenv("OUTLOOK_ALLOW_DRAFTS", raising=False)
    from outlook_mcp.server import _build_server

    server = _build_server()
    names = _list_tool_names(server)
    assert "ol_email_search" in names
    assert "ol_status" in names


def test_module_level_server_with_drafts_set_registers_write_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OUTLOOK_ALLOW_DRAFTS=true causes the gated draft tools to register
    alongside the read tools."""
    monkeypatch.setenv("OUTLOOK_ALLOW_DRAFTS", "true")
    from outlook_mcp.server import _build_server

    server = _build_server()
    names = _list_tool_names(server)
    assert "ol_email_create_draft" in names
    # Read tools still there
    assert "ol_email_search" in names


def test_module_level_server_with_drafts_unset_omits_write_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default (read-only) mode: draft tools are NOT visible."""
    monkeypatch.delenv("OUTLOOK_ALLOW_DRAFTS", raising=False)
    from outlook_mcp.server import _build_server

    server = _build_server()
    names = _list_tool_names(server)
    assert "ol_email_create_draft" not in names


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


def test_no_send_tool_exists_anywhere() -> None:
    """The defining design constraint of this server: NO send_* tool
    is ever registered, even with OUTLOOK_ALLOW_DRAFTS=true. If this
    test ever fails, someone violated the never-auto-send rule."""
    server = FastMCP("test-with-drafts")
    register_read_tools(server)
    register_write_tools(server)
    names = _list_tool_names(server)
    for name in names:
        assert "send" not in name.lower(), (
            f"Tool {name!r} contains 'send' — the never-auto-send rule "
            f"forbids any send_* tool, ever."
        )
