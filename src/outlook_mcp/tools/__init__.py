# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""MCP tool implementations.

Each `ol_*` tool lives in its own module as a pure function that takes
explicit `profile` + `http` parameters for testability. The MCP-server
layer (`outlook_mcp.server`) registers these as MCP tools, deriving
`profile` from the `OUTLOOK_PROFILE` env var and applying the right
annotations (readOnlyHint / destructiveHint / etc.) per tool.
"""
