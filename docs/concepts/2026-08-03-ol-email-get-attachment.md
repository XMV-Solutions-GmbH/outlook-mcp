<!--
SPDX-License-Identifier: MIT OR Apache-2.0
SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
SPDX-FileContributor: David Koller <david.koller@xmv.de>
-->

# Implementation concept — `ol_email_get_attachment`

Status: draft → review → revise. Single source of truth for the *how*; the *what/why*
is the app-concept (`docs/app-concept.md`, which already lists this tool as planned
v0.2 surface, lines 58 and 318) and the tracking issue.

## Requirements summary (the *what*)

A read tool that downloads **one** file attachment of a mail as raw bytes via Microsoft
Graph, writes it to a local file, and returns the local path plus metadata. Closes the
last unshipped item of the v0.2 batch (issue #8) — the app-concept already advertises
`ol_email_get_attachment(message_id, attachment_id) → attachment bytes to a local
temp file`.

### Tool signature (final)

```text
ol_email_get_attachment(
    message_id: str,
    attachment_id: str,
    save_dir: str | None = None,     # default: a per-call temp dir under the OS tmp root
    filename: str | None = None,     # default: the attachment's own name (sanitised)
    overwrite: bool = False,         # refuse to clobber an existing file unless True
    mailbox: str | None = None,      # shared-mailbox UPN; gated by OUTLOOK_ALLOW_SHARED_MAILBOXES
) -> dict
```

Returns:

```text
{
    "path": "/abs/local/path/Contract.docx",
    "name": "Contract.docx",            # Graph attachment name
    "content_type": "application/...",  # Graph contentType
    "size": 12345,                       # bytes actually written (== len(decoded))
    "attachment_id": "<att id>",
    "message_id": "<message id>",
    "mailbox": null,                     # echoes the mailbox arg for audit correlation
    "is_inline": false,
}
```

Naming: read-only, always registered, follows the `ol_email_*` convention. Sits in
`register_read_tools`. Read tier — no new consent flag; the `mailbox` parameter reuses
the existing `OUTLOOK_ALLOW_SHARED_MAILBOXES` gate via `_guard_mailbox`.

## Graph mechanics (the *how*)

`GET /{box}/messages/{message_id}/attachments/{attachment_id}` returns the attachment
resource as JSON. For a **fileAttachment** this includes `name`, `contentType`, `size`,
`isInline`, `@odata.type == "#microsoft.graph.fileAttachment"`, and `contentBytes`
(base64 of the raw file). We decode `contentBytes` and write the bytes.

Why this endpoint and not `.../attachments/{id}/$value`:

- `$value` returns only raw bytes, no `name` / `contentType` / `size` metadata, and it
  is **only valid for fileAttachment** (Graph 400s on item/reference). We would need a
  second GET for the metadata anyway. One JSON GET gives bytes + metadata together.
- The v0.5 upload helper (`_attachments.py`) already uses the base64-`contentBytes`
  shape on the write side; mirroring it on the read side keeps the two symmetric.

`{box}` comes from the existing `mailbox_path(mailbox)` helper (`me` or
`users/{quoted-upn}`), identical to every other email tool.

### Attachment-type handling

Graph has three `@odata.type`s:

- `#microsoft.graph.fileAttachment` — the only one with `contentBytes`. Supported.
- `#microsoft.graph.itemAttachment` — an embedded Outlook item (mail/event/contact); no
  `contentBytes`. **Reject** with a clear `ValueError` naming the type — downloading an
  embedded item is out of scope (would need `?$expand=microsoft.graph.itemAttachment/item`
  and a serialisation decision).
- `#microsoft.graph.referenceAttachment` — a link to a cloud file (OneDrive/SharePoint);
  no bytes in Graph. **Reject** with a `ValueError` pointing at `sharepoint-mcp`.

Inline attachments (`isInline == true`) are **not** filtered here: the caller passed a
specific `attachment_id`, so honouring it is correct (they may want the inline image).
`is_inline` is echoed in the result so the agent knows what it got. Filtering of inline
attachments is a *listing* concern (`ol_email_read include_attachments=True` already
surfaces `is_inline`), not a *get-by-id* concern.

## Files touched

| File | Change |
|---|---|
| `src/outlook_mcp/tools/email_get_attachment.py` | **New** — `get_attachment(...)` helper (pure-ish, `http` injectable like siblings). |
| `src/outlook_mcp/server.py` | Register `ol_email_get_attachment` in `register_read_tools`, with `_guard_mailbox(mailbox)`; read-only annotations. |
| `tests/unit/tools/test_email_get_attachment.py` | **New** — schema/sunny/error paths (respx). |
| `tests/unit/test_server.py` | Add `ol_email_get_attachment` to the always-registered read-tool set assertion. |
| `tests/harness/test_email_get_attachment.py` | **New** — real Graph: seed a draft with a known attachment, download it, assert bytes/size/type; error paths. |
| `README.md` | Document the new tool in the tool table + usage. |
| `CHANGELOG.md` | `Added` entry under `[Unreleased]`. |
| `docs/app-concept.md` | Move `ol_email_get_attachment` out of "Out of scope for v0.x" (line 318) into shipped surface. |
| `src/outlook_mcp/tools/email_read.py` + `server.py` desc | Drop the "deferred to v0.2 ol_email_get_attachment" phrasing now it ships. |
| `src/outlook_mcp/__init__.py`, `pyproject.toml` | Version bump 0.7.0 → 0.8.0 (release phase). |

## Local-path safety (the load-bearing risk)

The attachment `name` comes from an **untrusted** source (the sender chose the filename).
Writing it verbatim into `save_dir` is a path-traversal vector (`../../etc/...`, absolute
paths, NUL bytes). Mitigation:

- Derive the on-disk filename from `filename` if the caller gave one, else the Graph
  `name`.
- Sanitise: take **only the basename** (`os.path.basename` after stripping any
  backslashes too), reject/replace empty, `.`, `..`; fall back to
  `attachment-{attachment_id-ish}` if the sanitised name is empty.
- Resolve `save_dir` and the final path, and assert the resolved path stays **inside**
  the resolved `save_dir` — belt-and-braces against clever encodings.
- `overwrite=False` (default): if the target exists, raise `FileExistsError` rather than
  clobber.

`save_dir=None` → create a fresh `tempfile.mkdtemp(prefix="outlook-mcp-att-")` so
parallel calls never collide and no caller-supplied dir is required for the common case.

## Error cases (each gets a test)

| Case | Behaviour |
|---|---|
| empty/whitespace `message_id` | `ValueError` (mirrors `read_email`). |
| empty/whitespace `attachment_id` | `ValueError`. |
| whitespace-only `mailbox` | `ValueError` from `mailbox_path` ("non-empty UPN"). |
| message or attachment not found | Graph 404 → `httpx.HTTPStatusError` propagates. |
| `mailbox` set, no FullAccess | Graph 403 → propagates. |
| `mailbox` set, flag off | `_guard_mailbox` raises `PermissionError` (server layer). |
| itemAttachment / referenceAttachment | `ValueError` naming the unsupported type. |
| target file exists, `overwrite=False` | `FileExistsError`. |
| path traversal in name | sanitised to basename; never escapes `save_dir`. |

## Testability (three layers)

- **Unit** — respx mocks the single GET; assert URL shape (`/me/` vs `/users/{upn}/`),
  base64 decode → bytes on disk, metadata echo, type rejection, path sanitisation,
  overwrite guard, input validation. No real I/O beyond a `tmp_path`.
- **Integration** — covered by the lifecycle suite only if a natural fit; the tool is a
  single GET so unit+harness is the honest split (noted in the concept per EP § 5 "or
  explicitly justifies why unit/integration suffices").
- **Harness** — real Microsoft Graph: seed a throwaway draft, upload a known
  small attachment (reusing `_attachments.upload_attachment`), GET it back via the tool,
  assert `size`/`content_type`/bytes match; assert a bogus attachment id 404s; clean up
  the draft in `finally`. Shared-mailbox variant skips unless
  `OUTLOOK_HARNESS_SHARED_MAILBOX_UPN` is set (same pattern as `test_email_delete.py`).
  Plus the brief's real 7-attachment mail is exercised as a one-off manual harness run,
  not committed (its id is tenant-specific).

## Definition of done / operator acceptance

- [ ] Full local ladder green (unit + integration + harness).
- [ ] `tools/list` shows `ol_email_get_attachment` with read-only annotations.
- [ ] README + CHANGELOG + app-concept updated.
- [ ] Real download of ≥2 attachments from the brief's test mail verified (size + type).
