#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0
# =============================================================================
# Test Runner for Template Tests
# =============================================================================
#
# Usage:
#   ./tests/run_tests.sh              # Run all tests
#   ./tests/run_tests.sh template     # Run only template tests
#   ./tests/run_tests.sh --coverage   # Run with coverage (requires kcov)
#
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colours
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info() { echo -e "${BLUE}ℹ${NC} $1"; }
success() { echo -e "${GREEN}✓${NC} $1"; }
error() { echo -e "${RED}✗${NC} $1" >&2; }

# Check for bats
check_bats() {
    if ! command -v bats &> /dev/null; then
        error "bats-core is not installed."
        info "Install with: sudo apt install bats (Debian/Ubuntu)"
        info "         or: brew install bats-core (macOS)"
        exit 1
    fi
}

# Run tests with optional coverage
run_tests() {
    local test_dir="$1"
    local with_coverage="${2:-false}"
    
    if [[ ! -d "$test_dir" ]]; then
        error "Test directory not found: $test_dir"
        return 1
    fi
    
    local test_files
    test_files=$(find "$test_dir" -name "*.bats" -type f 2>/dev/null)
    
    if [[ -z "$test_files" ]]; then
        info "No test files found in $test_dir"
        return 0
    fi
    
    if [[ "$with_coverage" == "true" ]]; then
        if command -v kcov &> /dev/null; then
            info "Running tests with coverage..."
            local coverage_dir="$REPO_ROOT/coverage"
            mkdir -p "$coverage_dir"
            
            # Run each test file through kcov
            for test_file in $test_files; do
                kcov --include-path="$REPO_ROOT/.github/gh-scripts" \
                     "$coverage_dir" \
                     bats "$test_file"
            done
            
            success "Coverage report generated in $coverage_dir"
        else
            error "kcov not installed, running without coverage"
            bats "$test_dir"
        fi
    else
        bats "$test_dir"
    fi
}

# Main
main() {
    local target="${1:-all}"
    local with_coverage=false
    
    # Parse arguments
    for arg in "$@"; do
        case "$arg" in
            --coverage)
                with_coverage=true
                ;;
            template)
                target="template"
                ;;
            all)
                target="all"
                ;;
        esac
    done
    
    check_bats
    
    echo ""
    echo -e "${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║                    Running Tests                               ║${NC}"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    
    case "$target" in
        template)
            info "Running template tests..."
            run_tests "$SCRIPT_DIR/template" "$with_coverage"
            ;;
        all)
            info "Running all tests..."
            # Run template tests
            if [[ -d "$SCRIPT_DIR/template" ]]; then
                run_tests "$SCRIPT_DIR/template" "$with_coverage"
            fi
            # Add other test directories here as they are added
            ;;
        *)
            error "Unknown target: $target"
            exit 1
            ;;
    esac
    
    echo ""
    success "All tests completed!"
}

main "$@"
