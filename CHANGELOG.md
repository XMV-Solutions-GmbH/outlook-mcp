<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Authentication**: OAuth 2.0 Device Code Flow against Microsoft Identity, silent refresh-token loop, three-tier token persistence (OS keyring / plain file mode 0600 / passphrase-encrypted file). Multi-profile support via `OUTLOOK_PROFILE`. BYO Entra app registration via `OUTLOOK_CLIENT_ID` / `OUTLOOK_TENANT_ID` for tenants with strict app-allowlisting.
- **Read tools** (always registered): `ol_email_search`, `ol_email_list_unread`, `ol_email_read`, `ol_calendar_search`, `ol_calendar_list_events`, `ol_status`.
- **MCP tool annotations** correctly applied to every tool (`readOnlyHint`, etc.) so MCP clients render appropriate permission prompts.
- **CLI**: `mcp-server-outlook login [--profile NAME]`, `mcp-server-outlook logout [--profile NAME]`, `mcp-server-outlook` (default — start the MCP server on stdio).
- **Test harness**: three layers (unit / integration / harness) with the harness layer running against a real Microsoft 365 sandbox in CI via the `OUTLOOK_HARNESS_TOKEN_JSON` repo secret.
- **Documentation**: README with quickstart + safety model + troubleshooting; engineering principles + project conventions; testconcept; app-concept covering the never-auto-send rule.

### Project layout

- Python package skeleton: `pyproject.toml` (hatchling, dual-license MIT OR Apache-2.0), `src/outlook_mcp/` layout.
- Tooling: ruff (lint + format, line-length 100, target py311), mypy (strict), pytest 8+ with auto-markers per layer.
- CI: lint + test + harness jobs in GitHub Actions on every push to `main` and intra-repo PR.

[Unreleased]: https://github.com/XMV-Solutions-GmbH/outlook-mcp/compare/v0.1.0...HEAD
