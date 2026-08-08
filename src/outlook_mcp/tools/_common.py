# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Shared helpers across `ol_*` tool modules.

Default Microsoft Graph base URL + utilities for building the auth
header and addressing the right mailbox.

Every Graph request carries a `User-Agent: mcp-server-outlook/<version>`
header in addition to the bearer token. The audit-trail rationale is
in docs/spikes/2026-05-08-v02-drafts-spikes.md § 2: ClientAppId +
AppDisplayName already identify the calling app inside Microsoft 365
audit logs, but a self-identifying User-Agent makes raw Graph
diagnostics readable too — a compliance reviewer scrolling through
sign-in / activity logs sees the server name immediately.

Naming uses leading underscore at the module level to flag "internal
to the tools/ subpackage".
"""

from __future__ import annotations

import re
from urllib.parse import quote

from outlook_mcp import __version__

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
USER_AGENT = f"mcp-server-outlook/{__version__}"

# `mailbox="group:<group-id>"` selects a Microsoft 365 group mailbox.
# A prefix rather than a bare id because the value has to stay
# unambiguous against a UPN, and because the two route to different
# Graph surfaces entirely — see `is_group_mailbox`.
GROUP_PREFIX = "group:"

# Entra object ids are GUIDs. Validated rather than passed through so a
# malformed value fails here with a readable message instead of as an
# opaque Graph 400, and so nothing can be smuggled into the URL path.
_GUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def is_group_mailbox(mailbox: str | None) -> bool:
    """True iff `mailbox` addresses a Microsoft 365 group mailbox.

    Group mail is NOT reachable under `/users/{upn}/` — Exchange
    rejects that with `ErrorGroupIsUsedInNonGroupURI` — so this is a
    routing decision, not a permissions one.
    """
    return mailbox is not None and mailbox.strip().lower().startswith(GROUP_PREFIX)


def group_id(mailbox: str) -> str:
    """Extract and validate the group id from `group:<group-id>`.

    Raises `ValueError` if the value is not `group:` followed by a GUID.

    The id is required because a group's *address* cannot be resolved to
    its id without a directory-read scope (`/groups?$filter=mail eq …`
    answers 403 under this server's permissions), and requesting one
    just to look up a name would be a far larger consent ask than
    reading the conversations themselves. Callers pass the id.
    """
    raw = mailbox.strip()
    if not raw.lower().startswith(GROUP_PREFIX):
        raise ValueError(f"not a group mailbox: {mailbox!r}")
    candidate = raw[len(GROUP_PREFIX) :].strip()
    if not _GUID_RE.match(candidate):
        raise ValueError(
            f"group mailbox must be 'group:<group-id>' where <group-id> is the "
            f"group's Entra object id (a GUID); got {candidate!r}. "
            f"A group's e-mail address cannot be used here: resolving an "
            f"address to an id needs a directory-read permission this server "
            f"deliberately does not request.",
        )
    return candidate


def group_path(mailbox: str) -> str:
    """Return the Graph URL fragment addressing a group mailbox."""
    return f"groups/{group_id(mailbox)}"


def auth_headers(token: str) -> dict[str, str]:
    """Build the standard headers for Graph requests.

    Includes the bearer token and a self-identifying User-Agent. Every
    `ol_*` tool routes its outbound HTTP through here, so the
    audit-trail label is consistent.
    """
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
    }


def mailbox_path(mailbox: str | None) -> str:
    """Return the Graph URL fragment that addresses the right mailbox.

    `mailbox=None` (the default) → `"me"` — the signed-in user, exactly
    the behaviour the server had pre-v0.5 and still has when
    `OUTLOOK_ALLOW_SHARED_MAILBOXES=false` (or unset).

    `mailbox="<upn>"` → `"users/{upn-url-quoted}"` — a delegated mailbox
    that the signed-in user has FullAccess on via Exchange's
    `Add-MailboxPermission`. Requires `Mail.ReadWrite.Shared` in the
    OAuth scope (the server adds it automatically when SHARED_MAILBOXES
    is enabled; see auth/flow.py:resolve_scopes).

    The caller composes with f-strings, e.g.:

        f"{GRAPH_BASE}/{mailbox_path(mailbox)}/messages"

    URL-quotes the `@` and `.` in the UPN so a hostile mailbox value
    can't smuggle path traversal into the Graph URL — Graph itself
    accepts the decoded form, but we don't want surprise behaviour if
    the value flows through other clients first.

    Raises `ValueError` if `mailbox` is provided but empty/whitespace,
    or if it addresses a group (`group:<id>`) — group mail does not live
    under `/users/` and the caller must route it via `group_path`.
    """
    if mailbox is None:
        return "me"
    cleaned = mailbox.strip()
    if not cleaned:
        raise ValueError(
            "mailbox must be a non-empty UPN (e.g. 'shared@contoso.com') or None",
        )
    if is_group_mailbox(cleaned):
        raise ValueError(
            "group mailboxes are not addressable under /users/ — route via "
            "group_path(). Microsoft Exchange rejects the /users/ form with "
            "ErrorGroupIsUsedInNonGroupURI.",
        )
    return f"users/{quote(cleaned, safe='@.+-_')}"
