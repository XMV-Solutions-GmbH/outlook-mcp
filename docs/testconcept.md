<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# Test Concept for AI-Assisted Development

## Overview

This document defines the testing strategy for projects developed with AI assistance. The primary goal is to enable AI agents to **autonomously verify** their implementations through a comprehensive test harness that runs locally on the command line.

---

## Core Principle: Test Harness First

**ALL software developed with AI assistance MUST begin with test automation.**

Without executable tests, the AI cannot validate its own work, leading to accumulated errors and wasted iterations. The test harness is the foundation of autonomous quality assurance.

---

## Test Harness Requirements

Every project MUST have a **local test harness** that:

| Requirement | Description |
| ----------- | ----------- |
| **Command-line execution** | Runs entirely via CLI without manual UI interaction |
| **No external dependencies** | Mocks all external services and APIs |
| **Production-like** | Mirrors production code paths and configurations |
| **Clear output** | Provides unambiguous pass/fail results |
| **Fast execution** | Completes in seconds, not minutes |

---

## Tech-Stack Specific Implementations

### Shell/Bash Projects

```text
tests/
├── unit/                    # Pure function tests
├── integration/             # Docker-based integration tests
├── e2e/                     # Full workflow simulations
├── fixtures/                # Mock servers, test data
│   ├── Dockerfile.mock-*    # Mock service containers
│   └── docker-compose.test.yml
├── test_helper.bash         # Common functions
└── run_tests.sh             # Single entry point
```

