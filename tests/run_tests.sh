#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
#
# Test runner for mcp-server-outlook. Dispatches to the three test layers
# defined in ENGINEERING_PRINCIPLES.md § 5.
#
# Usage:
#   ./tests/run_tests.sh             # default: unit + integration
#   ./tests/run_tests.sh unit        # only unit
#   ./tests/run_tests.sh integration # only integration (boundary mocks)
#   ./tests/run_tests.sh harness     # only harness (real Microsoft Graph)
#   ./tests/run_tests.sh all         # unit + integration + harness
#
# Harness tests require harness credentials installed locally (or in
# CI as the OUTLOOK_HARNESS_TOKEN_JSON secret) — see
# docs/testconcept.md.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

target="${1:-default}"

# Coverage opt-in via OUTLOOK_COVERAGE env. Default ("auto"): on for
# unit + integration (where coverage is meaningful), off for harness
# (network-bound and not the right thing to measure for line
# coverage). OUTLOOK_COVERAGE=1 forces it on regardless;
# OUTLOOK_COVERAGE=0 forces it off.
rm -f .coverage coverage.xml 2>/dev/null || true

run_layer() {
    local layer="$1"
    local path="${SCRIPT_DIR}/${layer}"
    if [[ ! -d "${path}" ]]; then
        echo "ERROR: layer directory not found: ${path}" >&2
        return 1
    fi
    local cov_args=()
    case "${OUTLOOK_COVERAGE:-auto}" in
        1|true|yes|on) cov_args=(--cov --cov-report=term --cov-report=xml --cov-append) ;;
        0|false|no|off) cov_args=() ;;
        *)
            if [[ "${layer}" == "unit" || "${layer}" == "integration" ]]; then
                cov_args=(--cov --cov-report=term --cov-report=xml --cov-append)
            fi
            ;;
    esac
    echo ">>> uv run pytest tests/${layer}"
    local rc=0
    uv run pytest -m "${layer}" "${cov_args[@]}" "${path}" || rc=$?
    # pytest exit code 5 = "no tests collected"; treat as success for
    # layers that haven't been populated yet (early-development reality).
    case "${rc}" in
        0) return 0 ;;
        5) echo "    (no ${layer} tests collected — empty layer, treating as ok)"; return 0 ;;
        *) return "${rc}" ;;
    esac
}

case "${target}" in
    unit)
        run_layer unit
        ;;
    integration)
        run_layer integration
        ;;
    harness)
        run_layer harness
        ;;
    all)
        run_layer unit
        run_layer integration
        run_layer harness
        ;;
    default)
        run_layer unit
        run_layer integration
        ;;
    *)
        echo "Unknown target: ${target}" >&2
        echo "Usage: $0 [unit|integration|harness|all|default]" >&2
        exit 2
        ;;
esac
