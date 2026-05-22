# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""ol_email_delete — delete a message from a mailbox.

Two destruction levels:

- `permanent=False` (default): `DELETE /{mailbox}/messages/{id}` →
  Microsoft Graph moves the message to Deleted Items. The user (or
  an admin) can still restore it from the recycle bin via the Outlook
  web UI for the tenant's retention window. This matches the
  "delete-key behaviour" — reversible, audit-trail preserved.

- `permanent=True`: `POST /{mailbox}/messages/{id}/permanentDelete`
  → hard-delete that bypasses Deleted Items and lands the message
  straight in the Recoverable Items "Purges" subfolder. Tenant
  admins with eDiscovery can still recover for ~14 days (or whatever
  the Recoverable Items retention is configured to), but the end
  user cannot. Use for "definitely-throw-away" cases like sanitising
  a Sekretariats-Postfach.

This tool requires `OUTLOOK_ALLOW_DELETE=true`. The `mailbox` parameter
additionally requires `OUTLOOK_ALLOW_SHARED_MAILBOXES=true`; both
guards are enforced by the MCP-tool wrapper in `server.py`.

Implements outlook-mcp #45.

Note on draft-vs-message: this tool is for received / sent / shared-
mailbox messages. To discard a draft you authored via
`ol_email_create_draft`, use `ol_email_discard_draft` instead — that
preserves the per-profile DraftRegistry ownership semantics. There's
no overlap: `ol_email_discard_draft` only operates on registry-owned
drafts; `ol_email_delete` operates on any message id the signed-in
user has Mail.ReadWrite (or .Shared) permission on.
"""

from __future__ import annotations

from typing import Any

import httpx

from outlook_mcp.auth import get_token
from outlook_mcp.tools._common import GRAPH_BASE, auth_headers, mailbox_path


def delete_message(
    message_id: str,
    *,
    mailbox: str | None = None,
    permanent: bool = False,
    profile: str = "default",
    http: httpx.Client | None = None,
) -> dict[str, Any]:
    """Delete a message by Graph id.

    `mailbox=None` (default): the signed-in user's mailbox (`/me/...`).
    `mailbox="<upn>"`: a shared mailbox the signed-in user has
    FullAccess on (`/users/{upn}/...`). The MCP-tool wrapper enforces
    that `mailbox` is only usable when
    `OUTLOOK_ALLOW_SHARED_MAILBOXES=true`.

    `permanent=False` (default): soft delete (Deleted Items).
    `permanent=True`: hard delete (Recoverable Items / Purges).

    Returns a `{"message_id": ..., "mailbox": ..., "permanent": bool}`
    descriptor on success — the same shape regardless of which path
    was taken, so an agent processing the result doesn't have to branch.

    Raises:
        ValueError: empty `message_id`, or empty `mailbox` (non-None
            but whitespace-only).
        httpx.HTTPStatusError: 403 if `mailbox` is set but the signed-in
            user has no FullAccess on it; other non-2xx propagate.
        outlook_mcp.auth.AuthRequiredError: no cached token for
            `profile`.

    Idempotency: re-deleting a message already gone (Graph 404) is
    treated as success — the agent's intent ("make this message go
    away") is already satisfied. Other non-2xx codes raise.
    """
    if not message_id or not message_id.strip():
        raise ValueError("ol_email_delete requires a non-empty message_id")

    box = mailbox_path(mailbox)
    token = get_token(profile)
    headers = auth_headers(token)
    client = http if http is not None else httpx.Client(timeout=30.0)
    try:
        if permanent:
            # /permanentDelete is in Graph v1.0 since 2023 — bypasses
            # Deleted Items entirely. POST with no body.
            url = f"{GRAPH_BASE}/{box}/messages/{message_id}/permanentDelete"
            response = client.post(url, headers=headers)
        else:
            # Plain DELETE — moves to Deleted Items. If the message is
            # already in Deleted Items, Graph's behaviour is to move it
            # to Recoverable Items (effectively permanent). That matches
            # the Outlook UI's behaviour for "delete twice = gone".
            url = f"{GRAPH_BASE}/{box}/messages/{message_id}"
            response = client.delete(url, headers=headers)

        if response.status_code == 404:
            # Already gone. Agent's intent satisfied; report success.
            pass
        else:
            response.raise_for_status()
    finally:
        if http is None:
            client.close()

    return {
        "message_id": message_id,
        "mailbox": mailbox,
        "permanent": permanent,
    }
