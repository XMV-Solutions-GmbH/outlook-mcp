#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0
#
# setup-branch-protection.sh
#
# Sets PR-only branch protection for the default branch (usually main),
# restricts direct pushes to a maintainer team, and requires CI status checks.
# Configuration is loaded from repo.ini in the repository root.
#
# Usage:
#   ./.github/gh-scripts/setup-branch-protection.sh
#
# Environment variables can override repo.ini values:
#   ORG, REPO, BRANCH, TEAM_SLUG, REQUIRED_APPROVALS, etc.
#
# IMPORTANT:
# The required status check contexts MUST match the workflow/job names.
# Configure STATUS_CHECKS in repo.ini to match your CI workflow job names.

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
BRANCH="${BRANCH:-main}"
TEAM_SLUG="${TEAM_SLUG:-open-source}"

# PR review rules
REQUIRED_APPROVALS="${REQUIRED_APPROVALS:-0}"
REQUIRE_CODEOWNER_REVIEWS="${REQUIRE_CODEOWNER_REVIEWS:-false}"
DISMISS_STALE_REVIEWS="${DISMISS_STALE_REVIEWS:-true}"

# Admin enforcement
ENFORCE_ADMINS="${ENFORCE_ADMINS:-true}"

# Required status checks (comma-separated string from repo.ini)
# Format: "check1,check2" - commas separate checks, spaces are preserved within check names
# Example: "CI / lint,CI / test" results in two checks: "CI / lint" and "CI / test"
STATUS_CHECKS_STRING="${STATUS_CHECKS:-lint,test}"

# Convert comma-separated string to array, preserving spaces within check names
IFS=',' read -ra STATUS_CHECKS_ARRAY <<< "${STATUS_CHECKS_STRING}"

# Optional: allow certain actors to push to main besides team
EXTRA_USERS="${EXTRA_USERS:-}"
EXTRA_APPS="${EXTRA_APPS:-}"

FULL_REPO="${ORG}/${REPO}"

# ---------------------------
# Helpers
# ---------------------------
require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: Missing required command: $1" >&2
    exit 1
  }
}

split_csv_to_json_array() {
  local csv="${1:-}"
  if [[ -z "${csv}" ]]; then
    echo "[]"
    return
  fi
  local normalized
  normalized="$(echo "${csv}" | sed 's/[[:space:]]//g')"
  echo "${normalized}" | awk -F',' '{
    printf("[");
    for (i=1; i<=NF; i++) {
      printf("\"%s\"", $i);
      if (i<NF) printf(",");
    }
    printf("]");
  }'
}

json_array_from_bash_array() {
  # Print JSON array from STATUS_CHECKS_ARRAY bash array
  printf '%s\n' "${STATUS_CHECKS_ARRAY[@]}" | jq -R . | jq -s .
}

# ---------------------------
# Preconditions
# ---------------------------
require_cmd gh
require_cmd jq

if ! gh auth status >/dev/null 2>&1; then
  echo "ERROR: gh is not authenticated. Run: gh auth login" >&2
  exit 1
fi

echo ">> Repo: ${FULL_REPO}"
gh repo view "${FULL_REPO}" >/dev/null

echo ">> Team: ${ORG}/${TEAM_SLUG}"
gh api "orgs/${ORG}/teams/${TEAM_SLUG}" >/dev/null

USERS_JSON="$(split_csv_to_json_array "${EXTRA_USERS}")"
APPS_JSON="$(split_csv_to_json_array "${EXTRA_APPS}")"
CHECKS_JSON="$(json_array_from_bash_array)"

echo ">> Required status checks:"
echo "${CHECKS_JSON}" | jq -r '.[]' | sed 's/^/   - /'

# ---------------------------
# Apply protection
# ---------------------------
echo ">> Applying branch protection to ${FULL_REPO}:${BRANCH}"

# Build the simplified JSON payload for the PUT request
# Note: GitHub API strictness requires proper JSON types (booleans as true/false, not strings)
PAYLOAD=$(jq -n \
  --arg enforce_admins "$ENFORCE_ADMINS" \
  --arg required_approvals "$REQUIRED_APPROVALS" \
  --arg dismiss_stale "$DISMISS_STALE_REVIEWS" \
  --arg code_owner "$REQUIRE_CODEOWNER_REVIEWS" \
  --arg team_slug "$TEAM_SLUG" \
  --argjson checks "$CHECKS_JSON" \
  --argjson extra_users "$USERS_JSON" \
  --argjson extra_apps "$APPS_JSON" \
  '{
    required_status_checks: {
      strict: true,
      contexts: $checks
    },
    enforce_admins: ($enforce_admins == "true"),
    required_pull_request_reviews: {
      dismiss_stale_reviews: ($dismiss_stale == "true"),
      require_code_owner_reviews: ($code_owner == "true"),
      required_approving_review_count: ($required_approvals | tonumber),
      require_last_push_approval: false
    },
    restrictions: {
      users: $extra_users,
      teams: [$team_slug],
      apps: $extra_apps
    },
    required_conversation_resolution: true,
    allow_force_pushes: false,
    allow_deletions: false
  }'
)

echo ">> Config Payload generated"

# Send the request
echo "$PAYLOAD" | gh api -X PUT "repos/${FULL_REPO}/branches/${BRANCH}/protection" \
  -H "Accept: application/vnd.github+json" \
  --input - \
  >/dev/null

echo ">> Done."

echo ">> NOTE: If checks don't exist yet, GitHub will not be able to enforce them until the workflow runs at least once."