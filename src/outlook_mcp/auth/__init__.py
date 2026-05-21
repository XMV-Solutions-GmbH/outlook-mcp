# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Authentication public API.

Two entry points:

- `get_token(profile)` — silent path. Returns a fresh access token
  from the cached refresh token. Refreshes through Microsoft Identity
  if needed. Never blocks on user interaction. Raises
  `AuthRequiredError` if the cache is empty or the refresh token has
  been invalidated; the caller is expected to surface that to the
  human and arrange `interactive_login()` to be invoked separately.
- `interactive_login(profile)` — out-of-band path. Drives the full
  Device Code flow, blocks until the human completes (or refuses) the
  prompt, persists the resulting tokens to the configured TokenStore.
  Intended to be invoked from a CLI subcommand (`mcp-server-outlook
  login`), not from inside an MCP tool call.

This split mirrors how `gh auth login` separates from `gh` runtime
calls: the MCP server does not pause to do interactive auth in the
middle of a tool call.

`OUTLOOK_CLIENT_ID` and `OUTLOOK_TENANT_ID` env vars override the
bundled multi-tenant defaults — see `docs/app-concept.md`
§ Authentication.
"""

from __future__ import annotations

import os
import sys
import webbrowser
from collections.abc import Callable

import httpx

from outlook_mcp.auth.flow import (
    DEFAULT_AUTHORITY_TENANT,
    DEFAULT_CLIENT_ID,
    AuthorizationDeniedError,
    DeviceCodeChallenge,
    DeviceCodeError,
    DeviceCodeExpiredError,
    RefreshTokenInvalidError,
    poll_for_token,
    refresh_access_token,
    request_device_code,
    resolve_scopes,
)
from outlook_mcp.auth.service_principal import (
    ServicePrincipalConfigError,
    get_app_only_token,
    is_service_principal_mode,
)
from outlook_mcp.auth.store import TokenStore, get_token_store
from outlook_mcp.auth.tokens import CachedToken

CLIENT_ID_ENV = "OUTLOOK_CLIENT_ID"
TENANT_ENV = "OUTLOOK_TENANT_ID"

__all__ = [
    "AuthRequiredError",
    "AuthorizationDeniedError",
    "CachedToken",
    "DeviceCodeChallenge",
    "DeviceCodeError",
    "DeviceCodeExpiredError",
    "RefreshTokenInvalidError",
    "ServicePrincipalConfigError",
    "get_token",
    "interactive_login",
    "is_service_principal_mode",
]


class AuthRequiredError(RuntimeError):
    """No usable cached token; the caller must trigger `interactive_login`.

    Raised by `get_token` when (a) the cache is empty for this profile,
    (b) the cached access token expired and there is no refresh token
    to use, or (c) Microsoft Identity rejected the refresh token (the
    expired-after-too-long-idle case).

    The MCP tool layer should catch this, surface a clear message to
    the agent (and through it to the user), and stop. Re-authentication
    happens out of band via `uvx mcp-server-outlook login`.
    """

    def __init__(self, profile: str, reason: str) -> None:
        super().__init__(
            f"No usable credentials for profile {profile!r}: {reason}. "
            f"Run `uvx mcp-server-outlook login --profile {profile}` to sign in.",
        )
        self.profile = profile
        self.reason = reason


def _resolve_client_id(client_id: str | None) -> str:
    if client_id:
        return client_id
    env = os.environ.get(CLIENT_ID_ENV, "").strip()
    return env or DEFAULT_CLIENT_ID


def _resolve_tenant(tenant: str | None) -> str:
    if tenant:
        return tenant
    env = os.environ.get(TENANT_ENV, "").strip()
    return env or DEFAULT_AUTHORITY_TENANT


def _has_desktop_session() -> bool:
    """Heuristic: true iff there's likely a usable graphical browser."""
    if sys.platform == "darwin" or sys.platform.startswith("win"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


# Stable, agent-readable instruction block. Both the CLI `_default_prompt`
# and the MCP tool description for ol_login_begin / ol_login_status emit
# this verbatim so an MCP-client agent can pattern-match the literal
# `AGENT_INSTRUCTIONS:` marker and render the credentials correctly in
# the chat UI.
#
# The wording optimises for "mobile copy → tap URL → paste code" — the
# happy path of OAuth Device Code on a phone. A fenced code block gets a
# one-click copy button; a bare URL becomes auto-linked. Anything else
# (bold links, inline code, prose-embedded codes) breaks that flow.
AGENT_INSTRUCTIONS = (
    "AGENT_INSTRUCTIONS: Present the verification code to the user inside a "
    "fenced code block (so it can be copied with one click) and present the "
    "verification URL as a plain markdown link on its own line. Do not "
    "paraphrase, do not embed the code inside prose, do not wrap the URL "
    "in bold."
)


def _default_prompt(challenge: DeviceCodeChallenge) -> None:
    """Show the Device Code challenge to the human running login.

    Output shape is locked down by the `AGENT_INSTRUCTIONS` marker
    above: an MCP-client agent that pipes this stderr to the chat UI
    will see the explicit "render code in fenced block, URL as link"
    instruction first, then the actual code already pre-formatted that
    way. Agents that ignore the marker still get the right visual
    output because the raw stderr is already in the target format.

    On a desktop session, tries to open the verification URL
    automatically so the page is one click away.
    """
    target_uri = challenge.verification_uri_complete or challenge.verification_uri

    opened = False
    if _has_desktop_session():
        try:
            opened = webbrowser.open(target_uri, new=2)
        except webbrowser.Error:
            opened = False

    if opened:
        header = "Sign-in via Device Code flow. Browser opened automatically."
    else:
        header = "Sign in to mcp-server-outlook via the Device Code flow."

    url_to_show = challenge.verification_uri_complete or challenge.verification_uri

    # Code FIRST in a bare fenced block (no language tag, no labels);
    # URL SECOND on its own line as a plain auto-link. See AGENT_INSTRUCTIONS.
    print(
        (
            f"\n{header}\n\n"
            f"{AGENT_INSTRUCTIONS}\n\n"
            f"Code:\n```\n{challenge.user_code}\n```\n\n"
            f"Sign-in URL: {url_to_show}\n\n"
            "Waiting for sign-in..."
        ),
        file=sys.stderr,
        flush=True,
    )


def get_token(
    profile: str = "default",
    *,
    client_id: str | None = None,
    tenant: str | None = None,
    store: TokenStore | None = None,
    http: httpx.Client | None = None,
) -> str:
    """Return a valid access token for `profile`.

    In delegated mode (the default): reads from the configured
    TokenStore, refreshes through Microsoft Identity if needed.

    In service-principal mode (`OUTLOOK_AUTH_MODE=service-principal`,
    or auto-detected when `OUTLOOK_CLIENT_SECRET` is set): bypasses
    the token store, uses the in-process app-only token cache,
    re-acquires via client_credentials when expired. `profile` is
    ignored in this mode (one client_id+tenant -> one token).

    Raises:
        AuthRequiredError: delegated mode only. No cached entry, no
            refresh token, or the refresh token was rejected. The
            caller must trigger `interactive_login` to recover.
        ServicePrincipalConfigError: service-principal mode is
            selected but `OUTLOOK_CLIENT_ID` / `OUTLOOK_CLIENT_SECRET`
            / `OUTLOOK_TENANT_ID` aren't all set.
    """
    if is_service_principal_mode():
        return get_app_only_token(http=http)

    resolved_client = _resolve_client_id(client_id)
    resolved_tenant = _resolve_tenant(tenant)
    resolved_store = store if store is not None else get_token_store()

    raw = resolved_store.get(profile)
    if raw is None:
        raise AuthRequiredError(profile, "no cached credentials found")

    cached = CachedToken.from_json(raw.decode())
    if not cached.is_expired():
        return cached.access_token

    if cached.refresh_token is None:
        raise AuthRequiredError(
            profile, "cached token has expired and no refresh token is available"
        )

    try:
        new_token = refresh_access_token(
            refresh_token=cached.refresh_token,
            client_id=resolved_client,
            tenant=resolved_tenant,
            scopes=resolve_scopes(),
            http=http,
        )
    except RefreshTokenInvalidError as exc:
        resolved_store.delete(profile)
        raise AuthRequiredError(
            profile, f"refresh token rejected by Microsoft Identity ({exc})"
        ) from exc

    resolved_store.set(profile, new_token.to_json().encode())
    return new_token.access_token


def interactive_login(
    profile: str = "default",
    *,
    client_id: str | None = None,
    tenant: str | None = None,
    store: TokenStore | None = None,
    prompt: Callable[[DeviceCodeChallenge], None] | None = None,
    http: httpx.Client | None = None,
) -> CachedToken:
    """Run the Device Code flow end-to-end. Blocks until completion.

    On success: persists the issued tokens to `store` (or the
    auto-detected store) under `profile`, and returns the
    `CachedToken`.

    Raises:
        AuthorizationDeniedError: user refused the prompt.
        DeviceCodeExpiredError: device code expired before sign-in.

    Intended to be invoked from a CLI subcommand or test. Do not call
    from inside an MCP tool handler — it blocks the server for up to
    ~15 minutes.
    """
    resolved_client = _resolve_client_id(client_id)
    resolved_tenant = _resolve_tenant(tenant)
    resolved_store = store if store is not None else get_token_store()
    resolved_prompt = prompt if prompt is not None else _default_prompt
    # OUTLOOK_ALLOW_SEND-aware: appends Mail.Send only when the env var
    # is truthy. See auth/flow.py:resolve_scopes() for the design.
    scopes = resolve_scopes()

    device_code, challenge = request_device_code(
        client_id=resolved_client,
        tenant=resolved_tenant,
        scopes=scopes,
        http=http,
    )
    resolved_prompt(challenge)

    cached = poll_for_token(
        device_code=device_code,
        client_id=resolved_client,
        tenant=resolved_tenant,
        interval=challenge.interval,
        http=http,
    )
    resolved_store.set(profile, cached.to_json().encode())
    return cached
