# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Shared pytest fixtures + automatic test-layer marker assignment.

Tests are auto-marked by their directory so that `pytest -m unit` (etc.)
filters by layer without each test author having to remember to apply
the marker by hand. The three layers map to the markers declared in
pyproject.toml:

- tests/unit/       -> @pytest.mark.unit
- tests/integration -> @pytest.mark.integration
- tests/harness/    -> @pytest.mark.harness

Layer-specific shared fixtures live in `tests/<layer>/conftest.py`.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

import pytest

# v0.4: the server / CLI refuse to start without explicit
# OUTLOOK_ALLOW_DRAFTS=true|false. Set safe read-only defaults at
# module-import time (before pytest's autouse fixtures fire, before
# any test imports `outlook_mcp.server` which validates at module
# top level). Tests that need to vary the consent decision use
# `monkeypatch.setenv` to override.
os.environ.setdefault("OUTLOOK_ALLOW_DRAFTS", "false")
os.environ.setdefault("OUTLOOK_ALLOW_SEND", "false")


_LAYER_DIRS = ("unit", "integration", "harness")


def pytest_collection_modifyitems(config: pytest.Config, items: Iterable[pytest.Item]) -> None:
    """Apply a layer marker to every collected test based on its path."""
    del config  # unused
    for item in items:
        path_parts = Path(str(item.path)).parts
        for layer in _LAYER_DIRS:
            if layer in path_parts:
                item.add_marker(getattr(pytest.mark, layer))
                break
