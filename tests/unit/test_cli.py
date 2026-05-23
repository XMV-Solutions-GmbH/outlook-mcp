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

    def fake_interactive_login(*, profile: str, account_type: str | None) -> None:
        captured["profile"] = profile
        captured["account_type"] = account_type

    monkeypatch.setattr("outlook_mcp.auth.interactive_login", fake_interactive_login)
    assert cli.main(["login", "--profile", "harness", "--account-type", "work_or_school"]) == 0
    assert captured == {"profile": "harness", "account_type": "work_or_school"}


def test_login_default_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_interactive_login(*, profile: str, account_type: str | None) -> None:
        captured["profile"] = profile
        captured["account_type"] = account_type

    monkeypatch.setattr("outlook_mcp.auth.interactive_login", fake_interactive_login)
    assert cli.main(["login", "--account-type", "personal"]) == 0
    assert captured == {"profile": "default", "account_type": "personal"}


def test_login_account_type_personal_dispatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--account-type personal` is passed verbatim into interactive_login —
    this is the test seam for the personal-account routing."""
    captured: dict[str, object] = {}

    def fake_interactive_login(*, profile: str, account_type: str | None) -> None:
        captured["account_type"] = account_type

    monkeypatch.setattr("outlook_mcp.auth.interactive_login", fake_interactive_login)
    assert cli.main(["login", "--account-type", "personal"]) == 0
    assert captured["account_type"] == "personal"


def test_login_account_type_invalid_choice_rejected_by_argparse() -> None:
    """argparse `choices` enforces the two-value contract at parse time;
    a typo never reaches the auth layer."""
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["login", "--account-type", "privat"])
    assert excinfo.value.code == 2


def test_login_no_account_type_no_env_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without --account-type AND without OUTLOOK_TENANT_ID, the CLI
    exits 2 with the agent-readable elicit-user message on stderr.
    This is the v0.7 onboarding default — operators see the message
    once and learn to pass the flag."""
    monkeypatch.delenv("OUTLOOK_TENANT_ID", raising=False)
    # Use the REAL interactive_login (no monkeypatch) so the raise
    # comes from the actual code path, not a stub.
    assert cli.main(["login"]) == 2
    err = capsys.readouterr().err
    assert "account_type" in err
    assert "personal" in err
    assert "work_or_school" in err


def test_login_env_var_satisfies_requirement_without_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backwards-compat: OUTLOOK_TENANT_ID set → CLI accepts no flag and
    delegates to interactive_login with account_type=None."""
    monkeypatch.setenv("OUTLOOK_TENANT_ID", "consumers")
    captured: dict[str, object] = {}

    def fake_interactive_login(*, profile: str, account_type: str | None) -> None:
        captured["account_type"] = account_type

    monkeypatch.setattr("outlook_mcp.auth.interactive_login", fake_interactive_login)
    assert cli.main(["login"]) == 0
    assert captured["account_type"] is None


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
