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


def test_register_read_tools_adds_all_v01_tools() -> None:
    server = FastMCP("test-read-only")
    register_read_tools(server)
    names = _list_tool_names(server)
    assert names == {
        "ol_email_search",
        "ol_email_list_unread",
        "ol_email_read",
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


def test_module_level_server_with_drafts_set_still_only_has_read_tools_in_v01(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """v0.1 has no draft tools yet — flag is parsed but registers nothing extra."""
    monkeypatch.setenv("OUTLOOK_ALLOW_DRAFTS", "true")
    from outlook_mcp.server import _build_server

    server = _build_server()
    names = _list_tool_names(server)
    # No `ol_email_create_draft` etc. exist in v0.1
    assert "ol_email_create_draft" not in names
    assert "ol_email_search" in names
