# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Persistent registry of drafts created by this MCP profile.

Tracks the email + calendar-event drafts created by future v0.2 draft
tools so `ol_status` can list them and `ol_email_update_draft` /
`ol_email_discard_draft` can be defensive — only updating or
discarding drafts that *this profile* created. A hand-typed draft the
user is composing in Outlook will never have a matching registry
entry and is therefore protected from accidental MCP-side mutation.

Layout: `<base_dir>/<profile>/drafts.json` with mode 0o600. Atomic
write via temp-file + rename so a crash mid-write doesn't leave a
half-truncated registry.

In v0.1 the registry exists but is always empty (no draft tools
register entries). `ol_status` reads it anyway so the tool surface is
stable across the v0.1 → v0.2 boundary; v0.2 will start populating
entries when the draft-creation tools land.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

DEFAULT_REGISTRY_DIR = Path.home() / ".cache" / "outlook-mcp"

# Process-wide lock for registry mutations. Concurrent draft creation
# (e.g. agent runs many `ol_email_create_draft` calls in flight) does
# a non-atomic read-modify-write (list_all → mutate → _write).
# Without this lock, two concurrent adds can stomp each other and
# lose entries. Held only for the duration of each mutation;
# underlying I/O is fast.
_REGISTRY_LOCK = threading.Lock()

DraftKind = Literal["email", "event"]


@dataclass(frozen=True)
class DraftEntry:
    """One row in the per-profile draft registry.

    `kind` distinguishes email drafts (in the user's Drafts folder)
    from calendar event drafts (tentative events on a calendar with
    `responseRequested=False`). `graph_id` is the Microsoft Graph
    resource id; `web_url` is the human-clickable Outlook URL where
    the user reviews + sends manually.
    """

    kind: DraftKind
    graph_id: str
    web_url: str | None
    subject: str
    created_at: float  # epoch seconds


class DraftRegistry:
    """File-backed registry of drafts, scoped to one profile."""

    def __init__(self, profile: str, base_dir: Path | None = None) -> None:
        self._dir = (base_dir if base_dir is not None else DEFAULT_REGISTRY_DIR) / profile
        self._registry_file = self._dir / "drafts.json"

    def list_all(self) -> list[DraftEntry]:
        """Return every currently-tracked entry. Empty list if none."""
        if not self._registry_file.exists():
            return []
        try:
            raw = json.loads(self._registry_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # Corrupt file — treat as empty rather than crash. Caller can
            # delete the registry to recover.
            return []
        return [DraftEntry(**row) for row in raw]

    def get(self, graph_id: str) -> DraftEntry | None:
        for entry in self.list_all():
            if entry.graph_id == graph_id:
                return entry
        return None

    def add(self, entry: DraftEntry) -> None:
        """Add or replace the entry for `entry.graph_id`. Thread-safe."""
        with _REGISTRY_LOCK:
            existing = [e for e in self.list_all() if e.graph_id != entry.graph_id]
            existing.append(entry)
            self._write(existing)

    def remove(self, graph_id: str) -> DraftEntry | None:
        """Remove the entry for `graph_id`. Returns the removed entry, or None.
        Thread-safe."""
        with _REGISTRY_LOCK:
            existing = self.list_all()
            match = next((e for e in existing if e.graph_id == graph_id), None)
            if match is None:
                return None
            remaining = [e for e in existing if e.graph_id != graph_id]
            self._write(remaining)
        return match

    def _write(self, entries: list[DraftEntry]) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        # Atomic write: temp file in same directory, then rename.
        fd, tmp_path = tempfile.mkstemp(
            prefix="drafts-",
            suffix=".json.tmp",
            dir=self._dir,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump([asdict(e) for e in entries], f, indent=2)
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, self._registry_file)
        except OSError:
            try:
                Path(tmp_path).unlink()
            except FileNotFoundError:
                pass
            raise


def now() -> float:
    """Wall-clock epoch seconds; injectable for tests."""
    return time.time()
