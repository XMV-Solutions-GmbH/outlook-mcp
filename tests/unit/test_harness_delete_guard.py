# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""The harness must not be able to delete mail it did not create.

The harness runs unattended, on a schedule, against a real mailbox
that also holds real correspondence, and one of the APIs it exercises
is `permanentDelete` — which skips Deleted Items and is not
recoverable. "We only ever delete ids we created" used to be a
property of how the tests happened to be written. These tests make it
an invariant: the behavioural half pins what the guard does, and the
source-scan half pins that nothing can quietly go around it.

These run in the unit layer deliberately. They must fail on every
contributor's laptop and in every CI run, not only where harness
credentials exist — a guard that is only checked when the dangerous
path is live is checked too late.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import httpx
import pytest
import respx

from tests.harness._guard import (
    HARNESS_SUBJECT_MARKER,
    HarnessSafetyError,
    assert_deletable,
    assert_shared_mailbox_is_not_the_signed_in_one,
    guarded_delete,
    is_harness_owned,
    register_created,
)

HARNESS_DIR = Path(__file__).resolve().parents[1] / "harness"
GUARD_FILE = HARNESS_DIR / "_guard.py"
MESSAGES_URL = re.compile(r"https://graph\.microsoft\.com/v1\.0/me/messages/.*")


@pytest.fixture
def headers() -> dict[str, str]:
    return {"Authorization": "Bearer AT"}


# ---------------------------------------------------------------------
# What the guard lets through, and what it refuses
# ---------------------------------------------------------------------


def test_marker_recognises_a_harness_subject() -> None:
    assert is_harness_owned(f"{HARNESS_SUBJECT_MARKER}a1b2c3d4e5f6] do not deliver")


@pytest.mark.parametrize(
    "subject",
    [
        None,
        "",
        "Rechnung 2026-09",
        "Re: Termin Frau Dr. Meyer",
        # Near-misses: the marker is a prefix with a trailing space.
        "[outlook-mcp-harnessed abc] nope",
        "outlook-mcp-harness abc",
    ],
)
def test_marker_refuses_everything_else(subject: str | None) -> None:
    assert not is_harness_owned(subject)


@respx.mock
def test_refuses_a_message_the_harness_never_created(headers: dict[str, str]) -> None:
    """The scenario the guard exists for: an id that arrived from a
    search result or a mistyped variable, pointing at real mail."""
    respx.get(MESSAGES_URL).respond(json={"id": "REAL", "subject": "Re: Befund"})

    with httpx.Client() as client, pytest.raises(HarnessSafetyError) as excinfo:
        assert_deletable(client, headers, "REAL")

    assert "Re: Befund" in str(excinfo.value)


@respx.mock
def test_refuses_when_ownership_cannot_be_proven(headers: dict[str, str]) -> None:
    """Fails closed. An unreadable subject is not evidence of anything,
    and the two outcomes are not symmetric: an orphaned test draft
    versus an unrecoverable delete."""
    respx.get(MESSAGES_URL).respond(404)

    with httpx.Client() as client, pytest.raises(HarnessSafetyError):
        assert_deletable(client, headers, "GONE")


@respx.mock
def test_allows_a_message_carrying_the_marker(headers: dict[str, str]) -> None:
    """Covers the soft-delete case: Graph rotates the id on a folder
    move, so the message is ours under an id the ledger never saw."""
    respx.get(MESSAGES_URL).respond(
        json={"id": "ROTATED", "subject": f"{HARNESS_SUBJECT_MARKER}deadbeef] do not deliver"}
    )

    with httpx.Client() as client:
        assert_deletable(client, headers, "ROTATED")  # must not raise


@respx.mock
def test_allows_a_registered_id_without_a_round_trip(headers: dict[str, str]) -> None:
    """The ledger is checked first and is free. It also covers the
    already-deleted case the idempotency tests and the `finally`
    cleanups rely on."""
    register_created("SEEDED")
    route = respx.get(MESSAGES_URL).respond(404)

    with httpx.Client() as client:
        assert_deletable(client, headers, "SEEDED")

    assert route.call_count == 0


@respx.mock
def test_guarded_delete_does_not_issue_the_delete_when_it_refuses(
    headers: dict[str, str],
) -> None:
    """The load-bearing one: a refusal must happen *before* the
    destructive call, not alongside it."""
    respx.get(MESSAGES_URL).respond(json={"id": "REAL", "subject": "Elternabend"})
    delete_route = respx.delete(MESSAGES_URL).respond(204)

    with httpx.Client() as client, pytest.raises(HarnessSafetyError):
        guarded_delete(client, headers, "REAL")

    assert delete_route.call_count == 0, "a refused delete still reached Graph"


