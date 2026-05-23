#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
#
# One-shot harness token renewal for mcp-server-outlook CI.
#
# Two profiles, picked via the optional first argument:
#
#   ./scripts/renew-harness-token.sh                  → harness (work/school, default)
#   ./scripts/renew-harness-token.sh harness          → same as above
#   ./scripts/renew-harness-token.sh harness-personal → personal Microsoft account
#
# Run this once a month per profile (whenever Microsoft's refresh-token
# TTL is about to expire and CI starts hitting "refresh token rejected"
# in the harness job). Workflow:
#
#   1. Open a browser to the Microsoft Device Code URL.
#   2. You sign in as the chosen test user.
#   3. Token is cached locally at ~/.cache/outlook-mcp/{profile}/token.json
#   4. Same token is base64-encoded and uploaded to the GitHub repo as
#      the matching secret, where CI picks it up.
#
# Profile → secret mapping:
#
#   harness          → OUTLOOK_HARNESS_TOKEN_JSON
#   harness-personal → OUTLOOK_HARNESS_PERSONAL_TOKEN_JSON
#
# That's it — no other manual steps. CI is guided through the whole
# renewal via this single command.
#
# Prerequisites (one-time on a new dev machine):
#   - `gh auth login` (GitHub CLI logged in to the repo)
#   - `uv` installed (https://docs.astral.sh/uv/)
#   - This repo cloned + `uv sync --extra dev` once.

set -euo pipefail

REPO="XMV-Solutions-GmbH/outlook-mcp"
PROFILE="${1:-harness}"
case "${PROFILE}" in
  harness)
    SECRET_NAME="OUTLOOK_HARNESS_TOKEN_JSON"
    ACCOUNT_TYPE="work_or_school"
    ;;
  harness-personal)
    SECRET_NAME="OUTLOOK_HARNESS_PERSONAL_TOKEN_JSON"
    ACCOUNT_TYPE="personal"
    ;;
  *)
    printf '\033[0;31mERROR: unknown profile %q.\033[0m\n' "${PROFILE}" >&2
    printf 'Valid profiles: harness, harness-personal\n' >&2
    exit 2
    ;;
esac
TOKEN_PATH="${HOME}/.cache/outlook-mcp/${PROFILE}/token.json"

red()   { printf '\033[0;31m%s\033[0m\n' "$*"; }
green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
blue()  { printf '\033[0;34m%s\033[0m\n' "$*"; }
yellow(){ printf '\033[0;33m%s\033[0m\n' "$*"; }

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || {
        red "ERROR: missing required command: $1"
        exit 1
    }
}

require_cmd gh
require_cmd uv
require_cmd base64

# Ensure gh is logged in to the right repo
if ! gh auth status >/dev/null 2>&1; then
    red "ERROR: gh is not authenticated. Run: gh auth login"
    exit 1
fi

if ! gh repo view "${REPO}" >/dev/null 2>&1; then
    red "ERROR: cannot access repo ${REPO} via gh. Check `gh auth status` + your access."
    exit 1
fi

blue ">> Step 1/3: Sign in via Microsoft Device Code flow (profile: ${PROFILE}, account_type: ${ACCOUNT_TYPE})"
yellow "    A URL + code will be printed below; sign in with the matching ${ACCOUNT_TYPE} account."
echo

# Force the plain-file backend so we always know where the token lands.
# `--account-type` is per #49: routes to /consumers for personal MSAs and
# /organizations for work/school. No more OUTLOOK_TENANT_ID env-var hack.
OUTLOOK_TOKEN_STORE=file uv run mcp-server-outlook login \
    --profile "${PROFILE}" \
    --account-type "${ACCOUNT_TYPE}"

if [[ ! -f "${TOKEN_PATH}" ]]; then
    red "ERROR: expected ${TOKEN_PATH} after login, but it is missing."
    exit 1
fi

green ">> Token cached at ${TOKEN_PATH}"
echo

blue ">> Step 2/3: Verify the token actually works against Microsoft Graph"
uv run python -c "
import os, sys
os.environ.setdefault('OUTLOOK_TOKEN_STORE', 'file')
import httpx
from outlook_mcp.auth import get_token
token = get_token(profile='${PROFILE}')
r = httpx.get('https://graph.microsoft.com/v1.0/me',
              headers={'Authorization': f'Bearer {token}'},
              timeout=30.0)
r.raise_for_status()
p = r.json()
print(f'    Signed in as: {p[\"userPrincipalName\"]} (id={p[\"id\"]})')
"
green ">> /me round-trip OK"
echo

blue ">> Step 3/3: Upload token cache as GitHub repo secret ${SECRET_NAME}"
# Use a tempfile + stdin redirection rather than a printf | pipe.
# Empirically, `printf '%s' "$VAR" | gh secret set --body -` produced
# secrets that GitHub Actions later rejected as "base64: invalid input"
# (likely a subtle shell-pipe mangling for very long single-line
# payloads). Stdin redirection is bytes-exact.
TMPFILE="$(mktemp)"
trap 'rm -f "${TMPFILE}"' EXIT
base64 -w0 < "${TOKEN_PATH}" > "${TMPFILE}"
gh secret set "${SECRET_NAME}" --repo "${REPO}" < "${TMPFILE}"
green ">> Secret ${SECRET_NAME} uploaded to ${REPO} ($(wc -c < "${TMPFILE}") base64 bytes)."
echo

green "✓ Done. CI's harness job will use the new token on its next run."
yellow "  Verify with:  gh run list --repo ${REPO} --workflow ci.yml --limit 1"
