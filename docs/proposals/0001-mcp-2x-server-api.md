<!--
SPDX-License-Identifier: MIT OR Apache-2.0
SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
SPDX-FileContributor: David Koller <david.koller@xmv.de>
-->

# 0001 — Migrate the server layer to the mcp 2.x `MCPServer` API

- **Status:** Implemented
- **Date:** 2026-08-03

## Context

The package declared `mcp>=1.2` with no upper bound. When `mcp` 2.0.0 was
published, resolvers (`uv`, `pip`) began selecting it, and the server failed to
start: **mcp 2.x removed `mcp.server.fastmcp`**, the module the whole
registration layer was built on (`from mcp.server.fastmcp import Context,
FastMCP`). The only working install was the pin-down workaround `--with
"mcp<2"`. The decision was whether to migrate forward to the 2.x server API or
cap the dependency at `<2`.

## What was decided

**Migrate forward** to the in-SDK high-level server API that ships inside the
`mcp` package itself: `mcp.server.MCPServer` — the direct successor to
`FastMCP`. Dependency range set to `mcp>=2,<3`.

The migration is a like-for-like swap of the server plumbing; the 17 tools,
their schemas, descriptions and `ToolAnnotations` are unchanged:

- `from mcp.server.fastmcp import FastMCP` → `from mcp.server import MCPServer`.
- `from mcp.server.fastmcp import Context` → `from mcp.server.mcpserver import
  Context` (the `login_begin` `TYPE_CHECKING` import).
- `FastMCP(...)` → `MCPServer(...)`; type annotations updated accordingly.
- `ToolAnnotations` constructor kwargs converted from the camelCase aliases
  (`readOnlyHint=`) to the canonical snake_case field names (`read_only_hint=`).
  Runtime accepts both via pydantic aliases, but mypy-strict only knows the
  snake_case fields, and reading a listed tool's annotation back is
  snake_case-only in mcp 2.x.

The `@server.tool(...)` decorator, `list_tools()`, `run()` and
`Context.report_progress` keep the same shape, so the registration logic and the
never-auto-send / consent-flag gating are untouched.

## Why (alternatives discarded)

- **Cap at `mcp>=1.2,<2` (the safe fallback).** Would have unblocked
  `uv tool install` without the workaround, but freezes the package on an
  end-of-line major and defers the same migration. Rejected because the 2.x
  successor API proved to be a near drop-in — the forward path was low-risk
  once verified.
- **Adopt the standalone `fastmcp` PyPI package (v3.x).** A separate project with
  its own release cadence and a heavier dependency surface. Rejected: the `mcp`
  SDK already provides `MCPServer` in-tree, so no new dependency and no second
  server framework to track.

Feasibility was verified empirically before committing: `mcp==2.0.0` was
installed in isolation and probed — `mcp.server.fastmcp` is gone, but
`mcp.server.MCPServer` exposes `.tool(annotations=, description=)`,
`.list_tools()`, `.name`, `.run()` and `Context[Any, Any]`, and `ToolAnnotations`
survives in `mcp.types`.

## Consequences for future maintainers

- The floor is now `mcp>=2`; do not reintroduce `mcp.server.fastmcp` imports.
- `ToolAnnotations` fields are snake_case (`read_only_hint`, `destructive_hint`,
  `idempotent_hint`, `open_world_hint`). Construct and read them in snake_case.
- The upper cap `<3` is a guard against the next major repeating this break;
  revisit it deliberately when `mcp` 3.x lands.
