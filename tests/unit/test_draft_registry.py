# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the persistent draft registry.

Atomic-write + thread-safety semantics matter even in v0.1 even
though no tool populates entries: v0.2 will, and we want the
contracts locked down before they ship.
"""

from __future__ import annotations

from pathlib import Path

from outlook_mcp.draft_registry import DraftEntry, DraftRegistry


def _entry(graph_id: str = "msg-1", subject: str = "hello") -> DraftEntry:
    return DraftEntry(
        kind="email",
        graph_id=graph_id,
        web_url=f"https://outlook.office.com/{graph_id}",
        subject=subject,
        created_at=1.0,
    )


def test_empty_registry_lists_empty(tmp_path: Path) -> None:
    registry = DraftRegistry(profile="default", base_dir=tmp_path)
    assert registry.list_all() == []


def test_add_and_list(tmp_path: Path) -> None:
    registry = DraftRegistry(profile="default", base_dir=tmp_path)
    registry.add(_entry("a"))
    registry.add(_entry("b", subject="second"))
    entries = registry.list_all()
    assert {e.graph_id for e in entries} == {"a", "b"}


def test_get_by_graph_id(tmp_path: Path) -> None:
    registry = DraftRegistry(profile="default", base_dir=tmp_path)
    registry.add(_entry("a", subject="alpha"))
    found = registry.get("a")
    assert found is not None
    assert found.subject == "alpha"
    assert registry.get("missing") is None


def test_add_replaces_existing(tmp_path: Path) -> None:
    registry = DraftRegistry(profile="default", base_dir=tmp_path)
    registry.add(_entry("a", subject="v1"))
    registry.add(_entry("a", subject="v2"))
    entries = registry.list_all()
    assert len(entries) == 1
    assert entries[0].subject == "v2"


def test_remove_returns_entry(tmp_path: Path) -> None:
    registry = DraftRegistry(profile="default", base_dir=tmp_path)
    registry.add(_entry("a"))
    removed = registry.remove("a")
    assert removed is not None
    assert removed.graph_id == "a"
    assert registry.list_all() == []


def test_remove_missing_returns_none(tmp_path: Path) -> None:
    registry = DraftRegistry(profile="default", base_dir=tmp_path)
    assert registry.remove("never-added") is None


def test_per_profile_isolation(tmp_path: Path) -> None:
    a = DraftRegistry(profile="a", base_dir=tmp_path)
    b = DraftRegistry(profile="b", base_dir=tmp_path)
    a.add(_entry("only-in-a"))
    assert {e.graph_id for e in a.list_all()} == {"only-in-a"}
    assert b.list_all() == []


def test_corrupt_file_treated_as_empty(tmp_path: Path) -> None:
    """A garbled file shouldn't blow up the agent — return empty and let the
    user resolve manually if they care."""
    profile_dir = tmp_path / "default"
    profile_dir.mkdir()
    (profile_dir / "drafts.json").write_text("not-valid-json {", encoding="utf-8")
    registry = DraftRegistry(profile="default", base_dir=tmp_path)
    assert registry.list_all() == []
