#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Fail fast, and legibly, when the harness credential is unusable.

Run in CI after the harness token cache has been restored from its
secret, before the harness test layer. It answers one question — can
this credential still obtain an access token — and turns the answer
into an exit code.

Why it exists (#89). The first harness test to call `get_token()` with
a dead refresh token trips `RefreshTokenInvalidError`, and `get_token`
then deletes the cache entry, by design: an unusable entry should not
linger. On a CI runner that has the side effect of removing the file
every later test guards on, so ten of them skip with "Harness token
cache missing" — a message about a fresh contributor's laptop, not
about a credential that died in Entra. One root cause presented as two
failures and ten misleading skips, which reads as flakiness.

Checking once, up front, collapses that into a single message naming
the credential and how to replace it.

Deliberately account-agnostic: it never names a mailbox, so whichever
identity ends up behind `OUTLOOK_HARNESS_TOKEN_JSON` it keeps working.
"""

from __future__ import annotations

import sys

from outlook_mcp.auth import AuthRequiredError, get_token
from outlook_mcp.auth.store import PlainFileTokenStore

HARNESS_PROFILE = "harness"

_RENEWAL_HINT = (
    "The harness credential could not obtain an access token. This is a "
    "credential problem, not a code problem — nothing in this pull request "
    "caused it.\n"
    "Microsoft Entra expires a refresh token after 90 days of inactivity, so "
    "a credential that is never redeemed dies on its own; the scheduled run "
    "exists to prevent exactly that.\n"
    "To fix: sign in again for the harness identity, then update the "
    "OUTLOOK_HARNESS_TOKEN_JSON repository secret with the new "
    "base64-encoded token.json. See scripts/renew-harness-token.sh."
)


def main() -> int:
    """Return 0 if the harness credential still works, 1 otherwise."""
    try:
        token = get_token(profile=HARNESS_PROFILE, store=PlainFileTokenStore())
    except AuthRequiredError as exc:
        # ::error:: renders as an annotation on the run summary, so the
        # cause is visible without opening the log.
        print(f"::error title=Harness credential unusable::{exc}", file=sys.stderr)
        print(_RENEWAL_HINT, file=sys.stderr)
        return 1

    if not token:
        print(
            "::error title=Harness credential unusable::"
            "the auth pipeline returned an empty access token",
            file=sys.stderr,
        )
        print(_RENEWAL_HINT, file=sys.stderr)
        return 1

    print("Harness credential is alive; the access token was obtained successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
