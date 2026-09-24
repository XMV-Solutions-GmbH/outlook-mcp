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

Checks every profile the workflow actually restored, named in
`HARNESS_PROFILES`, rather than one hardcoded profile. The harness has
two — work/school and personal — and covering only the first left the
second free to die the same quiet death.

Deliberately account-agnostic: it never names a mailbox, so whichever
identities end up behind the harness secrets it keeps working.
"""

from __future__ import annotations

import os
import sys

# Safe read-only defaults, set before anything imports the auth stack.
# `get_token` refreshes an expired token, which calls `resolve_scopes()`,
# which refuses to run without an explicit OUTLOOK_ALLOW_DRAFTS /
# OUTLOOK_ALLOW_SEND decision. `tests/conftest.py` does the same thing
# for the test layers; this script is standalone and has to do it
# itself, or it fails with a consent-configuration error and never
# reaches the question it exists to answer. `setdefault`, so a caller
# who has already decided keeps their decision.
os.environ.setdefault("OUTLOOK_ALLOW_DRAFTS", "false")
os.environ.setdefault("OUTLOOK_ALLOW_SEND", "false")
# CI runners have no OS keyring.
os.environ.setdefault("OUTLOOK_TOKEN_STORE", "file")

from outlook_mcp.auth import AuthRequiredError, get_token
from outlook_mcp.auth.store import PlainFileTokenStore

# Comma-separated profile names, set by the workflow from the secrets
# it actually restored. Defaulting to the work/school profile keeps a
# bare local `python scripts/harness_preflight.py` useful.
PROFILES_ENV = "HARNESS_PROFILES"
DEFAULT_PROFILES = ("harness",)

_RENEWAL_HINT = (
    "The harness credential could not obtain an access token. This is a "
    "credential problem, not a code problem — nothing in this pull request "
    "caused it.\n"
    "Microsoft Entra expires a refresh token after 90 days of inactivity, so "
    "a credential that is never redeemed dies on its own; the scheduled run "
    "exists to prevent exactly that.\n"
    "To fix: sign in again for that harness identity, then update the "
    "matching repository secret with the new base64-encoded token.json. "
    "See scripts/renew-harness-token.sh."
)


def _profiles() -> tuple[str, ...]:
    """Profiles to check, from `HARNESS_PROFILES`."""
    raw = os.environ.get(PROFILES_ENV, "")
    named = tuple(part.strip() for part in raw.split(",") if part.strip())
    return named or DEFAULT_PROFILES


def _check(profile: str) -> bool:
    """True if `profile` can still obtain an access token."""
    try:
        token = get_token(profile=profile, store=PlainFileTokenStore())
    except AuthRequiredError as exc:
        # ::error:: renders as an annotation on the run summary, so the
        # cause is visible without opening the log.
        print(f"::error title=Harness credential unusable ({profile})::{exc}", file=sys.stderr)
        return False
    except Exception as exc:
        # Anything else — a malformed cache file, a network failure, a
        # misconfiguration — still has to arrive as one readable line
        # rather than a traceback that looks like a code defect.
        print(
            f"::error title=Harness credential could not be checked ({profile})::{exc!r}",
            file=sys.stderr,
        )
        return False

    if not token:
        print(
            f"::error title=Harness credential unusable ({profile})::"
            "the auth pipeline returned an empty access token",
            file=sys.stderr,
        )
        return False

    print(f"Harness credential for profile {profile!r} is alive.")
    return True


def main() -> int:
    """Return 0 if every configured harness credential works, 1 otherwise.

    Checks all of them before reporting, rather than stopping at the
    first failure: if both credentials have expired, one run should
    say so once, not send somebody round the loop twice.
    """
    profiles = _profiles()
    failed = [profile for profile in profiles if not _check(profile)]
    if failed:
        print(
            f"Unusable harness credential(s): {', '.join(failed)}.\n{_RENEWAL_HINT}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
