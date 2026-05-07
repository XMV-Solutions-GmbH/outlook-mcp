#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0
#
# assign-repo-to-team.sh
#
# Assigns the repository to a team with write access.
# Configuration is loaded from repo.ini in the repository root.
#
# Usage:
#   ./.github/gh-scripts/assign-repo-to-team.sh
#
# Environment variables can override repo.ini values:
#   ORG, REPO, TEAM_SLUG

set -euo pipefail

# ---------------------------
# Load configuration
# ---------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
CONFIG_FILE="${REPO_ROOT}/repo.ini"

if [[ -f "${CONFIG_FILE}" ]]; then
  echo ">> Loading configuration from repo.ini"
  # shellcheck source=/dev/null
  source "${CONFIG_FILE}"
else
  echo "WARNING: repo.ini not found, using defaults/environment variables" >&2
fi

# ---------------------------
# Configuration (override via env)
# ---------------------------
ORG="${ORG:-XMV-Solutions-GmbH}"
REPO="${REPO:-oss-project-template}"
TEAM_SLUG="${TEAM_SLUG:-open-source}"

# ---------------------------
# Helpers
# ---------------------------
require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: Missing required command: $1" >&2
    exit 1
  }
}

# ---------------------------
# Preconditions
# ---------------------------
require_cmd gh

if ! gh auth status >/dev/null 2>&1; then
  echo "ERROR: gh is not authenticated. Run: gh auth login" >&2
  exit 1
fi

# ---------------------------
# Execute
# ---------------------------
FULL_REPO="${ORG}/${REPO}"

echo ">> Granting write access to team '${TEAM_SLUG}' on repo '${FULL_REPO}'"

gh api -X PUT "orgs/${ORG}/teams/${TEAM_SLUG}/repos/${ORG}/${REPO}" \
  -H "Accept: application/vnd.github+json" \
  -f permission="push"

echo ">> Done."