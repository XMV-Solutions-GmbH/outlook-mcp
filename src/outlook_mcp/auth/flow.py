# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""OAuth 2.0 Device Code Flow + refresh-token client against Microsoft Identity.

Thin shim over `mcp-microsoft-graph-auth`'s `device_code` module
that supplies Outlook-specific defaults: the bundled multi-tenant
Entra app's client_id, the Outlook-flavoured Mail/Calendar Graph
scopes, and the multi-tenant `organizations` authority.

Each function delegates to the shared library after applying the
defaults. Existing imports (`outlook_mcp.auth.flow.poll_for_token`,
`resolve_scopes`, etc.) keep working without source-level changes.

Default scopes are deliberately read-only and DO NOT include
`Mail.Send`. The compliance line of this server is "drafts only,
sends are human-only" — the consent prompt should never read
"this app can send mail as you" unless the operator opts in via
`OUTLOOK_ALLOW_SEND`. See docs/app-concept.md for the full rationale.
"""

from __future__ import annotations

import dataclasses
import os
import time
from collections.abc import Callable

import httpx
from mcp_microsoft_graph_auth.device_code import (
    AUTHORITY_BASE,
    AuthorizationDeniedError,
    DeviceCodeChallenge,
    DeviceCodeError,
    DeviceCodeExpiredError,
    RefreshTokenInvalidError,
)
from mcp_microsoft_graph_auth.device_code import (
    poll_for_token as _lib_poll_for_token,
)
from mcp_microsoft_graph_auth.device_code import (
    refresh_access_token as _lib_refresh_access_token,
)
from mcp_microsoft_graph_auth.device_code import (
    request_device_code as _lib_request_device_code,
)
from mcp_microsoft_graph_auth.tokens import CachedToken

# ---------------------------------------------------------------------
# Outlook-specific defaults — see docs/app-concept.md § Authentication.
# ---------------------------------------------------------------------

# XMV-published multi-tenant Entra app registration for mcp-server-outlook.
# Public client, Device Code flow enabled. As of v0.3 the registered
# permission list is: Mail.Read, Mail.ReadWrite, Mail.Send, Calendars.Read,
# Calendars.ReadWrite, User.Read, offline_access. **Mail.Send is in the
# registered permission list but is NOT in the default OAuth scope
# request** — see `resolve_scopes()` below for the lazy-request semantic.
# Override via OUTLOOK_CLIENT_ID for tenants with strict app-allowlisting.
DEFAULT_CLIENT_ID = "5df367d9-4c9b-44fd-9f84-0b4fb1f1268a"
# `common` accepts both AzureAD (work/school) AND personal Microsoft
# accounts (outlook.com / hotmail.com / live.com). The XMV-hosted app
# registration has `signInAudience=AzureADandPersonalMicrosoftAccount`
# since v0.7 (#48), so the consent screen lets consumer accounts
# through. Multi-tenant B2B is unaffected — `common` is a superset of
# `organizations`. Personal-account-only tools (none today) or
# work/school-only tools (the `mailbox` parameter on email tools)
# guard at the call site via `is_personal_account()`.
DEFAULT_AUTHORITY_TENANT = "common"

# Env var that opts the running MCP server into requesting Mail.Send at
# OAuth time (and registering ol_email_send_draft as an MCP tool). When
# unset / falsy, the consent screen does NOT include "this app can send
# mail as you" — the default install is drafts-only. See
# docs/spikes/2026-05-08-v02-drafts-spikes.md § 1 (revised) for the design
# discussion.
ALLOW_SEND_ENV = "OUTLOOK_ALLOW_SEND"
ALLOW_DRAFTS_ENV = "OUTLOOK_ALLOW_DRAFTS"

# v0.5 (issue #45): opt-in access to mailboxes other than the signed-in
# user's via Exchange FullAccess-Delegate. When unset/false: all email
# tools are hard-bound to /me; when "true": the tools accept an optional
# `mailbox` parameter and route to /users/{upn}/... — and the OAuth scope
# request adds Mail.ReadWrite.Shared so the consent screen shows the
# expanded surface.
ALLOW_SHARED_MAILBOXES_ENV = "OUTLOOK_ALLOW_SHARED_MAILBOXES"

# v0.5 (issue #45): opt-in to the destructive ol_email_delete tool.
# Independent of the other three flags: an operator may want delete on
# the signed-in mailbox without shared-mailbox access, or vice versa.
# Permanent-delete (skipping Deleted Items) is opt-in per-call via the
# tool's `permanent=True` argument, not via a separate env var — the
# blast-radius cap stays at "operator decided to enable delete at all."
ALLOW_DELETE_ENV = "OUTLOOK_ALLOW_DELETE"

# v0.9: opt-in to reading Microsoft 365 **group** mailboxes.
# Separate from ALLOW_SHARED_MAILBOXES because it is a different
# Microsoft Graph surface, not a wider version of the same one: a group
# mailbox is not reachable under /users/{upn}/ at all (Exchange answers
# `ErrorGroupIsUsedInNonGroupURI`), it lives under /groups/{id}/threads,
# and it needs its own delegated scope. Conflating the two flags would
# mean an operator who wanted a Sekretariats-Postfach silently also
# consented to Group-Conversation.Read.All across every group they
# belong to.
ALLOW_GROUP_MAILBOXES_ENV = "OUTLOOK_ALLOW_GROUP_MAILBOXES"

# `OUTLOOK_ALLOW_DRAFTS` and `OUTLOOK_ALLOW_SEND` MUST be set to
# exactly "true" or "false" (case-insensitive, trimmed). Earlier
# versions accepted any of {"1","true","yes","on"} as truthy and
# silently treated unset as false; v0.4 enforces an explicit decision
# because "drafts not enabled because nobody flipped the switch" is
# indistinguishable, from the operator's perspective, from "drafts
# not enabled because I decided against it." See issue #37 for the
# user-side rationale.
_STRICT_TRUE = "true"
_STRICT_FALSE = "false"


class OutlookConsentNotConfiguredError(RuntimeError):
    """Raised at server-build / CLI-login time when one of the
    operator-consent env vars is unset or has a non-`true`/`false`
    value.

    The exception message is the user-facing onboarding hint —
    callers re-raise without wrapping so the operator sees it
    verbatim on stderr.
    """


# v0.7 (#49): the two valid `account_type` values. Stable contract —
# the strings are emitted in tool descriptions, error messages, CLI
# help, and tests; downstream code matches on them.
ACCOUNT_TYPE_PERSONAL = "personal"
ACCOUNT_TYPE_WORK_OR_SCHOOL = "work_or_school"
VALID_ACCOUNT_TYPES: tuple[str, ...] = (ACCOUNT_TYPE_PERSONAL, ACCOUNT_TYPE_WORK_OR_SCHOOL)


class LoginAccountTypeRequiredError(RuntimeError):
    """Raised when `interactive_login` / `ol_login_begin` is invoked
    without `account_type` AND no `OUTLOOK_TENANT_ID` env-var override.

    Microsoft Identity's `/common` authority returns the work/school
    Device Code landing page (`https://login.microsoft.com/device`)
    even for apps that accept personal accounts — and that landing page
    rejects personal MSAs. The two options route differently:

    - `account_type="personal"` → `/consumers` authority → personal
      Device Code landing page (`https://www.microsoft.com/link`).
    - `account_type="work_or_school"` → `/organizations` authority →
      work/school Device Code landing page
      (`https://login.microsoft.com/device`).

    There's no way to auto-detect the user's account kind before
    sign-in (we have no identity claim yet), so the caller MUST
    decide. The MCP-tool layer raises this with an agent-readable
    message so the MCP client can ask the user, then retry the tool
    call with the answer.
    """

    AGENT_MESSAGE = (
        "Required parameter `account_type` is missing. "
        "This determines which Microsoft Identity Device Code endpoint "
        "to route to — there is no auto-detection before sign-in.\n\n"
        "Valid values:\n"
        '  "personal"        — outlook.com / hotmail.com / live.com / msn.com\n'
        '  "work_or_school"  — any Microsoft 365 tenant account (incl. B2B guests)\n\n'
        "AGENT_INSTRUCTIONS: Ask the user which Microsoft account they want to sign in "
        "with — a personal Microsoft account (outlook.com / hotmail.com / live.com / "
        "msn.com) or a work/school Microsoft 365 account. Then call this tool again "
        "with the matching account_type value."
    )

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.AGENT_MESSAGE)


def account_type_to_tenant(account_type: str) -> str:
    """Map an `account_type` literal to the Microsoft Identity tenant
    path that returns the correct Device Code landing page.

    - `"personal"` → `"consumers"` (returns `https://www.microsoft.com/link`)
    - `"work_or_school"` → `"organizations"` (returns
      `https://login.microsoft.com/device`)

    Raises `ValueError` for anything else — strict per #49 acceptance
    criteria; we don't want a typo (`account_type="privat"`) to
    silently fall through to a wrong endpoint.

    The legacy `"common"` tenant is intentionally NOT a third option:
    `/common` returns `login.microsoft.com/device` regardless of app
    audience, which broke personal-account sign-in in v0.6. The two
    explicit values let us route correctly per case.
    """
    if account_type == ACCOUNT_TYPE_PERSONAL:
        return "consumers"
    if account_type == ACCOUNT_TYPE_WORK_OR_SCHOOL:
        return "organizations"
    raise ValueError(f"account_type must be one of {VALID_ACCOUNT_TYPES!r}; got {account_type!r}.")


def _strict_bool_env(name: str) -> bool:
    """Read `name` from the environment and parse strictly.

    Returns `True` for "true", `False` for "false" (case-insensitive,
    leading/trailing whitespace ignored). Raises
    `OutlookConsentNotConfiguredError` with the documented onboarding-help
    message for anything else, including unset / empty.
    """
    raw = os.environ.get(name)
    if raw is not None:
        normalised = raw.strip().lower()
        if normalised == _STRICT_TRUE:
            return True
        if normalised == _STRICT_FALSE:
            return False
    raise OutlookConsentNotConfiguredError(_consent_help_text(name, raw))


def _optional_strict_bool_env(name: str) -> bool:
    """Read an OPTIONAL boolean env var.

    Same strict accept-only-"true"/"false" parser as `_strict_bool_env`,
    but unset / empty returns `False` instead of raising. Typos still
    raise — we want "OUTLOOK_ALLOW_DELETE=yes" to fail loudly, not
    silently default to safe-off and leave the operator wondering why
    their delete attempts get refused.

    Used for the v0.5 opt-in flags added in #45: existing installs that
    don't set `OUTLOOK_ALLOW_SHARED_MAILBOXES` / `OUTLOOK_ALLOW_DELETE`
    keep their old behaviour. Operators who want to enable either must
    set it explicitly to "true"; "false" is also valid for documentation
    intent.
    """
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return False
    normalised = raw.strip().lower()
    if normalised == _STRICT_TRUE:
        return True
    if normalised == _STRICT_FALSE:
        return False
    raise OutlookConsentNotConfiguredError(_consent_help_text(name, raw))


def _consent_help_text(name: str, raw: str | None) -> str:
    """Format the onboarding-help message for an unset / invalid
    consent env var. Identical layout for the two env vars so the
    operator gets predictable guidance independent of which one
    tripped."""
    got = "(not set)" if raw is None else f"{raw!r}"
    if name == ALLOW_DRAFTS_ENV:
        return (
            f"ERROR: mcp-server-outlook requires an explicit "
            f"{ALLOW_DRAFTS_ENV} decision (got {got}).\n\n"
            f"This server can create email drafts on the signed-in user's "
            f"behalf (opt-in) or operate in read-only mode. There is no "
            f"implicit default — the operator must consciously decide.\n\n"
            f"Set in your MCP client config (.mcp.json env section):\n\n"
            f'  "{ALLOW_DRAFTS_ENV}": "true"    — enable draft creation\n'
            f'  "{ALLOW_DRAFTS_ENV}": "false"   — read-only (no draft tools)\n\n'
            f"If you set {ALLOW_DRAFTS_ENV}=true, you must additionally "
            f"decide:\n\n"
            f'  "{ALLOW_SEND_ENV}": "true"      — additionally enable send tool\n'
            f'  "{ALLOW_SEND_ENV}": "false"     — drafts only, no send tool\n\n'
            f"See README §Authentication for the design rationale."
        )
    if name == ALLOW_SEND_ENV:
        return (
            f"ERROR: mcp-server-outlook requires an explicit "
            f"{ALLOW_SEND_ENV} decision when {ALLOW_DRAFTS_ENV}=true (got {got}).\n\n"
            f"Sending mail is a separate consent decision from drafting it. "
            f"There is no implicit default — the operator must consciously "
            f"decide.\n\n"
            f"Set in your MCP client config (.mcp.json env section), next to "
            f'"{ALLOW_DRAFTS_ENV}": "true":\n\n'
            f'  "{ALLOW_SEND_ENV}": "true"      — register ol_email_send_draft\n'
            f'  "{ALLOW_SEND_ENV}": "false"     — drafts only, no send tool\n\n'
            f"See README §Authentication for the design rationale."
        )
    if name == ALLOW_GROUP_MAILBOXES_ENV:
        return (
            f"ERROR: mcp-server-outlook got an invalid {ALLOW_GROUP_MAILBOXES_ENV} "
            f"value ({got}).\n\n"
            f"This flag opts the server into reading Microsoft 365 GROUP "
            f"mailboxes, addressed as mailbox='group:<group-id>'. Group mail "
            f"lives under /groups/{{id}}/threads — a different Graph surface "
            f"from shared mailboxes — so the consent screen adds "
            f"Group-Conversation.Read.All.\n\n"
            f"Valid values:\n\n"
            f'  "{ALLOW_GROUP_MAILBOXES_ENV}": "true"   — enable group-mailbox reads\n'
            f'  "{ALLOW_GROUP_MAILBOXES_ENV}": "false"  — no group access (the safe default)\n'
            f"  (unset)                                 — same as false\n\n"
            f"See README §Authentication for the design rationale."
        )
    if name == ALLOW_SHARED_MAILBOXES_ENV:
        return (
            f"ERROR: mcp-server-outlook got an invalid {ALLOW_SHARED_MAILBOXES_ENV} "
            f"value ({got}).\n\n"
            f"This flag opts the server into routing email-tool calls to "
            f"/users/{{upn}}/... instead of /me/... when the agent passes "
            f"a `mailbox` argument. The OAuth consent screen then adds "
            f"Mail.ReadWrite.Shared.\n\n"
            f"Valid values:\n\n"
            f'  "{ALLOW_SHARED_MAILBOXES_ENV}": "true"   — enable shared-mailbox routing\n'
            f'  "{ALLOW_SHARED_MAILBOXES_ENV}": "false"  — /me only (the safe default)\n'
            f"  (unset)                                  — same as false\n\n"
            f"See README §Authentication for the design rationale."
        )
    # ALLOW_DELETE_ENV
    return (
        f"ERROR: mcp-server-outlook got an invalid {ALLOW_DELETE_ENV} "
        f"value ({got}).\n\n"
        f"This flag opts the server into registering the ol_email_delete "
        f"tool. Without it, the server cannot delete messages — only "
        f"create / update / send drafts on the agent's behalf.\n\n"
        f"Valid values:\n\n"
        f'  "{ALLOW_DELETE_ENV}": "true"   — register ol_email_delete\n'
        f'  "{ALLOW_DELETE_ENV}": "false"  — no delete tool (the safe default)\n'
        f"  (unset)                       — same as false\n\n"
        f"See README §Authentication for the design rationale."
    )


@dataclasses.dataclass(frozen=True)
class ConsentConfig:
    """The four operator-consent toggles, resolved together at startup.

    - `drafts` — can the server create local drafts? (v0.2; strict env.)
    - `send` — can the server send drafts? (v0.2; strict env, requires drafts.)
    - `shared_mailboxes` — does the server accept a `mailbox` argument
      on email tools that routes to `/users/{upn}/...`? (v0.5; optional
      env, defaults False, raises on typo.)
    - `delete` — is `ol_email_delete` registered? (v0.5; optional env,
      defaults False, raises on typo.)

    All four are read at startup, then passed around as a single value
    so per-tool gating reads as `if cfg.shared_mailboxes: ...` instead
    of re-running env-var parsing per call.
    """

    drafts: bool
    send: bool
    shared_mailboxes: bool
    delete: bool
    # Defaulted, unlike its siblings: this field was added after
    # ConsentConfig was public, and a required fifth positional would
    # break every existing four-argument construction.
    group_mailboxes: bool = False


def validate_consent_config() -> ConsentConfig:
    """Validate the consent env vars at startup.

    Returns a `ConsentConfig` with the four flags resolved. Raises
    `OutlookConsentNotConfiguredError` with a clear, actionable error
    message if any required env var is unset or has a non-`true`/`false`
    value.

    Strictness rules:

    - `OUTLOOK_ALLOW_DRAFTS` MUST be set to exactly `true` or `false`.
    - If `OUTLOOK_ALLOW_DRAFTS=true`, `OUTLOOK_ALLOW_SEND` MUST also be
      set to exactly `true` or `false`. (If DRAFTS=false, SEND is not
      checked — would be dead config anyway.)
    - `OUTLOOK_ALLOW_SHARED_MAILBOXES` and `OUTLOOK_ALLOW_DELETE` are
      OPTIONAL: unset/empty = False (safe default; existing installs
      keep their behaviour). If set to any value other than exactly
      `true` / `false`, raises — typos shouldn't silently degrade to
      false.
    """
    drafts = _strict_bool_env(ALLOW_DRAFTS_ENV)
    send = _strict_bool_env(ALLOW_SEND_ENV) if drafts else False
    shared_mailboxes = _optional_strict_bool_env(ALLOW_SHARED_MAILBOXES_ENV)
    delete = _optional_strict_bool_env(ALLOW_DELETE_ENV)
    group_mailboxes = _optional_strict_bool_env(ALLOW_GROUP_MAILBOXES_ENV)
    return ConsentConfig(
        drafts=drafts,
        send=send,
        shared_mailboxes=shared_mailboxes,
        delete=delete,
        group_mailboxes=group_mailboxes,
    )


# Legacy truthy-set kept as documentation for callers reading old
# CHANGELOGs. Not used by the v0.4 strict parser.
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})

_BASE_SCOPES: tuple[str, ...] = (
    # Read inbox + calendar (v0.1 minimum)
    "Mail.Read",
    "Calendars.Read",
    # Draft creation / update / discard for v0.2 — gated at the tool
    # surface by OUTLOOK_ALLOW_DRAFTS=true. Mail.ReadWrite covers
    # POST/PATCH/DELETE on /me/messages; Calendars.ReadWrite covers
    # the same on /me/events.
    "Mail.ReadWrite",
    "Calendars.ReadWrite",
    "User.Read",
    "offline_access",
)


def send_enabled() -> bool:
    """True iff `OUTLOOK_ALLOW_SEND` is set to `"true"` AND
    `OUTLOOK_ALLOW_DRAFTS=true`.

    Strict parsing — raises `OutlookConsentNotConfiguredError` if either
    env var is unset or has a non-`true`/`false` value. Sends are a
    separate decision from drafting; the OAuth scope request omits
    `Mail.Send` and the MCP server does not register
    `ol_email_send_draft` unless this returns True.
    """
    return validate_consent_config().send


def resolve_scopes() -> tuple[str, ...]:
    """Return the OAuth scopes to request at this moment.

    Always includes `_BASE_SCOPES`. Appends `Mail.Send` when the
    operator has opted into both drafts AND send. Appends
    `Mail.ReadWrite.Shared` when the operator has opted into
    `OUTLOOK_ALLOW_SHARED_MAILBOXES=true` — this is what the consent
    screen exposes for delegated access to other users' mailboxes
    (typical: Sekretariats- / shared-team-mailboxes via Exchange
    Add-MailboxPermission).

    Resolved at call time, not at module load, so test-time
    `monkeypatch.setenv` flips behaviour without re-importing.

    Raises `OutlookConsentNotConfiguredError` if the consent env vars
    are not configured strictly.
    """
    cfg = validate_consent_config()
    scopes: tuple[str, ...] = _BASE_SCOPES
    if cfg.send:
        scopes = (*scopes, "Mail.Send")
    if cfg.shared_mailboxes:
        # Covers both read and write against other mailboxes. The
        # narrower Mail.Read.Shared would suffice for v0.4-style
        # read-only deployments but the shared-mailbox use case the
        # flag was designed for (deleting old PDFs in a Sekretariats-
        # Postfach via ol_email_delete) needs write too.
        scopes = (*scopes, "Mail.ReadWrite.Shared")
    if cfg.group_mailboxes:
        # Least-privileged scope that reads /groups/{id}/threads and
        # .../posts. Deliberately NOT Group.Read.All: that one also
        # grants directory reads over every group in the tenant, which
        # this server never needs. Group resolution stays on
        # /me/memberOf, which the already-requested User.Read covers.
        scopes = (*scopes, "Group-Conversation.Read.All")
    return scopes


# Backwards-compat alias so callers who still import DEFAULT_SCOPES at
# module load continue to work — they get the un-flagged default. Tests
# that need to assert on the env-var-aware shape should call
# `resolve_scopes()` directly.
DEFAULT_SCOPES = _BASE_SCOPES

DEVICE_CODE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"

__all__ = [
    "ACCOUNT_TYPE_PERSONAL",
    "ACCOUNT_TYPE_WORK_OR_SCHOOL",
    "ALLOW_DELETE_ENV",
    "ALLOW_DRAFTS_ENV",
    "ALLOW_GROUP_MAILBOXES_ENV",
    "ALLOW_SEND_ENV",
    "ALLOW_SHARED_MAILBOXES_ENV",
    "AUTHORITY_BASE",
    "DEFAULT_AUTHORITY_TENANT",
    "DEFAULT_CLIENT_ID",
    "DEFAULT_SCOPES",
    "DEVICE_CODE_GRANT_TYPE",
    "VALID_ACCOUNT_TYPES",
    "AuthorizationDeniedError",
    "CachedToken",
    "ConsentConfig",
    "DeviceCodeChallenge",
    "DeviceCodeError",
    "DeviceCodeExpiredError",
    "LoginAccountTypeRequiredError",
    "OutlookConsentNotConfiguredError",
    "RefreshTokenInvalidError",
    "account_type_to_tenant",
    "poll_for_token",
    "refresh_access_token",
    "request_device_code",
    "resolve_scopes",
    "send_enabled",
    "validate_consent_config",
]


def request_device_code(
    *,
    client_id: str = DEFAULT_CLIENT_ID,
    tenant: str = DEFAULT_AUTHORITY_TENANT,
    scopes: tuple[str, ...] | None = None,
    http: httpx.Client | None = None,
) -> tuple[str, DeviceCodeChallenge]:
    """Initiate the Device Code flow with Outlook-flavoured defaults.

    `scopes=None` (the default) calls `resolve_scopes()` so the env-var-
    aware Mail.Send-when-enabled behaviour kicks in. Pass an explicit
    tuple to override.
    """
    return _lib_request_device_code(
        client_id=client_id,
        tenant=tenant,
        scopes=scopes if scopes is not None else resolve_scopes(),
        http=http,
    )


def poll_for_token(
    *,
    device_code: str,
    client_id: str = DEFAULT_CLIENT_ID,
    tenant: str = DEFAULT_AUTHORITY_TENANT,
    interval: int = 5,
    http: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.time,
) -> CachedToken:
    """Poll `/token` until the user completes (or denies) sign-in."""
    return _lib_poll_for_token(
        device_code=device_code,
        client_id=client_id,
        tenant=tenant,
        interval=interval,
        http=http,
        sleep=sleep,
        now=now,
    )


def refresh_access_token(
    *,
    refresh_token: str,
    client_id: str = DEFAULT_CLIENT_ID,
    tenant: str = DEFAULT_AUTHORITY_TENANT,
    scopes: tuple[str, ...] | None = None,
    http: httpx.Client | None = None,
) -> CachedToken:
    """Exchange a refresh token for a new access (and refresh) token.

    Like `request_device_code`, `scopes=None` (the default) calls
    `resolve_scopes()` so the env-var-aware behaviour kicks in.
    """
    return _lib_refresh_access_token(
        refresh_token=refresh_token,
        client_id=client_id,
        tenant=tenant,
        scopes=scopes if scopes is not None else resolve_scopes(),
        http=http,
    )
