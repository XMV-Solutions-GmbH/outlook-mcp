# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Harness tests for ol_email_delete (#45) — real Microsoft Graph.

Per ENGINEERING_PRINCIPLES § 5 and the user-side rule "harness tests
for new Graph API tools ship in the same PR as the implementation":
mocks are tautological, only real Graph catches the
URL-shape / scope / status-code-on-edge contract violations.

Each test seeds its own draft (POST /me/messages — never sent, never
leaves the tenant) so the suite is self-contained: no precondition on
inbox contents, no race against other tests.

Cleanup is best-effort in `finally` blocks. Microsoft Graph caps
Drafts at ~250k items per mailbox, so even a totally broken harness
run that leaves stragglers behind doesn't accumulate into a problem
fast.

The shared-mailbox tests skip silently unless
`OUTLOOK_HARNESS_SHARED_MAILBOX_UPN` is set to a mailbox the harness
identity has FullAccess on — otherwise we'd require every fresh
contributor to provision a shared mailbox in their tenant just to
make the harness suite green.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from outlook_mcp.auth import get_token
from outlook_mcp.auth.store import PlainFileTokenStore
from outlook_mcp.tools._common import GRAPH_BASE, auth_headers, mailbox_path
from outlook_mcp.tools.email_delete import delete_message

HARNESS_PROFILE = "harness"
SHARED_MAILBOX_ENV = "OUTLOOK_HARNESS_SHARED_MAILBOX_UPN"


def _harness_cache_path() -> Path:
    return Path.home() / ".cache" / "outlook-mcp" / HARNESS_PROFILE / "token.json"


def _skip_if_no_harness() -> None:
    if not _harness_cache_path().exists() and not os.environ.get("OUTLOOK_HARNESS_TOKEN_JSON"):
        pytest.skip(
            "Harness token cache missing. Run `./scripts/renew-harness-token.sh` or set "
            "OUTLOOK_HARNESS_TOKEN_JSON.",
        )


def _token() -> str:
    os.environ.setdefault("OUTLOOK_TOKEN_STORE", "file")
    return get_token(profile=HARNESS_PROFILE, store=PlainFileTokenStore())


def _create_throwaway_draft(
    client: httpx.Client,
    headers: dict[str, str],
    mailbox: str | None = None,
) -> tuple[str, str]:
    """POST a uniquely-titled draft directly via Graph.

    Returns `(message_id, subject_marker)`. The marker is the unique
    uuid suffix in the subject; it survives folder moves where the id
    rotates, so cross-folder lookups can use it.

    No `send` call follows — the draft sits in Drafts until our test
    deletes it. The body identifies the message as harness-generated
    so anyone reviewing the test mailbox manually knows it's safe to
    purge.
    """
    marker = uuid.uuid4().hex[:12]
    box = mailbox_path(mailbox)
    response = client.post(
        f"{GRAPH_BASE}/{box}/messages",
        headers={**headers, "Content-Type": "application/json"},
        json={
            "subject": f"[outlook-mcp-harness {marker}] do not deliver",
            "body": {
                "contentType": "text",
                "content": (
                    "This draft was created by outlook-mcp's harness suite "
                    f"(marker {marker}). It is safe to delete."
                ),
            },
            # toRecipients deliberately empty — the draft can be saved but
            # not sent, which is exactly what we want.
        },
    )
    response.raise_for_status()
    return str(response.json()["id"]), marker


