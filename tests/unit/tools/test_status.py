# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for ol_status."""

from __future__ import annotations

from pathlib import Path

import pytest

from outlook_mcp.draft_registry import DraftEntry, DraftRegistry
from outlook_mcp.tools.status import status


@pytest.fixture(autouse=True)
def _redirect_default_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("outlook_mcp.tools.status.DraftRegistry", _RedirectedRegistry(tmp_path))


class _RedirectedRegistry:
    """Tiny factory that always points DraftRegistry at tmp_path."""

    def __init__(self, base: Path) -> None:
        self._base = base

    def __call__(self, profile: str) -> DraftRegistry:
        return DraftRegistry(profile=profile, base_dir=self._base)


def test_status_empty_when_no_drafts() -> None:
    assert status() == []


def test_status_returns_entries(tmp_path: Path) -> None:
    """Manually populate the registry that status() will read."""
    registry = DraftRegistry(profile="default", base_dir=tmp_path)
    registry.add(
        DraftEntry(
            kind="email",
            graph_id="msg-1",
            web_url="https://outlook.office.com/m/msg-1",
            subject="Reply to Anna",
            created_at=1715000000.0,
        )
    )
    out = status()
    assert len(out) == 1
    assert out[0]["kind"] == "email"
    assert out[0]["graph_id"] == "msg-1"
    assert out[0]["subject"] == "Reply to Anna"
    # ISO 8601 UTC string
    assert out[0]["created_at"].endswith("+00:00")
