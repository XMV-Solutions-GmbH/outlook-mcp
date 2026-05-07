#!/bin/bash
# SPDX-License-Identifier: MIT OR Apache-2.0

# .github/gh-scripts/check-pr.sh
# Checks the CI status of the current branch's PR.

set -e

BRANCH=$(git branch --show-current)
SHA=$(git rev-parse HEAD)

# 1. Find the PR
PR_INFO=$(gh pr list --head "$BRANCH" --json number,url --jq '.[0]')
if [ -z "$PR_INFO" ] || [ "$PR_INFO" == "null" ]; then
  echo "❌ No open PR found for branch '$BRANCH'."
  exit 1
fi

PR_NUM=$(echo "$PR_INFO" | jq -r '.number')
PR_URL=$(echo "$PR_INFO" | jq -r '.url')

echo "🔍 Checking PR #$PR_NUM ($PR_URL) at commit $SHA..."

# 2. Fetch Check Runs
# We grab name, status (queued, in_progress, completed), conclusion (success, failure, etc), and databaseId (for logs)
CHECKS=$(gh api "repos/:owner/:repo/commits/$SHA/check-runs" --jq '.check_runs[] | {name: .name, status: .status, conclusion: .conclusion, id: .id, html_url: .html_url}')

# Check for "in_progress" or "queued"
PENDING_COUNT=$(echo "$CHECKS" | jq -r 'select(.status != "completed") | .name' | wc -l | xargs)
FAILURE_COUNT=$(echo "$CHECKS" | jq -r 'select(.conclusion == "failure" or .conclusion == "timed_out" or .conclusion == "action_required") | .name' | wc -l | xargs)

# 3. Output Status
if [ "$PENDING_COUNT" -gt "0" ]; then
  echo "⏳ Status: PENDING ($PENDING_COUNT checks running)"
  echo "$CHECKS" | jq -r 'select(.status != "completed") | "- \(.name) [\(.status)]"'
  exit 0 # Exit 0 to indicate script ran fine, but status is pending
fi

if [ "$FAILURE_COUNT" -gt "0" ]; then
  echo "❌ Status: FAILURE ($FAILURE_COUNT checks failed)"
  
  # Print failed checks
  FAILED_ITEMS=$(echo "$CHECKS" | jq -c 'select(.conclusion == "failure" or .conclusion == "timed_out")')
  
  echo "$FAILED_ITEMS" | while read -r item; do
    NAME=$(echo "$item" | jq -r '.name')
    ID=$(echo "$item" | jq -r '.id')
    URL=$(echo "$item" | jq -r '.html_url')
    
    echo "---------------------------------------------------"
    echo "🔴 $NAME failed"
    echo "   URL: $URL"
    
    # Try to fetch logs / annotations if possible using gh api
    # Getting full logs via API is complex (download zip), but we can try getting annotations
    echo "   Annotations:"
    gh api "repos/:owner/:repo/check-runs/$ID/annotations" --jq '.[] | "   file: \(.path):\(.start_line)\n   message: \(.message)\n"' || true
  done
  
  exit 1
fi

echo "✅ Status: SUCCESS (All checks passed)"
exit 0
