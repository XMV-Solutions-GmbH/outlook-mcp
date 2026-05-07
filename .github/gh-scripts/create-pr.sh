#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0
# .github/gh-scripte/create-pr.sh
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  create-pr.sh -t "<pr-title>" -w "<what>" -y "<why>" -h "<how>" -x "<tests>" [-d "<docs>"] [-b <base-branch>] [-r <reviewer>] [--draft]

Required:
  -t  PR title
  -w  What changed (1 paragraph)
  -y  Why (1 paragraph)
  -h  How (bullets; use '\n' or semicolons)
  -x  Tests run (bullets; use '\n' or semicolons)

Optional:
  -d  Docs changes (default: "none")
  -b  Base branch (default: main)
  -r  Reviewer/team (default: XMV-Solutions-GmbH/open-source)
  --draft Create PR as draft

Behavior:
  - Requires clean working tree
  - Enforces: cargo fmt --check, cargo clippy -D warnings, cargo test
  - Creates PR using a temp file (no repo files written)
EOF
}

TITLE=""
WHAT=""
WHY=""
HOW=""
TESTS=""
DOCS="none"
BASE="main"
REVIEWER="XMV-Solutions-GmbH/open-source"
DRAFT="false"

# Parse args (support --draft)
ARGS=()
for a in "$@"; do
  if [[ "${a}" == "--draft" ]]; then
    DRAFT="true"
  else
    ARGS+=("${a}")
  fi
done
set -- "${ARGS[@]}"

while getopts ":t:w:y:h:x:d:b:r:H" opt; do
  case "${opt}" in
    t) TITLE="${OPTARG}" ;;
    w) WHAT="${OPTARG}" ;;
    y) WHY="${OPTARG}" ;;
    h) HOW="${OPTARG}" ;;
    x) TESTS="${OPTARG}" ;;
    d) DOCS="${OPTARG}" ;;
    b) BASE="${OPTARG}" ;;
    r) REVIEWER="${OPTARG}" ;;
    H) usage; exit 0 ;;
    *) usage; exit 1 ;;
  esac
done

if [[ -z "${TITLE}" || -z "${WHAT}" || -z "${WHY}" || -z "${HOW}" || -z "${TESTS}" ]]; then
  echo "ERROR: Missing required arguments." >&2
  usage
  exit 1
fi

require_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: Missing command: $1" >&2; exit 1; }; }
require_cmd git
require_cmd gh
require_cmd cargo

if ! gh auth status >/dev/null 2>&1; then
  echo "ERROR: gh is not authenticated. Run: gh auth login" >&2
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR: Working tree not clean. Commit everything first." >&2
  exit 1
fi

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [[ "${BRANCH}" == "${BASE}" ]]; then
  echo "ERROR: You are on ${BASE}. Switch to a feature branch first." >&2
  exit 1
fi

echo ">> Enforcing checks locally"
cargo fmt --all -- --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test --all-features --all-targets

normalize_lines() {
  echo "$1" | sed 's/;/\n/g' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//'
}

HOW_LINES="$(normalize_lines "${HOW}")"
TEST_LINES="$(normalize_lines "${TESTS}")"

BODY_FILE="$(mktemp)"
cat > "${BODY_FILE}" <<EOF
## What
${WHAT}

## Why
${WHY}

## How
$(echo "${HOW_LINES}" | awk 'NF{print "- " $0}')

## Tests
$(echo "${TEST_LINES}" | awk 'NF{print "- " $0}')

## Docs
${DOCS}
EOF

PR_ARGS=(
  --base "${BASE}"
  --head "${BRANCH}"
  --title "${TITLE}"
  --body-file "${BODY_FILE}"
  --reviewer "${REVIEWER}"
)

if [[ "${DRAFT}" == "true" ]]; then
  PR_ARGS+=(--draft)
fi

echo ">> Creating PR"
gh pr create "${PR_ARGS[@]}"

rm -f "${BODY_FILE}"