**Framework:** [bats-core](https://github.com/bats-core/bats-core)

**Run all tests:**

```bash
./tests/run_tests.sh
```

---

## Template Repository Tests

This template repository includes its own test harness to validate the template structure.

### Test Structure

```text
tests/
└── run_tests.sh             # Single entry point
```

Tests are added as the template grows. Use bats-core for bash-based validation.

### Coverage Reporting

- **Tool:** kcov (for bash script coverage)
- **Service:** Coveralls (badge in README)

---

### Node.js/TypeScript Projects

```text
tests/
├── unit/                    # Vitest/Jest unit tests
├── integration/             # API/service integration
├── e2e/                     # Playwright for UI (if applicable)
├── harness/                 # Test utilities and mocks
└── setup.ts                 # Global test setup
```

**Framework:** Vitest or Jest + Playwright for UI

**Run all tests:**

```bash
npm test                     # Unit + integration
npm run test:e2e             # End-to-end
npm run test:coverage        # With coverage report
```

### Rust Projects

```text
src/
├── lib.rs                   # Unit tests inline (#[cfg(test)])
└── main.rs
tests/
├── integration/             # Integration tests
└── fixtures/                # Test data and mocks
```

**Framework:** Built-in `cargo test`

**Run all tests:**

```bash
cargo test                   # All tests
cargo test --lib             # Unit tests only
cargo test --test '*'        # Integration tests only
```

### Python Projects

```text
tests/
├── unit/                    # pytest unit tests
├── integration/             # pytest integration tests
├── e2e/                     # pytest-playwright for UI
├── conftest.py              # Shared fixtures
└── fixtures/                # Test data and mocks
```

**Framework:** pytest + pytest-playwright for UI

**Run all tests:**

```bash
pytest                       # All tests
pytest tests/unit            # Unit tests only
pytest --cov=src             # With coverage
```

### Go Projects

```text
pkg/
├── module/
│   ├── module.go
│   └── module_test.go       # Unit tests
internal/
└── ...
tests/
├── integration/             # Integration tests
└── e2e/                     # End-to-end tests
```

**Framework:** Built-in `go test`

**Run all tests:**

```bash
go test ./...                # All tests
go test -cover ./...         # With coverage
```

---

## UI Testing with Playwright

For projects with significant UI components:

1. **Prefer headless Playwright tests** over manual UI verification
2. **Use the Playwright MCP server** for AI-assisted UI testing
3. **Record and replay patterns** for complex interactions
4. **Screenshot comparisons** for visual regression

### Playwright Setup

```bash
# Node.js
npm install -D @playwright/test
npx playwright install

# Python
pip install pytest-playwright
playwright install
```

### Example Test Structure

```typescript
// tests/e2e/login.spec.ts
import { test, expect } from '@playwright/test';

test('user can log in successfully', async ({ page }) => {
  await page.goto('/login');
  await page.fill('[data-testid="email"]', 'test@example.com');
  await page.fill('[data-testid="password"]', 'password');
  await page.click('[data-testid="submit"]');
  await expect(page).toHaveURL('/dashboard');
});
```

---

## AI Development Protocol

When implementing features with AI assistance:

```text
1. User describes feature requirement
2. AI creates/updates /docs/todo.md with the task
3. AI writes failing tests in the test harness
4. AI runs tests (expected: FAIL)
5. AI implements minimal code
6. AI runs tests (expected: PASS)
7. AI refactors while keeping tests green
8. AI marks task complete in /docs/todo.md
9. Repeat for next feature
```

**CRITICAL:** After EVERY code change, run the test harness to verify. Do not proceed if tests fail.

---

## Test Coverage Requirements

| Level | Coverage Target | Description |
| ----- | --------------- | ----------- |
| Unit | ≥80% | All functions, classes, and modules |
| Integration | Critical paths | Component interactions and data flow |
| E2E | Happy paths | Critical user journeys |

### Coverage Tools by Language

| Language | Tool | Command |
| -------- | ---- | ------- |
| JavaScript/TypeScript | c8 / istanbul | `npm run test:coverage` |
| Python | coverage.py | `pytest --cov` |
| Rust | cargo-tarpaulin | `cargo tarpaulin` |
| Go | built-in | `go test -cover` |
| Shell | bashcov | `bashcov ./tests/run_tests.sh` |

---

## Mock Strategy

### What to Mock

- External APIs and services
- Database connections (use in-memory or containers)
- File system operations (where appropriate)
- Network requests
- Time-dependent operations

### What NOT to Mock

- Core business logic
- Data transformations
- Internal module interactions (for integration tests)

### Docker-Based Mocking

For complex dependencies, use Docker containers:

```yaml
# docker-compose.test.yml
services:
  mock-api:
    build:
      context: ./tests/fixtures
      dockerfile: Dockerfile.mock-api
    ports:
      - "8080:8080"

  test-db:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: test
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test
```

---

## Continuous Integration

### Minimum CI Requirements

1. **Lint** — Code style and quality checks
2. **Unit tests** — Fast feedback
3. **Integration tests** — Component verification
4. **Coverage report** — Track test coverage

### Example GitHub Actions Workflow

```yaml
# .github/workflows/ci.yml
name: ci

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run tests
        run: ./tests/run_tests.sh
      - name: Upload coverage
        uses: codecov/codecov-action@v4
```

---

## Test Naming Conventions

### Unit Tests

Format: `[function/class]_[scenario]_[expected result]`

Examples:

- `parse_config_valid_input_returns_config_object`
- `calculate_total_empty_cart_returns_zero`
- `validate_email_invalid_format_throws_error`

### Integration Tests

Format: `[components]_[interaction]_[expected result]`

Examples:

- `api_database_create_user_persists_record`
- `auth_session_valid_token_grants_access`

### E2E Tests

Format: `[user journey]_[expected outcome]`

Examples:

- `checkout_flow_completes_order_successfully`
- `password_reset_sends_email_and_allows_reset`

---

## Troubleshooting

### Common Issues

| Issue | Solution |
| ----- | -------- |
| Tests pass locally but fail in CI | Ensure all dependencies are installed in CI; check for environment differences |
| Flaky tests | Remove time dependencies; use deterministic test data; increase timeouts for async operations |
| Slow test suite | Parallelise tests; use faster test databases; mock expensive operations |
| Coverage gaps | Review uncovered code paths; add edge case tests |

---

## References

- [bats-core](https://github.com/bats-core/bats-core) — Bash Automated Testing System
- [Vitest](https://vitest.dev/) — Blazing fast unit test framework
- [pytest](https://pytest.org/) — Python testing framework
- [Playwright](https://playwright.dev/) — End-to-end testing for modern web apps
- [Testing Trophy](https://kentcdodds.com/blog/the-testing-trophy-and-testing-classifications) — Testing philosophy

---

*This test concept is licensed under MIT OR Apache-2.0.*
