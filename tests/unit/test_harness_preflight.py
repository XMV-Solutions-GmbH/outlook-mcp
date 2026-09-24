# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Which harness profiles the preflight checks.

The workflow builds `HARNESS_PROFILES` from the secrets it actually
restored, which means the value legitimately arrives with empty slots
and stray separators — `"harness,"` when only the work/school secret
is set, `",harness-personal"` when only the personal one is. Parsing
that wrongly would silently check nothing, and a preflight that
checks nothing passes.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "harness_preflight.py"


def _load() -> object:
    spec = importlib.util.spec_from_file_location("harness_preflight", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["harness_preflight"] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("harness,harness-personal", ("harness", "harness-personal")),
        # Only the work/school secret is configured.
        ("harness,", ("harness",)),
        # Only the personal one is.
        (",harness-personal", ("harness-personal",)),
        # Whitespace from a folded YAML scalar.
        (" harness , harness-personal ", ("harness", "harness-personal")),
    ],
)
def test_profiles_parsed_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: tuple[str, ...]
) -> None:
    monkeypatch.setenv("HARNESS_PROFILES", value)
    module = _load()
    assert module._profiles() == expected  # type: ignore[attr-defined]


def test_unset_falls_back_to_the_work_school_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """So a bare `python scripts/harness_preflight.py` on a laptop
    still checks something useful."""
    monkeypatch.delenv("HARNESS_PROFILES", raising=False)
    module = _load()
    assert module._profiles() == ("harness",)  # type: ignore[attr-defined]


def test_an_all_empty_value_never_yields_an_empty_check_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A preflight with nothing to check would pass vacuously."""
    monkeypatch.setenv("HARNESS_PROFILES", " , ")
    module = _load()
    assert module._profiles() == ("harness",)  # type: ignore[attr-defined]
