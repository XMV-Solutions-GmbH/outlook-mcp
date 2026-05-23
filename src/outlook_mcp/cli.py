# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Command-line entry point.

Three commands:

- `mcp-server-outlook login [--profile NAME]` — interactive Device
  Code flow, persists the resulting tokens to the configured
  TokenStore. Run once per profile; subsequent MCP-server starts
  use the cached refresh token silently.
- `mcp-server-outlook logout [--profile NAME]` — clears cached
  credentials.
- `mcp-server-outlook` (no command) — starts the MCP server on stdio.
  This is what `.mcp.json` invokes.

The login/logout subcommands deliberately mirror the `gh auth login`
/ `gh auth logout` pattern: auth setup is out-of-band, the running
MCP process never blocks for human interaction.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from outlook_mcp import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp-server-outlook",
        description=(
            "MCP server for Microsoft 365 Outlook (mail + calendar) with "
            "audit-preserving drafts and never-auto-send."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    login_p = subparsers.add_parser(
        "login",
        help="Sign in via Microsoft Device Code flow and cache the refresh token.",
    )
    login_p.add_argument(
        "--profile",
        default="default",
        help="Profile name (namespace for token cache). Default: 'default'.",
    )
    login_p.add_argument(
        "--account-type",
        choices=("personal", "work_or_school"),
        default=None,
        help=(
            "Which kind of Microsoft account to sign in with. "
            "'personal' for outlook.com / hotmail.com / live.com / msn.com "
            "(routes to Microsoft Identity /consumers, landing page "
            "https://www.microsoft.com/link). "
            "'work_or_school' for any Microsoft 365 tenant account incl. "
            "B2B guests (routes to /organizations, landing page "
            "https://login.microsoft.com/device). REQUIRED unless "
            "OUTLOOK_TENANT_ID is set as an explicit power-user override."
        ),
    )

    logout_p = subparsers.add_parser(
        "logout",
        help="Remove cached credentials for a profile.",
    )
    logout_p.add_argument(
        "--profile",
        default="default",
        help="Profile name. Default: 'default'.",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse CLI arguments and dispatch to the right subcommand.

    Returns the process exit code.

    For both `login` and the default server-start path, validates the
    consent env vars (`OUTLOOK_ALLOW_DRAFTS` / `OUTLOOK_ALLOW_SEND`)
    up-front — if either is unset or has a non-`true`/`false` value,
    prints the help text and exits 2. The CLI `logout` subcommand
    skips this check because clearing a cached token doesn't depend
    on the operator's draft/send decision.
    """
    import sys

    from outlook_mcp.auth.flow import (
        OutlookConsentNotConfiguredError,
        validate_consent_config,
    )

    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command != "logout":
        try:
            validate_consent_config()
        except OutlookConsentNotConfiguredError as err:
            sys.stderr.write(str(err) + "\n")
            return 2

    if args.command == "login":
        from outlook_mcp.auth import LoginAccountTypeRequiredError, interactive_login

        try:
            interactive_login(
                profile=args.profile,
                account_type=args.account_type,
            )
        except LoginAccountTypeRequiredError as err:
            sys.stderr.write(str(err) + "\n")
            return 2
        return 0

    if args.command == "logout":
        from outlook_mcp.auth.store import get_token_store

        get_token_store().delete(args.profile)
        return 0

    # No subcommand — start the MCP server on stdio.
    from outlook_mcp.server import run

    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
