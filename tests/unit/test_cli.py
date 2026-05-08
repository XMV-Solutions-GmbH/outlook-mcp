# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the CLI subcommand dispatcher.

Verifies argument parsing and subcommand routing without actually
running the MCP server, contacting Microsoft Identity, or touching
the OS keyring.
"""

from __future__ import annotations

import pytest

from outlook_mcp import cli


def test_help_exits_cleanly() -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--help"])
    assert excinfo.value.code == 0


def test_version_exits_cleanly() -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])
    assert excinfo.value.code == 0


def test_login_dispatches_to_interactive_login(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_interactive_login(*, profile: str) -> None:
        captured["profile"] = profile

    monkeypatch.setattr("outlook_mcp.auth.interactive_login", fake_interactive_login)
    assert cli.main(["login", "--profile", "harness"]) == 0
    assert captured == {"profile": "harness"}


def test_login_default_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_interactive_login(*, profile: str) -> None:
        captured["profile"] = profile

    monkeypatch.setattr("outlook_mcp.auth.interactive_login", fake_interactive_login)
    assert cli.main(["login"]) == 0
    assert captured == {"profile": "default"}


def test_logout_calls_store_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    deleted: list[str] = []

    class FakeStore:
        def get(self, profile: str) -> bytes | None:
            return None

        def set(self, profile: str, value: bytes) -> None:
            pass

        def delete(self, profile: str) -> None:
            deleted.append(profile)

    monkeypatch.setattr("outlook_mcp.auth.store.get_token_store", lambda: FakeStore())
    assert cli.main(["logout", "--profile", "harness"]) == 0
    assert deleted == ["harness"]


def test_logout_default_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    deleted: list[str] = []

    class FakeStore:
        def get(self, profile: str) -> bytes | None:
            return None

        def set(self, profile: str, value: bytes) -> None:
            pass

        def delete(self, profile: str) -> None:
            deleted.append(profile)

    monkeypatch.setattr("outlook_mcp.auth.store.get_token_store", lambda: FakeStore())
    assert cli.main(["logout"]) == 0
    assert deleted == ["default"]


def test_no_command_starts_server(monkeypatch: pytest.MonkeyPatch) -> None:
    started = []

    monkeypatch.setattr("outlook_mcp.server.run", lambda: started.append(True))
    assert cli.main([]) == 0
    assert started == [True]


def test_unknown_subcommand_errors() -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["nonsense"])
    # argparse uses exit code 2 for parse errors
    assert excinfo.value.code == 2
