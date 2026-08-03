<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Tracked in [GitHub Issues](https://github.com/XMV-Solutions-GmbH/outlook-mcp/issues).

## [v0.9.0] — 2026-08-03

### Changed

- **Migrated the server layer from `mcp.server.fastmcp.FastMCP` to the mcp 2.x high-level `MCPServer` API.** mcp 2.0.0 removed the `mcp.server.fastmcp` module, so installs that resolved `mcp>=2` failed to start (`ModuleNotFoundError: No module named 'mcp.server.fastmcp'`). The server now imports `MCPServer` from `mcp.server` — the in-SDK FastMCP successor — with the same `@server.tool(...)` decorator, `list_tools()`, `run()` and `Context` surface. All **17 tools** (10 read + 5 draft + send + delete), their schemas, descriptions and `ToolAnnotations` are **unchanged**; the never-auto-send posture and the consent-flag gating are untouched. Migration decision recorded in [`docs/proposals/0001-mcp-2x-server-api.md`](docs/proposals/0001-mcp-2x-server-api.md). Closes [#72](https://github.com/XMV-Solutions-GmbH/outlook-mcp/issues/72).
- **`ToolAnnotations` construction and read-back use snake_case field names** (`read_only_hint`, `destructive_hint`, `idempotent_hint`, `open_world_hint`). mcp 2.x's `ToolAnnotations` still accepts the camelCase aliases at construction, but mypy-strict only knows the snake_case fields and a listed tool's annotation is snake_case-only on read. No behavioural change — the emitted annotation values are identical.

### Dependencies

- **`mcp` bumped to `>=2,<3`** (was `>=1.2`, unbounded). The removed upper bound is what let `mcp` 2.0.0 in silently; the new range pins the supported major and makes `uv tool install mcp-server-outlook` work without the `--with "mcp<2"` workaround.

## [v0.8.0] — 2026-08-03

### Added

- **`ol_email_get_attachment(message_id, attachment_id, save_dir=None, filename=None, overwrite=False, mailbox=None)`** — read tool that downloads a single **file** attachment of a mail via Microsoft Graph and writes it to a local file. Returns `{path, name, content_type, size, graph_size, attachment_id, message_id, mailbox, is_inline}`, where `size` is the number of bytes written (the decoded length) and `graph_size` is Graph's stored size — the two differ because Graph's includes encoding overhead. Always registered (read tier, no new consent flag). `save_dir` defaults to a fresh OS temp directory; `filename` defaults to the attachment's own name, sanitised to a bare basename so a hostile sender-chosen filename cannot escape the download directory (path-traversal-safe, with a resolved-path containment re-check). `overwrite=False` refuses to clobber an existing file. Item attachments (embedded Outlook items) and reference attachments (cloud-file links) carry no bytes and are rejected with a clear error pointing reference attachments at the SharePoint MCP server. The `mailbox` parameter targets a shared mailbox (gated by `OUTLOOK_ALLOW_SHARED_MAILBOXES`, same as the other email tools). Closes the last unshipped item of the v0.2 batch ([#8](https://github.com/XMV-Solutions-GmbH/outlook-mcp/issues/8)); [#69](https://github.com/XMV-Solutions-GmbH/outlook-mcp/issues/69).
- **`UnsupportedAttachmentTypeError`** (subclass of `ValueError`) exported from `outlook_mcp.tools.email_get_attachment` — raised for item- and reference-attachments.

### Engineering

- 22 new unit tests (`test_email_get_attachment.py`: sunny paths, `size` vs `graph_size`, shared-mailbox routing with call-count assertions, no-bytes-excluding-`$select` guard, filename sanitisation / path-traversal refusal, overwrite guard, item/reference rejection, invalid-base64 and missing-`contentBytes` handling, 403/404 propagation, input validation) plus the read-tool registration-set assertion in `test_server.py`.
- 4 new harness tests (`tests/harness/test_email_get_attachment.py`) against real Microsoft Graph: round-trip download on `/me` (bytes + metadata match, `size != graph_size` confirmed empirically), default-temp-dir path, 404 on an unknown attachment id, and a shared-mailbox variant (skips unless `OUTLOOK_HARNESS_SHARED_MAILBOX_UPN` is set).

## [v0.7.0] — 2026-05-23

### Added

- **`account_type` parameter on the login surface** (CLI `--account-type` and MCP tool `ol_login_begin`) with two values: `"personal"` (outlook.com / hotmail.com / live.com / msn.com) and `"work_or_school"` (M365 tenant accounts incl. B2B guests). The MCP tool description and the `LoginAccountTypeRequiredError` message both carry an `AGENT_INSTRUCTIONS:` marker so MCP clients can pattern-match the elicit-the-user UX. Closes [#49](https://github.com/XMV-Solutions-GmbH/outlook-mcp/issues/49).
- **`account_type_to_tenant(account_type)`** helper exported from `outlook_mcp.auth.flow` — maps `"personal"`→`"consumers"`, `"work_or_school"`→`"organizations"`. Strict (`ValueError` on typo).
- **`LoginAccountTypeRequiredError`** exception with a default agent-readable message naming both valid values verbatim.
- **`outlook_mcp.auth.is_personal_account(token)`** — JWT-claims-based detector. Returns `True` iff the token's `tid` matches the global consumer tenant GUID. Used by tool guards to refuse Microsoft-platform-restricted features on consumer identities with clear messages rather than confusing 403s.
- **`outlook_mcp.auth.signed_in_account_type(token)`** → returns `"personal"` or `"work_or_school"`. Stable label for structured logs and error messages.
- **Personal Microsoft accounts supported** (outlook.com / hotmail.com / live.com / msn.com). The XMV-hosted Entra app's `signInAudience` was widened from `AzureADMultipleOrgs` to `AzureADandPersonalMicrosoftAccount`. Multi-tenant B2B (XMV + customer tenants) is unaffected.
- **Harness profile `harness-personal`** — separate token cache + matching `OUTLOOK_HARNESS_PERSONAL_TOKEN_JSON` repo secret. `scripts/renew-harness-token.sh` takes an optional profile arg (`harness` → `--account-type work_or_school`, `harness-personal` → `--account-type personal`) — no more env-var hacks. Personal-account harness tests skip silently if the token cache is absent.

### Changed

- **`is_personal_account()` recognises Microsoft Graph opaque tokens** (`EwBI…` / `EwBY…`) as personal. Pre-v0.7 it returned `False` for opaque tokens — that classified real personal MSA sign-ins as "work/school" and silently bypassed the platform-restriction guards. Fix: any non-empty non-3-segment access token is now treated as personal; empty strings and unparseable 3-segment tokens still default to work/school for malformed-input safety.
- **Device Code authority routing**: `interactive_login` / `ol_login_begin` now route via `/consumers` for personal accounts and `/organizations` for work/school. Microsoft Identity's `/common` was previously the default but returns the work/school landing page (`login.microsoft.com/device`) even for personal-capable apps — that page rejects personal MSAs. The new routing fixes personal-account sign-in end-to-end without requiring per-user env vars.
- `_guard_mailbox()` extended: when `OUTLOOK_ALLOW_SHARED_MAILBOXES=true` AND the signed-in account is a personal MSA, the `mailbox` parameter is refused with a Microsoft-platform-restriction error message (FullAccess-Delegate via Exchange's `Add-MailboxPermission` only exists for work/school accounts). Operator policy still takes precedence — when the flag is `false`, that's still the error message.

### Deprecated

- `OUTLOOK_TENANT_ID` env var remains supported as a power-user / CI escape hatch but is no longer the recommended way to pick the Device Code authority. Use `--account-type` (CLI) or the `account_type` MCP-tool parameter instead.

## [v0.6.0] — 2026-05-23

### Added

- **`OUTLOOK_ALLOW_SHARED_MAILBOXES=true|false`** (optional, default false) — opts the server into routing email-tool calls to `/users/{upn}/...` when an agent passes a `mailbox` argument. The OAuth scope request adds `Mail.ReadWrite.Shared` so the consent screen shows the expanded surface. `ol_email_search`, `ol_email_list_unread`, `ol_email_read`, and the new `ol_email_delete` all gain an optional `mailbox` parameter (default `None` = signed-in user, unchanged). Closes [#45](https://github.com/XMV-Solutions-GmbH/outlook-mcp/issues/45) (shared-mailbox half).
- **`OUTLOOK_ALLOW_DELETE=true|false`** (optional, default false) — opts the server into registering the new `ol_email_delete` tool. Independent of the drafts/send chain; an operator can enable delete without enabling drafts.
- **`ol_email_delete(message_id, mailbox=None, permanent=False)`** — destructive MCP tool. `permanent=False` (default) moves the message to Deleted Items via `DELETE`; `permanent=True` skips Deleted Items via `POST .../permanentDelete`, landing in Recoverable Items. Idempotent: re-deleting an already-gone message (Graph 404) is treated as success. Combined with `OUTLOOK_ALLOW_SHARED_MAILBOXES=true`, deletes can target other mailboxes the signed-in user has FullAccess on (typical: Sekretariats-/shared-team-mailbox cleanup). Closes [#45](https://github.com/XMV-Solutions-GmbH/outlook-mcp/issues/45) (delete half).
- **`outlook_mcp.tools._common.mailbox_path(mailbox)`** — internal helper that returns `"me"` or `"users/{quoted-upn}"`. Single source of truth for the /me-vs-/users routing across the four touched tools.
- **`outlook_mcp.auth.flow.ConsentConfig`** — frozen dataclass returned by `validate_consent_config()` with named `drafts` / `send` / `shared_mailboxes` / `delete` fields. Replaces the previous `tuple[bool, bool]` shape. Internal API; not exported in `outlook_mcp.auth`'s public re-exports.

### Changed

- `validate_consent_config()` returns `ConsentConfig` instead of `tuple[bool, bool]`. All three internal callers (`auth/flow.py:resolve_scopes`, `auth/flow.py:send_enabled`, `server.py:drafts_enabled`, `server.py:_build_server`) updated. External callers of the unchanged top-level `drafts_enabled()` / `send_enabled()` accessors are unaffected.

### Engineering

- 40 new unit tests (mailbox_path encoding, ConsentConfig, scope resolution with new flags, `ol_email_delete` happy paths + 404 idempotence + shared-mailbox routing + permission-error propagation, the `_guard_mailbox` server-side runtime check, `register_delete_tools` gating). Total: 395 unit + integration tests pass.
- 6 new harness tests against the real Microsoft Graph (`tests/harness/test_email_delete.py`): soft-delete + permanent-delete + 404-idempotency × /me + shared mailbox. Shared-mailbox tests skip unless `OUTLOOK_HARNESS_SHARED_MAILBOX_UPN` is set. Empirically revealed two Graph quirks not visible in mocks: (1) message ids rotate when items move between folders (the immutable-ID feature is opt-in), (2) Graph returns 400 (not 404) for malformed message-id URLs, so 404-idempotency tests must use real round-trip ids.

## [v0.5.0] — 2026-05-11

Attachments arrive — drafts can now carry files, no more "use a separate Graph client" workaround. Two new MCP-tool parameters; one new internal helper module.

### Added

- **`ol_email_create_draft` accepts `attachments: list[Attachment]`** and uploads each file to the freshly-created draft before returning. Returns `{draft_id, web_url, attachments: [{id, name, size}]}` so the caller can later remove specific items by id.
- **`ol_email_update_draft` accepts `add_attachments: list[Attachment]` + `remove_attachment_ids: list[str]`** with additive semantics — does NOT replace existing attachments. Returns `added_attachments` / `removed_attachment_ids` in the result. When ONLY attachment operations are requested (no `subject` / `body` / recipients), the tool skips the `PATCH /me/messages/{id}` step and just hits the `/attachments` endpoints, fetching the draft via GET for the return envelope.
- **`Attachment` schema** — dict with `name: str` plus exactly one of `content_path` (local file), `content_bytes_b64` (already-base64-encoded raw bytes), `content_url` (http/https URL — server downloads). Optional `content_type` (MIME); inferred from filename extension if absent. Schema is validated locally for every attachment in the list **before any HTTP call**, so a malformed third entry doesn't leave the first two half-uploaded.
- **Resumable uploads for files >3 MiB.** The helper picks single-shot POST vs `createUploadSession` automatically based on content size. Resumable path uses 8 MiB chunks (Graph's recommended boundary alignment), strips the Authorization header on the chunked PUTs (the uploadUrl is pre-authenticated by Graph), and falls back to a GET on the attachment list if the final chunk returns 2xx without a body.
- **New helper `outlook_mcp.tools._attachments`** with public-ish API: `validate_attachment`, `load_attachment_bytes`, `upload_attachment`, `attach_to_draft`, `remove_attachments`, plus `AttachmentSchemaError` exception (subclass of `ValueError` so existing handlers catch it without changes). Closes [#36](https://github.com/XMV-Solutions-GmbH/outlook-mcp/issues/36).

### Engineering

- 347 unit tests (was 318 — 23 new in `test_attachments.py` covering schema rules, all three content sources, single-shot vs resumable path selection, the 2xx-without-body fallback; 3 new in `test_email_create_draft.py`; 4 new in `test_email_update_draft.py`).

### Out of scope

- **Inline attachments** (`cid:` references in HTML body) — Phase 2; tracked as a follow-up because the round-trip differs (the attachment's `contentId` field needs to match the `<img src="cid:...">` reference in the body, and Graph treats inline attachments as a different attachment-type subtype). Plain attachments cover the dominant use case for v0.5.

## [v0.4.0] — 2026-05-11

**Breaking change** to the consent-env-var contract. Operators upgrading from v0.3.x must update their `.mcp.json` to set `OUTLOOK_ALLOW_DRAFTS` and `OUTLOOK_ALLOW_SEND` to exactly `"true"` or `"false"`; legacy truthy values (`1`, `yes`, `on`) and unset / empty are now rejected at startup. The motivation is the compliance-story upgrade described in [#37](https://github.com/XMV-Solutions-GmbH/outlook-mcp/issues/37) — the operator must consciously decide, not silently inherit a read-only default.

### Changed (breaking)

- **`OUTLOOK_ALLOW_DRAFTS` must be set to exactly `"true"` or `"false"`** (case-insensitive, trimmed). Any other value — including unset / empty / legacy `1`/`yes`/`on` — causes the server (and the CLI `login` subcommand) to refuse to start with a formatted onboarding-help message printed to stderr. Closes [#37](https://github.com/XMV-Solutions-GmbH/outlook-mcp/issues/37).
- **`OUTLOOK_ALLOW_SEND` is required when `OUTLOOK_ALLOW_DRAFTS=true`** and must also be exactly `"true"` or `"false"`. When `OUTLOOK_ALLOW_DRAFTS=false`, `OUTLOOK_ALLOW_SEND` is not checked (it would be dead config).
- **Server start is no longer silently read-only** when consent is unset. Previously the server fell through to read-only mode with an INFO log; operators commonly missed the log and assumed drafts were broken. The new error message is itself the documentation.

### Added

- **`outlook_mcp.auth.flow.OutlookConsentNotConfiguredError`** — new exception class raised by the strict consent parser. Re-exported from `auth.flow.__all__` so downstream tooling can catch it.
- **`outlook_mcp.auth.flow.validate_consent_config()`** — returns `(drafts_enabled, send_enabled)` or raises. Single source of truth; called from `_build_server()` at module import and from `cli.main()` before the login flow.
- **`outlook_mcp.auth.flow.ALLOW_DRAFTS_ENV`** — exported constant string `"OUTLOOK_ALLOW_DRAFTS"` (was hard-coded in `server.py` only).

### Migration from v0.3.x

Add the explicit decision to your `.mcp.json` env section:

```jsonc
{
  "mcpServers": {
    "outlook": {
      "command": "uvx",
      "args": ["mcp-server-outlook"],
      "env": {
        "OUTLOOK_ALLOW_DRAFTS": "false"   // or "true" + add OUTLOOK_ALLOW_SEND below
        // "OUTLOOK_ALLOW_SEND": "true"   // only when DRAFTS=true
      }
    }
  }
}
```

If you were already setting `OUTLOOK_ALLOW_DRAFTS=true` and `OUTLOOK_ALLOW_SEND=true` in v0.3.x, no change is needed (those values were already among the accepted truthy set and remain the exact-strict form). If you relied on legacy `1`/`yes`/`on`, change to `true`.

## [v0.3.1] — 2026-05-08

Patch fix for the v0.3.0 MCP-tool login flow.

### Fixed

- **`ol_login_begin` is now non-blocking.** The v0.3.0 implementation awaited the polling task before returning, so MCP clients that don't render progress notifications saw an empty response with no `user_code` and no `verification_url` until the device code expired — the user couldn't enter the code because they couldn't see it. The tool now returns immediately with `status="pending"` plus the user-facing fields after spawning the polling task in the background; the agent polls `ol_login_status` until the state flips to `signed_in` (or to a terminal `expired` / `failed`). Matches the canonical RFC design and the sister project's `sp_login_begin` shape.
- `force=True` now removes the cancelled session from the registry before atomic-inserting the replacement, eliminating a brief window where two sessions for the same profile could coexist.

### Removed

- Progress notifications during the poll loop. With the non-blocking design the tool returns before polling begins, so progress events have no synchronous return path to attach to. The agent uses `ol_login_status` for state changes instead — same end-user effect, simpler lifecycle.

## [v0.3.0] — 2026-05-08

First release after v0.1.0, bundling the v0.2 draft surface and the v0.3 login + send opt-in.

### Added — drafts (v0.2 milestone, never separately released)

- **`ol_email_create_draft(to, subject, body?, body_html?, cc?, bcc?)`** — creates a draft in the user's Drafts folder. `body` is Markdown (rendered via safe-mode `mistune`); `body_html` is raw HTML, mutually exclusive with `body`. Records the draft in the per-profile registry. Annotations: `readOnlyHint=False`, `destructiveHint=False` (drafts append, don't overwrite).
- **`ol_email_update_draft(draft_id, …)`** — PATCH `/me/messages/{id}`. **Defensive**: only mutates drafts in this profile's registry — hand-typed drafts in Outlook are off-limits, raising `DraftNotOwnedError` before any Graph call. `subject` / `body` / `body_html` use `None` = leave unchanged. `to` / `cc` / `bcc` use `None` = leave unchanged, `[]` = clear, `[…]` = set.
- **`ol_email_list_drafts(profile_only=True)`** — lists drafts. `profile_only=True` (default) is a pure registry read with no Graph call. `profile_only=False` round-trips Graph and overlays a `created_by_this_profile` flag per entry so the agent knows which it owns.
- **`ol_email_discard_draft(draft_id)`** — DELETE `/me/messages/{id}`. Same registry-defensive shape. 404 from Graph (already gone) is treated as success and the registry entry is cleaned up. Idempotent.
- **`ol_calendar_create_event_draft(subject, start, end, attendees?, body?, body_html?, location?, time_zone?)`** — POST `/me/events` with `responseRequested=false` so Microsoft Graph never auto-emails attendees. Conflict detection per [spike § 3](docs/spikes/2026-05-08-v02-drafts-spikes.md): warn-and-create — the draft IS created on overlap; the response carries a `warnings` array.
- **`ol_calendar_discard_event_draft(event_id)`** — DELETE `/me/events/{id}`, same defensive + 404-as-success shape as the email discard.
- **Markdown → HTML safe-mode renderer** (`outlook_mcp/markdown.py`) using `mistune>=3` with `escape=True`. `javascript:` link schemes are dropped; inline HTML is escaped. Used by `ol_email_create_draft` / `ol_email_update_draft` / `ol_calendar_create_event_draft` for `body=` Markdown input.
- **`User-Agent: mcp-server-outlook/<version>` header** on every Microsoft Graph request. Diagnostic trail aside from the `ClientAppId` / `AppDisplayName` audit-log attribution.
- **Drafts opt-in via `OUTLOOK_ALLOW_DRAFTS=true`.** Without the env flag, none of the draft tools are registered — same posture as the v0.1 read-only default.

### Added — MCP-tool login (v0.3 milestone)

- **Adopted [`mcp-microsoft-graph-auth>=0.1.1`](https://pypi.org/project/mcp-microsoft-graph-auth/)** as a runtime dependency. The auth primitives (Device Code flow, token store backends, service-principal mode, `LoginSession` + `LoginSessionRegistry`) now come from the shared library; `outlook_mcp/auth/` is a thin shim supplying Outlook-specific defaults (client_id, scopes, env-var prefix).
- **`ol_login_begin(force=False)`** — async MCP tool that drives the OAuth Device Code flow without leaving the agent dialogue. Initiates the flow, blocks until terminal status (success / expired / failed), persists the token via the configured TokenStore on success, populates the per-profile UPN cache. **Idempotent**: a non-expired pending session is joined, not duplicated. `force=True` cancels the in-flight session and starts fresh — replaces a separate `_cancel` tool. **Streams MCP progress notifications** (`time_remaining_s` countdown) when the calling client advertises the progress capability.
- **`ol_login_status()`** — three-state status tool with **active-probe semantics**: a user who logged in via the CLI hours / days ago shows as `signed_in`, NOT `none`. The check tries the configured TokenStore (with silent refresh) and falls through to the in-process `LoginSessionRegistry` only when no token is obtainable. Three states: `signed_in` (with `signed_in_user_upn`), `pending` (with `user_code` + `verification_url` + `time_remaining_s`), `none` (with optional `error` from a previous failed/expired/cancelled session).
- **UX guidance baked into both tools' MCP descriptions**: render `user_code` first in its own code block (no labels, no whitespace) and `verification_url` second as a plain auto-link (not in a code block). Minimises app-switching on mobile clients.
- **`ol_logout` is intentionally NOT exposed** as an MCP tool. Agent-driven logout is a footgun. CLI `mcp-server-outlook logout` stays for human-initiated use.

### Added — opt-in send (v0.3, "Option B")

- **`OUTLOOK_ALLOW_SEND=true` env flag** opts the deployment into a separate `ol_email_send_draft(draft_id)` tool AND extends the OAuth scope request to include `Mail.Send`. The default install does NOT request `Mail.Send`; the consent screen stays drafts-only out of the box.
- **`ol_email_send_draft(draft_id)`** — wraps `POST /me/messages/{id}/send`. Registry-defensive: only sends drafts this profile created (i.e. drafts the agent itself drafted via `ol_email_create_draft` / `ol_email_update_draft`, which the human can review in Outlook between draft and send). Annotations: `destructiveHint=True`, `idempotentHint=False`. The agent never autonomously sends — every send requires an explicit per-draft tool call.
- **Lazy scope resolver** (`outlook_mcp/auth/flow.py:resolve_scopes`) computes the OAuth scope set at request time, appending `Mail.Send` only when `OUTLOOK_ALLOW_SEND` is truthy. Backwards-compat alias `DEFAULT_SCOPES` kept for callers reading at module load.
- **Entra app updated**: `Mail.Send` added to the registered permission list of the multi-tenant app `mcp-server-outlook` (appId `5df367d9-…`). Tenant-wide admin consent granted in the XMV tenant. Privacy + terms pages on `xmv.de` documented to reflect the opt-in posture (drafts-only by default, opt-in for power users, never autonomous send).

### Changed

- Authentication primitives moved out to the shared library. Existing `outlook_mcp.auth` imports still work — the public API surface is preserved via re-exports.
- `tests/unit/test_server.py:test_no_send_tool_exists_anywhere` renamed to `test_no_send_tool_in_default_config` — the invariant now applies only to the default config; the explicit-opt-in path is excepted.
- README "Safety model" section grew from 3 layers to 4: send opt-in is its own layer between drafts and never-autonomous-send.

### Documentation

- New **`docs/spikes/2026-05-08-v02-drafts-spikes.md`** records the v0.2 design decisions (one Entra app vs two, audit attribution, calendar conflict warn-and-create, Markdown body format) plus a Revision 2026-05-08 § 1 supplement documenting the v0.3 move from "Mail.Send absent" to "Mail.Send registered, lazy-requested".
- New README sections: "Login from an MCP client" (the agent-driven flow), "Sending: opt-in via OUTLOOK_ALLOW_SEND".
- `docs/app-concept.md` "Login UX" section replaces the original 4-tool RFC with the agreed 2-tool design + an explicit "what changed from the RFC" header.
- `CLAUDE.md` "The never-auto-send rule" rewritten in three layers (default install never sends → opt-in is two-step → no autonomous send even with opt-in).

### Tests

- 312 unit + 1 integration green; +165 tests added across the v0.2 + v0.3 surface.
- Harness layer continues to exercise `GET /me` against real Microsoft Graph in CI; v0.3 send-tool harness gated behind `OUTLOOK_HARNESS_ALLOW_SEND_TEST=true` for opt-in verification.

### Known limitations (documented)

- Pending login sessions are in-process state. If the MCP server restarts mid-flow, the session is lost; the agent calls `ol_login_begin` again. Microsoft cleans up the abandoned device code automatically.
- The shared lib's TokenStore implementations do NOT file-lock writes. Concurrent CLI login + tool login on the same profile resolves as "last writer wins". Documented; tracked upstream as [`mcp-microsoft-graph-auth#15`](https://github.com/XMV-Solutions-GmbH/mcp-microsoft-graph-auth/issues/15).

## [v0.1.0] — 2026-05-08

### Added

- **Authentication**: OAuth 2.0 Device Code Flow against Microsoft Identity, silent refresh-token loop, three-tier token persistence (OS keyring / plain file mode 0600 / passphrase-encrypted file). Multi-profile support via `OUTLOOK_PROFILE`. BYO Entra app registration via `OUTLOOK_CLIENT_ID` / `OUTLOOK_TENANT_ID` for tenants with strict app-allowlisting. Service-principal mode (`OUTLOOK_AUTH_MODE=service-principal`) for unattended automation.
- **Read tools** (always registered): `ol_email_search`, `ol_email_list_unread`, `ol_email_read`, `ol_calendar_search`, `ol_calendar_list_events`, `ol_status`. Each tool wraps a single Microsoft Graph round-trip; bodies and headers are returned in flat shapes the agent can consume directly.
- **Never-auto-send guarantee**: `Mail.Send` is not requested in the default scopes, the Entra app registration does not list it, and no `send_*` tool exists in the MCP surface. Sending stays a manual action in Outlook — structurally, not by config flag.
- **MCP tool annotations** correctly applied to every tool (`readOnlyHint`, `idempotentHint`, `openWorldHint`) so MCP clients render appropriate permission prompts.
- **CLI**: `mcp-server-outlook login [--profile NAME]`, `mcp-server-outlook logout [--profile NAME]`, `mcp-server-outlook` (default — start the MCP server on stdio).
- **Test harness**: three layers (unit / integration / harness) per `ENGINEERING_PRINCIPLES.md` § 5. 147 unit tests + 1 integration test (88% coverage) plus a single harness gate that runs `GET /me` against the real Microsoft Graph in CI via the `OUTLOOK_HARNESS_TOKEN_JSON` repo secret.
- **Operator scripts**: `scripts/renew-harness-token.sh` (one-command monthly token rotation that also uploads the refreshed cache as a GitHub Actions secret) and `scripts/bootstrap-azure-app.sh` (idempotent Entra-app provisioning for the publisher).
- **Documentation**: README with quickstart + safety model + troubleshooting; engineering principles + project conventions (CLAUDE.md); testconcept; app-concept covering the never-auto-send rule and the v0.2 draft surface.

### Project layout

- Python package skeleton: `pyproject.toml` (hatchling, dual-license MIT OR Apache-2.0), `src/outlook_mcp/` layout.
- Tooling: ruff (lint + format, line-length 100, target py311), mypy (strict), pytest 8+ with auto-markers per layer.
- CI: lint + test + harness jobs in GitHub Actions on every push to `main` and intra-repo PR. Branch protection on `main` requires `lint` + `test` to be green and CODEOWNERS approval.
- Release pipeline: tag-driven OIDC Trusted-Publisher PyPI publish (`mcp-server-outlook`).

[Unreleased]: https://github.com/XMV-Solutions-GmbH/outlook-mcp/compare/v0.3.0...HEAD
[v0.3.0]: https://github.com/XMV-Solutions-GmbH/outlook-mcp/compare/v0.1.0...v0.3.0
[v0.1.0]: https://github.com/XMV-Solutions-GmbH/outlook-mcp/releases/tag/v0.1.0
