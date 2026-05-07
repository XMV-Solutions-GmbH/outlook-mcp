#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0
# .github/gh-scripte/merge-pr.sh
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  merge-pr.sh -p <PR_NUMBER_OR_URL> [-m squash|merge|rebase] [-d] [-a]

Required:
  -p  PR number or URL

Optional:
  -m  Merge method (default: squash)
  -d  Delete branch after merge
  -a  Use admin privileges (bypass requirements)

Behavior:
  - Verifies PR is open & mergeable
  - Verifies all checks are SUCCESS (best-effort via statusCheckRollup)
  - Merges via gh
EOF
}

PR=""
METHOD="squash"
DELETE_BRANCH="false"
ADMIN="false"

while getopts ":p:m:dah" opt; do
  case "${opt}" in
    p) PR="${OPTARG}" ;;
    m) METHOD="${OPTARG}" ;;
    d) DELETE_BRANCH="true" ;;
    a) ADMIN="true" ;;
    h) usage; exit 0 ;;
    *) usage; exit 1 ;;
  esac
done

if [[ -z "${PR}" ]]; then
  echo "ERROR: Missing -p <PR>." >&2
  usage
  exit 1
fi

if [[ ! "${METHOD}" =~ ^(squash|merge|rebase)$ ]]; then
  echo "ERROR: -m must be one of: squash|merge|rebase" >&2
  exit 1
fi

require_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: Missing command: $1" >&2; exit 1; }; }
require_cmd gh

if ! gh auth status >/dev/null 2>&1; then
  echo "ERROR: gh is not authenticated. Run: gh auth login" >&2
  exit 1
fi

STATE="$(gh pr view "${PR}" --json state --jq .state)"
if [[ "${STATE}" != "OPEN" ]]; then
  echo "ERROR: PR is not open (state=${STATE})." >&2
  exit 1
fi

MERGEABLE="$(gh pr view "${PR}" --json mergeable --jq .mergeable)"
if [[ "${MERGEABLE}" == "CONFLICTING" ]]; then
  echo "ERROR: PR has conflicts. Resolve first." >&2
  exit 1
fi

if [[ "${ADMIN}" != "true" ]]; then
  FAILED_CHECKS="$(gh pr view "${PR}" --json statusCheckRollup --jq '[.statusCheckRollup[] | select(.conclusion != "SUCCESS") | .name]')"
  if [[ "${FAILED_CHECKS}" != "[]" ]]; then
    echo "ERROR: Not all checks are successful: ${FAILED_CHECKS}" >&2
    exit 1
  fi
fi

DELETE_ARG=()
if [[ "${DELETE_BRANCH}" == "true" ]]; then
  DELETE_ARG+=(--delete-branch)
fi

if [[ "${ADMIN}" == "true" ]]; then
  DELETE_ARG+=(--admin)
fi

echo ">> Merging PR (${METHOD})"
gh pr merge "${PR}" "--${METHOD}" "${DELETE_ARG[@]}"