# ---------------------------------------------------------------------
# Nothing may go around the guard
# ---------------------------------------------------------------------


def _harness_sources() -> list[Path]:
    return sorted(p for p in HARNESS_DIR.glob("*.py") if p != GUARD_FILE)


def _docstring_line_numbers(tree: ast.AST) -> set[int]:
    """Line numbers occupied by docstrings.

    The scans below look for deletion primitives in *code*. Prose that
    names one — "permanent=True calls POST /{path}/permanentDelete" —
    is documentation doing its job, and flagging it would push authors
    to stop describing the dangerous path accurately.
    """
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = getattr(node, "body", [])
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
            and first.end_lineno is not None
        ):
            lines.update(range(first.lineno, first.end_lineno + 1))
    return lines


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """Every line of `path` that is neither a comment nor a docstring."""
    source = path.read_text()
    skip = _docstring_line_numbers(ast.parse(source))
    return [
        (i, line)
        for i, line in enumerate(source.splitlines(), start=1)
        if i not in skip and not line.lstrip().startswith("#")
    ]


def test_there_are_harness_sources_to_scan() -> None:
    """Guard against the scans below passing vacuously."""
    assert _harness_sources()


@pytest.mark.parametrize(
    ("pattern", "what"),
    [
        (r"\bdelete_message\s*\(", "a direct call to the ol_email_delete tool"),
        (r"\.delete\s*\(", "a raw HTTP DELETE"),
        (r"permanentDelete", "a raw permanentDelete request"),
    ],
)
def test_no_harness_test_deletes_without_the_guard(pattern: str, what: str) -> None:
    """Every deletion primitive lives in `_guard.py` and nowhere else.

    A future refactor that reaches for one directly fails here, in the
    unit layer, instead of reaching a real mailbox. `\\b` before
    `delete_message` is what lets `guarded_delete_message(` through
    while catching the unwrapped call.
    """
    offenders = [
        f"{path.name}:{i}"
        for path in _harness_sources()
        for i, line in _code_lines(path)
        if re.search(pattern, line)
    ]
    assert offenders == [], f"{what} outside the guard, at: {offenders}"


def test_every_seeded_message_is_registered_in_the_ledger() -> None:
    """A seeding helper that forgets `register_created` would still
    work — the marker check would carry it — but it would spend a
    Graph round-trip per delete and, worse, silently weaken the
    ledger half of the proof. Any helper that POSTs a message must
    register what it created."""
    unregistered: list[str] = []
    for path in _harness_sources():
        source = path.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            body = ast.get_source_segment(source, node) or ""
            posts_a_message = re.search(r"client\.post\(\s*\n?\s*f?\"[^\"]*/messages\"", body)
            if posts_a_message and "register_created(" not in body:
                unregistered.append(f"{path.name}:{node.name}")
    assert unregistered == [], (
        f"these helpers create messages without registering them: {unregistered}"
    )


# ---------------------------------------------------------------------
# Shared-mailbox targeting
# ---------------------------------------------------------------------


def _token_for(upn: str) -> str:
    import base64
    import json

    def seg(obj: dict[str, object]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{seg({'alg': 'none'})}.{seg({'upn': upn})}.sig"


def test_shared_mailbox_may_not_be_the_signed_in_identity() -> None:
    """Pointing the shared-mailbox tests at the harness's own mailbox
    both destroys their meaning and turns them into deletes against
    the signed-in account's mail."""
    with pytest.raises(HarnessSafetyError) as excinfo:
        assert_shared_mailbox_is_not_the_signed_in_one(
            _token_for("harness@example.test"), "harness@example.test"
        )
    assert "OUTLOOK_HARNESS_SHARED_MAILBOX_UPN" in str(excinfo.value)


def test_shared_mailbox_comparison_ignores_case_and_whitespace() -> None:
    with pytest.raises(HarnessSafetyError):
        assert_shared_mailbox_is_not_the_signed_in_one(
            _token_for("Harness@Example.test"), "  harness@example.TEST  "
        )


def test_a_genuinely_different_mailbox_is_allowed() -> None:
    assert_shared_mailbox_is_not_the_signed_in_one(
        _token_for("harness@example.test"), "sekretariat@example.test"
    )


def test_an_unreadable_token_does_not_block_the_run() -> None:
    """An opaque token yields no UPN, so there is nothing to compare.
    This check is a misconfiguration catcher, not the thing protecting
    the mailbox — the marker guard does that on every delete, and it
    does not depend on reading the token."""
    assert_shared_mailbox_is_not_the_signed_in_one("opaque-not-a-jwt", "anything@example.test")
