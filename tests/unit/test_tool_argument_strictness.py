# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unknown tool arguments must fail loudly, on every tool.

An MCP client that misremembers a parameter name is the normal case,
not the exotic one: the agent calling the tool is a language model
reading a description. Silently dropping the argument it invented
turns a typo into wrong output that nobody is told about — a
`body_type="html"` that never existed got ignored, the body went
through the safe-mode Markdown renderer instead, and the human
received drafts with visible `<p>` tags.

Both halves are pinned here: the advertised JSON schema says
`additionalProperties: false` so a well-behaved client rejects the
call before it is made, and the server refuses it regardless of what
the client does.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from outlook_mcp import server as server_module


def _all_tools(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Build a server with every optional tool tier registered, so no
    tool escapes the sweep just because its flag defaults to off."""
    for name in (
        "OUTLOOK_ALLOW_DRAFTS",
        "OUTLOOK_ALLOW_SEND",
        "OUTLOOK_ALLOW_SHARED_MAILBOXES",
        "OUTLOOK_ALLOW_DELETE",
        "OUTLOOK_ALLOW_GROUP_MAILBOXES",
    ):
        monkeypatch.setenv(name, "true")
    built = server_module._build_server()
    return {tool.name: tool for tool in built._tool_manager.list_tools()}


def test_every_tool_advertises_additional_properties_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools = _all_tools(monkeypatch)
    assert tools, "no tools registered — the sweep would be vacuous"
    offenders = [
        name
        for name, tool in tools.items()
        if tool.parameters.get("additionalProperties") is not False
    ]
    assert offenders == []


def test_every_tool_rejects_an_unknown_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    tools = _all_tools(monkeypatch)
    for name, tool in tools.items():
        # The model itself forbids extras (this is what makes the
        # advertised schema honest) ...
        with pytest.raises(ValidationError):
            tool.fn_metadata.arg_model.model_validate({"definitely_not_a_parameter": "x"})
        # ... and so does the path a real tool call takes.
        with pytest.raises(ValueError, match="definitely_not_a_parameter") as excinfo:
            tool.fn_metadata.validate_arguments({"definitely_not_a_parameter": "x"})
        assert name in str(excinfo.value)


def test_rejection_names_the_accepted_parameters(monkeypatch: pytest.MonkeyPatch) -> None:
    """The message has to be usable by the agent that got it wrong:
    it must say which argument was rejected AND what the real ones
    are, or the next attempt is another guess."""
    tools = _all_tools(monkeypatch)
    tool = tools["ol_email_create_draft"]

    with pytest.raises(ValueError, match="body_type") as excinfo:
        tool.fn_metadata.validate_arguments(
            {"to": ["a@b.de"], "subject": "s", "body": "b", "body_type": "html"}
        )

    message = str(excinfo.value)
    assert "body_type" in message
    assert "body_html" in message  # the parameter the caller actually meant


def test_valid_arguments_still_validate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The strictness must not cost us the normal path — defaults,
    optional arguments and aliases all keep working."""
    tools = _all_tools(monkeypatch)
    kwargs = tools["ol_email_search"].fn_metadata.validate_arguments({"query": "rechnung"})
    assert kwargs["query"] == "rechnung"
    assert kwargs["limit"] == 25
    assert kwargs["mailbox"] is None
