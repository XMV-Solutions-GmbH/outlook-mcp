# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Markdown -> HTML rendering for v0.2 draft bodies.

Microsoft Graph's `POST /me/messages` accepts a `body` object with a
`contentType` of `"text"` or `"html"` — no native Markdown. The v0.2
draft tools (`ol_email_create_draft`, `ol_calendar_create_event_draft`)
default to Markdown input because that's the format agents emit
naturally; we render it server-side to HTML before posting.

**Safe by default.** `mistune` is initialised with `escape=True`,
which:

- HTML-escapes any raw HTML in the Markdown source (prevents
  agents from accidentally embedding <script> or styled spam).
- Drops dangerous URI schemes on links (`javascript:`, `data:`,
  `vbscript:` etc. become inert text).

Agents that need precise HTML control pass `body_html=...` directly
to the draft tools, bypassing this renderer.

Rationale + alternatives considered in
docs/spikes/2026-05-08-v02-drafts-spikes.md § 4.
"""

from __future__ import annotations

import mistune

# `hard_wrap=False` matches GitHub-flavoured Markdown semantics:
# single newlines are joined, double newlines split paragraphs.
# Email bodies usually have meaningful paragraph breaks, not
# meaningful single-newline breaks.
_renderer = mistune.create_markdown(escape=True, hard_wrap=False)


def markdown_to_html(md: str) -> str:
    """Render a Markdown string to safe HTML.

    Wrapping in a function (rather than exposing the configured
    renderer instance directly) keeps the call site independent of
    mistune's API and lets us replace the implementation later
    without touching every caller.

    Empty input returns an empty string. The mistune renderer itself
    handles non-string input by raising; callers should pre-validate
    if they accept untrusted shapes.
    """
    if not md:
        return ""
    rendered = _renderer(md)
    # mistune 3.x returns str directly; older 2.x returned a list-like
    # in some configurations. Coerce defensively.
    if isinstance(rendered, str):
        return rendered
    return str(rendered)
