# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Refuse to delete anything the harness did not create.

Every harness test that deletes a message deletes an id it got back
from its own `POST /messages` a few lines earlier, so today nothing
can reach real mail. That safety is a property of how the tests
happen to be written, not something enforced — and the harness runs
unattended, on a schedule, against a **real mailbox** that also holds
real correspondence. One refactor that deletes by search result, or
one id threaded through the wrong variable, and the blast radius is a
permanent, unrecoverable delete of somebody's mail.

This module turns that convention into an invariant. Deletion has two
independent proofs of ownership, and a delete needs one of them:

1. **The ledger.** `_create_throwaway_draft` registers every id it
   creates. Re-deleting a registered id is always allowed — including
   after it has already been deleted, which is exactly what the
   idempotency tests and the best-effort `finally` cleanups do.
2. **The subject marker.** For any id the ledger has not seen, the
   subject is read back from Graph and must carry
   `[outlook-mcp-harness `. An id that arrived from a search result,
   a folder listing, or a mistyped variable has to clear this bar,
   and a real message never will.

Ownership by ledger is checked first because it is free; the marker
check costs a round-trip and exists for the case the ledger cannot
cover — notably a soft delete, after which Graph rotates the id, so
the moved message is ours but under an id we have never seen.

Failing closed is deliberate. An unregistered id whose subject cannot
be read at all is refused. The cost of refusing a delete that would
have been fine is an orphaned test draft with an obvious marker in
its subject; the cost of allowing one that should have been refused
is unrecoverable. Those are not comparable.

