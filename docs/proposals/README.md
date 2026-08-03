<!--
SPDX-License-Identifier: MIT OR Apache-2.0
SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
SPDX-FileContributor: David Koller <david.koller@xmv.de>
-->

# Proposals & Decision Records

This directory holds **Decision Records** — permanent, findable records of
project-specific choices whose reasoning is not obvious from the code
(`ENGINEERING_PRINCIPLES.md` § 16).

## Lifecycle

A proposal moves through statuses recorded in its own front matter:

- `Draft` — under discussion.
- `Accepted` — decided, not yet fully implemented.
- `Implemented` — decided and shipped.
- `Superseded by NNNN` — replaced by a later record (never deleted).

Records are append-only history. A later decision that reverses or refines an
earlier one references the old record and explains the change; the old record
stays in place with its status flipped to `Superseded`.

## Format

Each record is `NNNN-short-slug.md` and captures at minimum:

- **What was decided** — the chosen option, stated plainly.
- **Why** — the constraints and trade-offs: costs accepted, benefits sought,
  alternatives discarded.
- **Consequences for future maintainers** — what assumptions are now baked in;
  what to revisit if the context changes.

## Index

| # | Title | Status |
|---|---|---|
| [0001](0001-mcp-2x-server-api.md) | Migrate the server layer to the mcp 2.x `MCPServer` API | Implemented |
