<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Tracked in the v0.2 backlog (drafts) — see [GitHub Issues](https://github.com/XMV-Solutions-GmbH/outlook-mcp/issues).

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

[Unreleased]: https://github.com/XMV-Solutions-GmbH/outlook-mcp/compare/v0.1.0...HEAD
[v0.1.0]: https://github.com/XMV-Solutions-GmbH/outlook-mcp/releases/tag/v0.1.0
