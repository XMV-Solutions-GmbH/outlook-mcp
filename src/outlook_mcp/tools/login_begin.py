# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""ol_login_begin — drive the OAuth Device Code flow as an MCP tool.

Async tool that:

1. Returns the existing in-flight session (idempotent) when one is
   already pending for `profile` and `force=False`.
2. Otherwise initiates a fresh Device Code flow (one HTTP round-trip
   to Microsoft Identity), records a `LoginSession` in the
   process-wide registry, and starts polling.
3. Streams progress notifications (`time_remaining_s`) while polling
   when the calling MCP client advertises the progress capability.
   Clients without that capability skip silently — bonus channel.
4. Blocks until the polling task reaches a terminal state
   (success / expired / failed). On success, writes the token to the
   configured TokenStore + populates the UPN cache so subsequent
   `ol_login_status` calls answer locally.

`force=True` cancels any in-flight session for the profile and
starts fresh — replaces the original four-tool RFC's separate
`ol_login_cancel` tool with one less choice for the agent.

Concurrent calls during a pending session for the same profile
return the existing session without re-initiating; the polling task
is started exactly once per session.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

import httpx
from mcp_microsoft_graph_auth import LoginSession, public_view

from outlook_mcp.auth import (
    AuthorizationDeniedError,
    DeviceCodeExpiredError,
)
from outlook_mcp.auth.flow import (
    DEFAULT_AUTHORITY_TENANT,
    DEFAULT_CLIENT_ID,
    poll_for_token,
    request_device_code,
)
from outlook_mcp.auth.store import get_token_store
from outlook_mcp.login_state import cache_upn, get_login_session_registry
from outlook_mcp.tools._common import GRAPH_BASE, auth_headers

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context

_log = logging.getLogger("outlook-mcp.login_begin")


async def login_begin(
    *,
    profile: str = "default",
    force: bool = False,
    ctx: Context[Any, Any] | None = None,
    http: httpx.Client | None = None,
) -> dict[str, Any]:
    """Drive the Device Code flow.

    Returns the public-view dict of the resulting `LoginSession` —
    fields include `session_id`, `user_code`, `verification_url`,
    `verification_url_complete`, `expires_at`, `time_remaining_s`,
    `status`, `signed_in_user_upn`, `error`. Caller renders
    `user_code` first (in a code block, no labels) and
    `verification_url` second (plain auto-link); see the tool
    description for the canonical UX phrasing.

    Idempotent: if a non-expired pending session already exists for
    this profile, the existing session is returned without starting
    a second polling task. Pass `force=True` to cancel any in-flight
    session and start fresh.
    """
    registry = get_login_session_registry()
    existing = registry.get(profile)

    if existing is not None and existing.status == "pending":
        if force:
            _cancel_session(existing)
        else:
            # Idempotent return — block on the existing task if any,
            # so the caller still gets a terminal status and progress
            # notifications.
            return await _await_terminal(existing, ctx=ctx)

    # Initiate Device Code flow (sync HTTP, sub-second).
    device_code, challenge = await asyncio.to_thread(
        request_device_code,
        client_id=DEFAULT_CLIENT_ID,
        tenant=DEFAULT_AUTHORITY_TENANT,
        http=http,
    )
    started_at = datetime.now(UTC)
    session = LoginSession(
        session_id=str(uuid.uuid4()),
        profile=profile,
        device_code=device_code,
        user_code=challenge.user_code,
        verification_url=challenge.verification_uri,
        verification_url_complete=challenge.verification_uri_complete,
        expires_at=datetime.fromtimestamp(challenge.expires_at, tz=UTC),
        interval_s=challenge.interval,
        status="pending",
        signed_in_user_upn=None,
        error=None,
        task=None,
        started_at=started_at,
    )
    poll_task = asyncio.create_task(_poll_and_finalize(session, http=http))
    session.task = poll_task
    registry.put(session)

    return await _await_terminal(session, ctx=ctx)


def _cancel_session(session: LoginSession) -> None:
    """Mark a session as cancelled and cancel its polling task."""
    session.status = "cancelled"
    task = session.task
    if isinstance(task, asyncio.Task) and not task.done():
        task.cancel()


