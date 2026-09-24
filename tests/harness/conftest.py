# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""The harness layer does not run unless somebody says so, in as many words.

These tests create and **permanently delete** messages in a live
Microsoft 365 mailbox — `permanentDelete` skips Deleted Items and is
not recoverable. The mailbox behind the harness credential is a real
one, with real correspondence in it.

Nothing about `./tests/run_tests.sh all` announces that. It is the
obvious thing for a contributor, or a future agent, to type; and any
machine that happens to hold a harness token cache — a developer
laptop, a workspace where an agent runs shell commands — will then
reach the real mailbox from an ordinary-looking test command.

Every other destructive capability in this repo is behind an explicit
consent env var: `OUTLOOK_ALLOW_DRAFTS`, `OUTLOOK_ALLOW_SEND`,
`OUTLOOK_ALLOW_DELETE`, `OUTLOOK_ALLOW_SHARED_MAILBOXES`. The harness
layer was the one that was not. It is now.

The gate lives in `pytest_collection_modifyitems` rather than in a
per-file helper deliberately: a helper has to be remembered by whoever
writes the next harness test, and the one that forgets is the one that
matters. Collection-time skipping covers every test in this directory,
including ones that do not exist yet.

The name is long on purpose. `OUTLOOK_HARNESS=1` is something a person
sets while skim-reading a README; this one cannot be set without
having understood what it does.
"""

from __future__ import annotations

import os
from collections.abc import Iterable

import pytest

#: Set to exactly "true" to allow the harness layer to run.
HARNESS_OPT_IN_ENV = "OUTLOOK_HARNESS_I_KNOW_THIS_HITS_A_REAL_MAILBOX"

# NB: this message deliberately says "permanent-delete" rather than naming
# the Graph endpoint. `tests/unit/test_harness_delete_guard.py` scans harness
# sources for that API name to keep every deletion primitive inside
# `_guard.py`, and prose outside a docstring would read as a violation. The
# scan is right to be strict; the wording bends.
_SKIP_REASON = (
    f"{HARNESS_OPT_IN_ENV} is not set to 'true'. The harness layer creates and "
    f"PERMANENTLY deletes messages in a live Microsoft 365 mailbox — the "
    f"permanent-delete path skips Deleted Items and cannot be undone. Set it "
    f"only if you understand which mailbox your harness credential points at, "
    f"and only for that run:\n\n"
    f"  {HARNESS_OPT_IN_ENV}=true ./tests/run_tests.sh harness\n\n"
    f"CI sets it in the harness job and nowhere else."
)


def harness_opt_in_granted() -> bool:
    """True iff the operator has explicitly opted into the harness layer.

    Strict, matching the `OUTLOOK_ALLOW_*` parser in `auth/flow.py`:
    only the exact string "true" (case-insensitive, trimmed) counts.
    "1", "yes" and "on" do not — a near-miss must fail closed rather
    than turn on a destructive suite by accident.
    """
    return os.environ.get(HARNESS_OPT_IN_ENV, "").strip().lower() == "true"


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: Iterable[pytest.Item],
) -> None:
    """Skip every test in this directory unless the opt-in is granted."""
    del config  # unused
    if harness_opt_in_granted():
        return
    skip = pytest.mark.skip(reason=_SKIP_REASON)
    for item in items:
        item.add_marker(skip)
