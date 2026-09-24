# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""The harness layer must refuse to run without an explicit opt-in.

The harness creates and permanently deletes messages in a live
mailbox. `./tests/run_tests.sh all` says nothing about that, and any
machine holding a harness token cache would otherwise reach the real
mailbox from an ordinary-looking test command.

These tests run in the unit layer so they execute everywhere — a gate
that is only exercised where credentials exist is exercised too late.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from tests.harness.conftest import (
    HARNESS_OPT_IN_ENV,
    harness_opt_in_granted,
    pytest_collection_modifyitems,
)


class _FakeItem:
    """Minimal stand-in for a collected test item."""

    def __init__(self) -> None:
        self.markers: list[Any] = []

    def add_marker(self, marker: Any) -> None:
        self.markers.append(marker)

    @property
    def skipped(self) -> bool:
        return any(getattr(m, "name", None) == "skip" for m in self.markers)


def _run_gate(items: list[_FakeItem]) -> None:
    """Drive the collection hook with stand-in items.

    The casts are the price of testing a pytest hook without a real
    collection; they say "these quack like Items", which for the two
    attributes the hook touches they do.
    """
    pytest_collection_modifyitems(
        config=cast("pytest.Config", None),
        items=cast("list[pytest.Item]", items),
    )


@pytest.mark.parametrize("value", ["true", "TRUE", "  true  "])
def test_opt_in_is_granted_by_an_explicit_true(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(HARNESS_OPT_IN_ENV, value)
    assert harness_opt_in_granted()


@pytest.mark.parametrize("value", ["1", "yes", "on", "false", "", "  ", "True-ish"])
def test_a_near_miss_does_not_grant_the_opt_in(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """Strict, matching the OUTLOOK_ALLOW_* parser. A value that only
    looks affirmative must fail closed — the cost of a false negative
    is a skipped test run, the cost of a false positive is deleted
    mail."""
    monkeypatch.setenv(HARNESS_OPT_IN_ENV, value)
    assert not harness_opt_in_granted()


def test_unset_does_not_grant_the_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(HARNESS_OPT_IN_ENV, raising=False)
    assert not harness_opt_in_granted()


def test_every_collected_item_is_skipped_without_the_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate is applied at collection, so it covers harness tests
    that do not exist yet — the ones whose author would have forgotten
    to call a per-file helper."""
    monkeypatch.delenv(HARNESS_OPT_IN_ENV, raising=False)
    items = [_FakeItem(), _FakeItem(), _FakeItem()]

    _run_gate(items)

    assert all(item.skipped for item in items)


def test_the_skip_reason_says_what_is_at_stake(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bare "skipped" teaches nobody why. The reason has to name the
    consequence and the variable."""
    monkeypatch.delenv(HARNESS_OPT_IN_ENV, raising=False)
    item = _FakeItem()

    _run_gate([item])

    reason = str(item.markers[0].kwargs["reason"])
    assert HARNESS_OPT_IN_ENV in reason
    assert "PERMANENTLY" in reason
    assert "live Microsoft 365 mailbox" in reason


def test_nothing_is_skipped_once_the_opt_in_is_granted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(HARNESS_OPT_IN_ENV, "true")
    items = [_FakeItem(), _FakeItem()]

    _run_gate(items)

    assert not any(item.skipped for item in items)