The refusal is an error, never a skip: a harness run that tried to
delete an unmarked message is a bug worth failing loudly for, and a
skip would hide it.
"""

from __future__ import annotations

from typing import Any

import httpx

from outlook_mcp.auth.identity import upn_from_access_token
from outlook_mcp.tools._common import GRAPH_BASE, mailbox_path
from outlook_mcp.tools.email_delete import delete_message as _delete_message_tool

# Stamped into the subject of everything the harness creates. The
# trailing space is part of it: real subjects read
# `[outlook-mcp-harness a1b2c3d4e5f6] do not deliver`, and matching
# without it would also match a hypothetical `[outlook-mcp-harnessed …]`.
HARNESS_SUBJECT_MARKER = "[outlook-mcp-harness "

# Ids this process created. Never cleared between tests on purpose:
# a test's `finally` cleanup, and the idempotency tests' second
# delete, both act on ids whose messages are already gone.
_created_ids: set[str] = set()


class HarnessSafetyError(AssertionError):
    """A harness test tried to delete a message it did not create.

    Derives from `AssertionError` so pytest reports it as a test
    failure rather than an infrastructure error — the suite attempted
    something it must never attempt, which is what a failing assertion
    is for. It is also why `except httpx.HTTPStatusError` cleanup
    blocks do not swallow it.
    """


def register_created(message_id: str) -> None:
    """Record that the harness created `message_id`, so it may be deleted."""
    _created_ids.add(message_id)


def was_created_by_harness(message_id: str) -> bool:
    """True iff `message_id` was registered by `register_created`."""
    return message_id in _created_ids


def is_harness_owned(subject: str | None) -> bool:
    """True iff `subject` marks a message this harness created.

    None and empty subjects are not owned: a message whose subject
    cannot be shown to be ours fails closed.
    """
    return bool(subject) and HARNESS_SUBJECT_MARKER in str(subject)


def fetch_subject(
    client: httpx.Client,
    headers: dict[str, str],
    message_id: str,
    *,
    mailbox: str | None = None,
) -> str | None:
    """Read back one message's subject, or None if it cannot be read.

    None covers every "cannot prove ownership" case — a 404, a
    transport error, a malformed body — and each of them means the
    caller must refuse.
    """
    box = mailbox_path(mailbox)
    try:
        response = client.get(
            f"{GRAPH_BASE}/{box}/messages/{message_id}",
            headers=headers,
            params={"$select": "id,subject"},
        )
        if response.status_code != 200:
            return None
        payload = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    subject = payload.get("subject")
    return subject if isinstance(subject, str) else None


def assert_deletable(
    client: httpx.Client,
    headers: dict[str, str],
    message_id: str,
    *,
    mailbox: str | None = None,
) -> None:
    """Raise `HarnessSafetyError` unless `message_id` is ours to delete."""
    if was_created_by_harness(message_id):
        return

    subject = fetch_subject(client, headers, message_id, mailbox=mailbox)
    if subject is None:
        raise HarnessSafetyError(
            f"refusing to delete message {message_id!r}: the harness did not "
            f"create it and its subject could not be read back, so ownership "
            f"cannot be proven. The harness only ever deletes messages it "
            f"seeded itself — anything else is a bug in the test, not a "
            f"transient failure to retry."
        )
    if not is_harness_owned(subject):
        raise HarnessSafetyError(
            f"refusing to delete message {message_id!r}: its subject "
            f"({subject!r}) does not carry {HARNESS_SUBJECT_MARKER!r} and the "
            f"harness never created it. This mailbox holds real mail; a harness "
            f"test must never delete a message it did not seed."
        )


def guarded_delete(
    client: httpx.Client,
    headers: dict[str, str],
    message_id: str,
    *,
    mailbox: str | None = None,
) -> None:
    """Delete `message_id` straight through Graph — ours only."""
    assert_deletable(client, headers, message_id, mailbox=mailbox)
    box = mailbox_path(mailbox)
    client.delete(f"{GRAPH_BASE}/{box}/messages/{message_id}", headers=headers)


def guarded_delete_message(
    message_id: str,
    *,
    client: httpx.Client,
    headers: dict[str, str],
    permanent: bool = False,
    mailbox: str | None = None,
    profile: str,
) -> dict[str, Any]:
    """Call the `ol_email_delete` tool under test — ours only.

    The tool is what these tests exist to exercise, so this is a
    pass-through, not a replacement: ownership is proven first, then
    the real `delete_message` runs and its result is returned
    unchanged. `permanent=True` routes to `permanentDelete`, which
    skips Deleted Items entirely — the path that most needs the
    guard in front of it.
    """
    assert_deletable(client, headers, message_id, mailbox=mailbox)
    return _delete_message_tool(
        message_id,
        permanent=permanent,
        mailbox=mailbox,
        profile=profile,
    )


def assert_shared_mailbox_is_not_the_signed_in_one(access_token: str, shared_upn: str) -> None:
    """Refuse a shared-mailbox target that is the harness's own mailbox.

    The shared-mailbox tests are the destructive ones aimed at a
    mailbox that is, by definition, not the signed-in account's. If
    `OUTLOOK_HARNESS_SHARED_MAILBOX_UPN` is pointed at the harness
    identity itself, two things go wrong at once: the tests stop
    testing anything (their whole point is asserting that
    `/users/{upn}/` routing did NOT land on `/me/`), and a
    misconfiguration quietly turns them into deletes against the
    harness account's own mail.

    Deliberately compares against the signed-in identity read from the
    token at runtime, rather than against a list of known addresses.
    This is a public repository: a hardcoded allow/deny list would put
    real people's mailbox addresses in public source, and it would go
    stale the moment the harness identity changes. Reading the `upn`
    claim costs nothing and is always current.

    Note the limit, so nobody assumes more than it gives: this
    compares UPNs. A proxy address or SMTP alias of the same mailbox
    is a different string and will not be caught here. The marker
    guard is what actually protects the mailbox contents, on every
    delete, whatever the routing; this check is about catching an
    obviously wrong configuration early and with a clear message.
    """
    signed_in = upn_from_access_token(access_token)
    if signed_in is None:
        return
    if shared_upn.strip().lower() == signed_in.strip().lower():
        raise HarnessSafetyError(
            f"refusing to run shared-mailbox tests against {shared_upn!r}: that is "
            f"the signed-in harness identity's own mailbox. These tests create and "
            f"permanently delete messages in the mailbox they are pointed at, and "
            f"they assert that routing did not fall back to /me — both of which "
            f"require a genuinely different mailbox. Unset "
            f"OUTLOOK_HARNESS_SHARED_MAILBOX_UPN, or point it at a mailbox "
            f"provisioned for testing."
        )
