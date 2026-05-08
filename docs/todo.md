<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# Project Todo

> **Frozen.** This file is a leftover from the OSS project template. New work for `mcp-server-outlook` lives in [GitHub Issues](https://github.com/XMV-Solutions-GmbH/outlook-mcp/issues), milestoned to releases (`v0.1.0 — MVP`, `v0.2.0`, …). See [CLAUDE.md § Project-specific tracking](../CLAUDE.md#project-specific-tracking).

## v0.1 — what's in this initial scaffold

The first scaffold ships:

- Auth stack — Device Code flow, three-tier token store, service-principal mode.
- MCP server with `ol_email_search`, `ol_email_list_unread`, `ol_email_read`, `ol_calendar_search`, `ol_calendar_list_events`, `ol_status`.
- CLI: `mcp-server-outlook login|logout`.
- Three-layer test harness (unit / integration / harness) with `respx` for HTTP mocking.
- CI: lint + test + harness jobs in GitHub Actions.
- Release pipeline: tag push → `pypi` Trusted-Publisher OIDC publish.

## Open tech-spike questions

Tracked in [docs/app-concept.md § Open questions for the tech spike](app-concept.md#open-questions-for-the-tech-spike). Resolve before v0.2 ships drafts.
