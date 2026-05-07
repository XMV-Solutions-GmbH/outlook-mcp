#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0
# .github/gh-scripte/new-feature.sh
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  new-feature.sh -k <kind> -t "<title>" -d "<description>" [-b <base-branch>]

Required:
  -k  Kind of change:
      feature | fix | proto | update | chore | docs | refactor | test | release
  -t  Title (short human title)
  -d  Description (what/why in 1-10 sentences)

Optional:
  -b  Base branch (default: main)

Behavior:
  - Requires clean working tree
  - Creates and checks out a new branch based on <kind>
  - Writes NO repo files

Output (stdout):
  BRANCH=<branch-name>
  SLUG=<slug>
  KIND=<kind>
EOF
}

KIND=""
TITLE=""
DESC=""
BASE="main"

while getopts ":k:t:d:b:h" opt; do
  case "${opt}" in
    k) KIND="${OPTARG}" ;;
    t) TITLE="${OPTARG}" ;;
    d) DESC="${OPTARG}" ;;
    b) BASE="${OPTARG}" ;;
    h) usage; exit 0 ;;
    *) usage; exit 1 ;;
  esac
done

if [[ -z "${KIND}" || -z "${TITLE}" || -z "${DESC}" ]]; then
  echo "ERROR: Missing required arguments." >&2
  usage
  exit 1
fi

case "${KIND}" in
  feature|fix|proto|update|chore|docs|refactor|test|release) ;;
  *)
    echo "ERROR: Invalid kind: ${KIND}" >&2
    usage
    exit 1
    ;;
esac

require_cmd() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: Missing command: $1" >&2; exit 1; }; }
require_cmd git

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "ERROR: Not inside a git repository." >&2
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR: Working tree not clean. Commit/stash first." >&2
  exit 1
fi

slugify() {
  echo "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//; s/-+/-/g'
}

prefix_for_kind() {
  case "$1" in
    feature) echo "feature" ;;
    fix) echo "fix" ;;
    proto) echo "proto" ;;
    update) echo "update" ;;
    chore) echo "chore" ;;
    docs) echo "docs" ;;
    refactor) echo "refactor" ;;
    test) echo "test" ;;
    release) echo "release" ;;
  esac
}

SLUG="$(slugify "${TITLE}")"
if [[ -z "${SLUG}" ]]; then
  echo "ERROR: Could not derive slug from title." >&2
  exit 1
fi

PREFIX="$(prefix_for_kind "${KIND}")"
BRANCH="${PREFIX}/${SLUG}"

git fetch origin "${BASE}" >/dev/null 2>&1 || true
git checkout "${BASE}" >/dev/null
git pull --ff-only origin "${BASE}" >/dev/null 2>&1 || true

if git show-ref --verify --quiet "refs/heads/${BRANCH}"; then
  echo "ERROR: Branch already exists locally: ${BRANCH}" >&2
  exit 1
fi
if git ls-remote --exit-code --heads origin "${BRANCH}" >/dev/null 2>&1; then
  echo "ERROR: Branch already exists on origin: ${BRANCH}" >&2
  exit 1
fi

git checkout -b "${BRANCH}" >/dev/null

echo "BRANCH=${BRANCH}"
echo "SLUG=${SLUG}"
echo "KIND=${KIND}"