async def _await_terminal(
    session: LoginSession,
    *,
    ctx: Context[Any, Any] | None,
) -> dict[str, Any]:
    """Wait for the session's polling task to reach a terminal state.

    During the wait, send periodic progress notifications via `ctx`
    (if the client advertises the capability). On exit, return the
    session's `public_view`.
    """
    task = session.task
    if not isinstance(task, asyncio.Task):
        # No task to wait on — session is already terminal (rare).
        return public_view(session, now=datetime.now(UTC))

    interval_s = max(1, session.interval_s)
    total_s = max(1.0, (session.expires_at - session.started_at).total_seconds())

    while not task.done():
        if ctx is not None:
            now = datetime.now(UTC)
            elapsed = (now - session.started_at).total_seconds()
            time_remaining = max(0.0, (session.expires_at - now).total_seconds())
            with contextlib.suppress(Exception):
                # report_progress is a bonus channel — never fail the
                # tool because progress emission failed (e.g. client
                # has no progressToken).
                await ctx.report_progress(
                    progress=elapsed,
                    total=total_s,
                    message=f"Waiting for sign-in — {int(time_remaining)}s remaining",
                )
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=interval_s)
        except TimeoutError:
            continue
        except asyncio.CancelledError:
            # Caller cancelled this await; the polling task may
            # still be running (asyncio.shield protected it).
            raise

    return public_view(session, now=datetime.now(UTC))


async def _poll_and_finalize(
    session: LoginSession,
    *,
    http: httpx.Client | None,
) -> None:
    """Background task: poll Microsoft Identity until a terminal state,
    then write the token + populate the UPN cache.

    Mutates `session.status`, `session.error`, `session.signed_in_user_upn`
    in place. Persists the token via the configured TokenStore.
    """
    try:
        cached = await asyncio.to_thread(
            poll_for_token,
            device_code=session.device_code,
            client_id=DEFAULT_CLIENT_ID,
            tenant=DEFAULT_AUTHORITY_TENANT,
            interval=session.interval_s,
            http=http,
        )
    except AuthorizationDeniedError as exc:
        session.status = "failed"
        session.error = {"code": "access_denied", "message": str(exc)}
        return
    except DeviceCodeExpiredError as exc:
        session.status = "expired"
        session.error = {"code": "expired_token", "message": str(exc)}
        return
    except asyncio.CancelledError:
        # Cancelled (force=True or external cancel) — leave session
        # status alone; _cancel_session has set it to "cancelled".
        raise
    except Exception as exc:
        session.status = "failed"
        session.error = {"code": "unexpected_error", "message": repr(exc)}
        _log.exception("ol_login_begin polling failed for profile %r", session.profile)
        return

    # Success: persist the token + update the session.
    try:
        store = get_token_store()
        store.set(session.profile, cached.to_json().encode())
    except Exception as exc:
        # Token couldn't be persisted — surface as failure so the
        # agent retries rather than silently moving on.
        session.status = "failed"
        session.error = {"code": "token_store_failed", "message": repr(exc)}
        _log.exception("ol_login_begin token persist failed for profile %r", session.profile)
        return

    upn = await asyncio.to_thread(_fetch_upn, cached.access_token, http)
    if upn is not None:
        cache_upn(session.profile, upn)
    session.signed_in_user_upn = upn
    session.status = "success"


def _fetch_upn(token: str, http: httpx.Client | None) -> str | None:
    """One sync /me?$select=userPrincipalName round-trip. Defensive
    against wire-format quirks — same shape as login_status._fetch_upn."""
    client = http if http is not None else httpx.Client(timeout=15.0)
    try:
        response = client.get(
            f"{GRAPH_BASE}/me",
            headers=auth_headers(token),
            params={"$select": "userPrincipalName"},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return None
        upn = payload.get("userPrincipalName")
        return cast("str | None", upn) if isinstance(upn, str) else None
    except (httpx.HTTPError, ValueError):
        return None
    finally:
        if http is None:
            client.close()
