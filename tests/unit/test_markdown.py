# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the Markdown -> HTML renderer used by v0.2 draft bodies.

Pins the safe-mode behaviour described in
docs/spikes/2026-05-08-v02-drafts-spikes.md § 4. Inline-HTML and
dangerous URI schemes must stay disabled — a draft body that ships
to the Drafts folder must not be a phishing payload.
"""

from __future__ import annotations

from outlook_mcp.markdown import markdown_to_html


def test_empty_string_returns_empty() -> None:
    assert markdown_to_html("") == ""


def test_paragraph_renders_as_p_tag() -> None:
    out = markdown_to_html("Hello world.")
    assert "<p>Hello world.</p>" in out


def test_bold_and_italic() -> None:
    out = markdown_to_html("**bold** and *italic*")
    assert "<strong>bold</strong>" in out
    assert "<em>italic</em>" in out


def test_unordered_list() -> None:
    out = markdown_to_html("- one\n- two\n- three")
    assert "<ul>" in out
    assert "<li>one</li>" in out
    assert "<li>three</li>" in out


def test_ordered_list() -> None:
    out = markdown_to_html("1. first\n2. second")
    assert "<ol>" in out
    assert "<li>first</li>" in out


def test_link_https_is_rendered() -> None:
    out = markdown_to_html("[XMV](https://xmv.de)")
    assert '<a href="https://xmv.de">XMV</a>' in out


def test_link_javascript_scheme_is_blocked() -> None:
    """The most important safe-mode property: dangerous URI schemes
    must not survive the renderer. mistune in safe mode will either
    drop the href or render the text without the link wrapper —
    either way, the literal `javascript:` string must not appear in
    an `href` attribute."""
    out = markdown_to_html('[click](javascript:alert("x"))')
    assert 'href="javascript:' not in out


def test_inline_html_is_escaped() -> None:
    out = markdown_to_html('<script>alert("x")</script>')
    # The literal <script> tag must not survive — it must be
    # escaped to text or stripped.
    assert "<script>" not in out
    # Some safe-mode renderers escape, others remove. Either is fine
    # as long as the executable form is gone.


def test_inline_html_in_paragraph_is_escaped() -> None:
    out = markdown_to_html("This is <b>not</b> bold.")
    # The raw <b> tag should be escaped, not rendered as a tag.
    assert "<b>not</b>" not in out
    assert "&lt;b&gt;" in out or "&lt;b" in out


def test_code_block_is_preserved() -> None:
    out = markdown_to_html("```\nsome code\n```")
    assert "<code>" in out
    assert "some code" in out


def test_inline_code() -> None:
    out = markdown_to_html("call `foo()` now")
    assert "<code>foo()</code>" in out


def test_headings_render() -> None:
    out = markdown_to_html("# Title\n\n## Subtitle")
    assert "<h1>Title</h1>" in out
    assert "<h2>Subtitle</h2>" in out


def test_paragraph_break_on_blank_line() -> None:
    out = markdown_to_html("First paragraph.\n\nSecond paragraph.")
    assert out.count("<p>") == 2


def test_single_newline_does_not_force_break() -> None:
    """hard_wrap=False — single newline within a paragraph stays
    soft, doesn't insert <br/>. Email bodies use double-newline
    for real paragraph breaks."""
    out = markdown_to_html("Line one\nLine two")
    # Both lines collapse into one paragraph, no <br/> inserted.
    assert "<br" not in out
