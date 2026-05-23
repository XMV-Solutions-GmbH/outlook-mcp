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

from urllib.parse import quote

from outlook_mcp import __version__

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
USER_AGENT = f"mcp-server-outlook/{__version__}"


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

    Raises `ValueError` if `mailbox` is provided but empty/whitespace.
    """
    if mailbox is None:
        return "me"
    cleaned = mailbox.strip()
    if not cleaned:
        raise ValueError(
            "mailbox must be a non-empty UPN (e.g. 'shared@contoso.com') or None",
        )
    return f"users/{quote(cleaned, safe='@.+-_')}"