def _find_in_folder(
    client: httpx.Client,
    headers: dict[str, str],
    folder: str,
    message_id: str,
    mailbox: str | None = None,
) -> dict[str, Any] | None:
    """Look up a message by id inside a specific well-known folder.

    Returns the Graph item dict on hit, None on 404. Used to assert
    "message is no longer in Drafts" — that assertion is reliable
    because the original draft id is valid while the message is in
    Drafts (we just got it from the POST response).

    DO NOT use this to check DeletedItems after a soft delete: empirical
    harness run on 2026-05-23 confirmed that Graph rotates the message
    id when it moves between folders (the immutable-ID feature is
    opt-in via a header we don't send). So a GET by the original id
    against DeletedItems returns 404 even when the message is there.
    """
    box = mailbox_path(mailbox)
    response = client.get(
        f"{GRAPH_BASE}/{box}/mailFolders/{folder}/messages/{message_id}",
        headers=headers,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return dict(response.json())


def _find_by_subject(
    client: httpx.Client,
    headers: dict[str, str],
    folder: str,
    subject_marker: str,
    mailbox: str | None = None,
    *,
    retries: int = 5,
    retry_delay_s: float = 1.0,
) -> dict[str, Any] | None:
    """Find a message in `folder` whose subject contains the unique marker.

    Workaround for the id-rotation-on-folder-move behaviour: after a
    soft delete from Drafts, the message is in DeletedItems with a new
    id. We seeded with a unique uuid in the subject so we can re-find
    it.

    Quirks discovered empirically (2026-05-23):

    - Graph's `$filter contains(subject, '...')` requires
      `ConsistencyLevel: eventual`; without that header Graph silently
      returns zero results instead of failing the query.
    - Even with the header, there is a brief (≤5s) indexing delay
      after a soft-delete folder move before the moved message shows
      up in $filter against DeletedItems. We retry a few times before
      giving up — `None` from this helper is meaningful (definitive
      absence) only after the retry budget is exhausted.

    Returns the first Graph item dict that matches, or None after
    `retries` attempts.
    """
    import time as _time

    box = mailbox_path(mailbox)
    url = f"{GRAPH_BASE}/{box}/mailFolders/{folder}/messages"
    query_headers = {**headers, "ConsistencyLevel": "eventual"}
    params = {
        "$filter": f"contains(subject, '{subject_marker}')",
        "$top": 5,
        "$select": "id,subject",
    }
    for attempt in range(retries):
        response = client.get(url, headers=query_headers, params=params)
        response.raise_for_status()
        items = response.json().get("value", [])
        if items:
            return dict(items[0])
        if attempt < retries - 1:
            _time.sleep(retry_delay_s)
    return None


# ── soft delete: round-trip on /me ────────────────────────────────────────


def test_ol_email_delete_soft_on_me() -> None:
    """ol_email_delete with permanent=False removes the message from
    its source folder. Microsoft Graph documents the destination as
    Deleted Items, but we don't assert that — observed empirically
    (2026-05-23 harness run) that the post-move $filter-by-subject
    lookup has >5s indexing latency for newly soft-deleted drafts,
    which would make the assertion flaky. The load-bearing claim is
    "the message is gone from Drafts after the call", which we DO
    verify deterministically using the original id (still valid pre-
    move).
    """
    _skip_if_no_harness()
    headers = auth_headers(_token())
    with httpx.Client(timeout=30.0) as client:
        draft_id, _marker = _create_throwaway_draft(client, headers)
        try:
            # Sanity: draft is initially in Drafts under its original id.
            initial = _find_in_folder(client, headers, "Drafts", draft_id)
            assert initial is not None, "seed draft not found in Drafts immediately after POST"

            result = delete_message(draft_id, profile=HARNESS_PROFILE)
            assert result == {
                "message_id": draft_id,
                "mailbox": None,
                "permanent": False,
            }

            # Message must no longer be in Drafts.
            assert _find_in_folder(client, headers, "Drafts", draft_id) is None, (
                "soft delete should remove the message from Drafts"
            )
        finally:
            # Cleanup: permanent-delete by the original id. After a soft
            # delete the id is stale (Graph rotates on move), so this
            # will likely 404 — our tool swallows that.
            try:
                delete_message(draft_id, permanent=True, profile=HARNESS_PROFILE)
            except httpx.HTTPStatusError:
                pass


# ── permanent delete: round-trip on /me ───────────────────────────────────


def test_ol_email_delete_permanent_on_me() -> None:
    """permanent=True calls POST /{path}/permanentDelete (the Graph
    v1.0 endpoint that skips Deleted Items and lands in Recoverable
    Items). This is what unblocks the Anqer Fahrtenbuch use case —
    sanitising old PDFs from a shared mailbox without leaving traces
    in Deleted Items.

    Like the soft-delete test we don't assert on the destination
    folder (Recoverable Items isn't queryable via the standard
    /mailFolders surface). We assert: the call succeeds and the
    message is gone from Drafts.
    """
    _skip_if_no_harness()
    headers = auth_headers(_token())
    with httpx.Client(timeout=30.0) as client:
        draft_id, _marker = _create_throwaway_draft(client, headers)
        try:
            result = delete_message(draft_id, permanent=True, profile=HARNESS_PROFILE)
            assert result["permanent"] is True
            assert result["message_id"] == draft_id

            # Gone from Drafts.
            assert _find_in_folder(client, headers, "Drafts", draft_id) is None
        finally:
            # If permanentDelete somehow failed mid-test, the draft may
            # still be in Drafts. Make sure it's gone.
            try:
                delete_message(draft_id, permanent=True, profile=HARNESS_PROFILE)
            except httpx.HTTPStatusError:
                pass


# ── 404 idempotency ───────────────────────────────────────────────────────


def test_ol_email_delete_idempotent_on_me() -> None:
    """Re-deleting a message that's already been permanently deleted is
    a no-op success.

    Round-trip pattern: create draft → permanent-delete → call delete
    AGAIN with the (now-stale) draft id. This uses a real Graph-shape
    id rather than a hand-crafted bogus one — empirical harness run on
    2026-05-23 showed Graph rejects malformed ids with 400 before
    checking existence, so a bogus-id test wouldn't actually exercise
    the 404 idempotency path our tool's `if response.status_code ==
    404` branch promises.
    """
    _skip_if_no_harness()
    headers = auth_headers(_token())
    with httpx.Client(timeout=30.0) as client:
        draft_id, _marker = _create_throwaway_draft(client, headers)

        # First delete: succeeds, message gone.
        delete_message(draft_id, permanent=True, profile=HARNESS_PROFILE)

        # Second delete on the same (now invalid) id: should also
        # report success. This is the load-bearing idempotency contract.
        result = delete_message(draft_id, profile=HARNESS_PROFILE)
        assert result == {
            "message_id": draft_id,
            "mailbox": None,
            "permanent": False,
        }


def test_ol_email_delete_permanent_idempotent_on_me() -> None:
    """Same as above for the permanent=True path."""
    _skip_if_no_harness()
    headers = auth_headers(_token())
    with httpx.Client(timeout=30.0) as client:
        draft_id, _marker = _create_throwaway_draft(client, headers)
        delete_message(draft_id, permanent=True, profile=HARNESS_PROFILE)

        # Re-issue: should succeed silently.
        result = delete_message(draft_id, permanent=True, profile=HARNESS_PROFILE)
        assert result["permanent"] is True


# ── shared-mailbox routing (skipif unless explicitly configured) ──────────


def _shared_mailbox_or_skip() -> Iterator[str]:
    """Yield the shared-mailbox UPN, or skip the test.

    `OUTLOOK_HARNESS_SHARED_MAILBOX_UPN` is set in CI alongside the
    harness token when the test tenant has a Sekretariats-style shared
    mailbox configured. Local contributors without one get a skip,
    not a fail — provisioning a shared mailbox is per-tenant work
    that doesn't belong in a clone-and-test loop.
    """
    upn = os.environ.get(SHARED_MAILBOX_ENV)
    if not upn:
        pytest.skip(
            f"{SHARED_MAILBOX_ENV} not set — skipping shared-mailbox harness tests. "
            "Set the env var to a UPN the harness user has FullAccess on.",
        )
    yield upn


def test_ol_email_delete_soft_on_shared_mailbox() -> None:
    """Round-trip soft delete against a shared mailbox via FullAccess
    delegate. Closes the load-bearing half of #45 — the use case the
    issue was filed for.

    Cross-routing assertion: a seed-draft created in the shared
    mailbox's Drafts MUST NOT be findable in /me/Drafts (would prove
    the /users/{upn}/ routing actually went to /me/). And after the
    soft-delete call, the draft is gone from the shared mailbox's
    Drafts — same load-bearing assertion as the /me variant.
    """
    _skip_if_no_harness()
    shared = next(_shared_mailbox_or_skip())

    headers = auth_headers(_token())
    with httpx.Client(timeout=30.0) as client:
        draft_id, _marker = _create_throwaway_draft(client, headers, mailbox=shared)
        try:
            # Cross-routing cross-check: seed must be in shared Drafts,
            # NOT in /me/Drafts.
            assert (
                _find_in_folder(client, headers, "Drafts", draft_id, mailbox=shared)
                is not None
            ), "seed draft should be in shared mailbox's Drafts"
            assert _find_in_folder(client, headers, "Drafts", draft_id) is None, (
                "shared-mailbox seed must NOT appear in /me/Drafts — would prove "
                "the /users/{upn}/ routing actually went to /me/"
            )

            result = delete_message(
                draft_id,
                mailbox=shared,
                profile=HARNESS_PROFILE,
            )
            assert result == {
                "message_id": draft_id,
                "mailbox": shared,
                "permanent": False,
            }

            # Gone from shared mailbox's Drafts.
            assert (
                _find_in_folder(client, headers, "Drafts", draft_id, mailbox=shared)
                is None
            ), "soft delete on shared mailbox should remove from shared Drafts"
        finally:
            try:
                delete_message(
                    draft_id,
                    mailbox=shared,
                    permanent=True,
                    profile=HARNESS_PROFILE,
                )
            except httpx.HTTPStatusError:
                pass


def test_ol_email_delete_permanent_on_shared_mailbox() -> None:
    _skip_if_no_harness()
    shared = next(_shared_mailbox_or_skip())

    headers = auth_headers(_token())
    with httpx.Client(timeout=30.0) as client:
        draft_id, _marker = _create_throwaway_draft(client, headers, mailbox=shared)
        try:
            result = delete_message(
                draft_id,
                mailbox=shared,
                permanent=True,
                profile=HARNESS_PROFILE,
            )
            assert result["permanent"] is True
            assert result["mailbox"] == shared

            # Gone from shared mailbox's Drafts.
            assert _find_in_folder(client, headers, "Drafts", draft_id, mailbox=shared) is None
        finally:
            try:
                delete_message(
                    draft_id,
                    mailbox=shared,
                    permanent=True,
                    profile=HARNESS_PROFILE,
                )
            except httpx.HTTPStatusError:
                pass
