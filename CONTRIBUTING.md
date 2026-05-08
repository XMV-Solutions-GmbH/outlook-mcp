<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# Contributing to mcp-server-outlook

Thank you for your interest in contributing! This document provides guidelines for contributions to `mcp-server-outlook`.

---

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

---

## Getting Started

### Prerequisites

- Git
- GitHub CLI (`gh`) — [installation guide](https://cli.github.com/)
- Any additional tools required by your specific implementation

### Setup

```bash
git clone https://github.com/XMV-Solutions-GmbH/outlook-mcp.git
cd outlook-mcp
uv sync --extra dev

# Run the test harness
./tests/run_tests.sh
```

See [`README.md` § Development](README.md#development) for more.

---

## Development Guidelines

### Code Style

- Run formatters before committing
- Run linters before committing
- Follow language-specific best practices
- Use British English in all code, comments, and documentation

### SPDX Headers

Every source file MUST start with an SPDX licence identifier:

```text
// SPDX-License-Identifier: MIT OR Apache-2.0   (for C-style comments)
#  SPDX-License-Identifier: MIT OR Apache-2.0   (for shell/Python)
<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->  (for HTML/Markdown)
```

### Documentation

- All public items must have documentation comments
- Include examples where helpful
- Examples must compile/run
- Keep documentation up to date with code changes

### Testing

- **Unit tests are mandatory** for all new functionality
- **Integration tests are required** for new features
- Run the full test suite before submitting a PR
- See [docs/testconcept.md](docs/testconcept.md) for testing strategy

---

## Pull Request Process

### 1. Fork the Repository

```bash
gh repo fork XMV-Solutions-GmbH/outlook-mcp
```

### 2. Create a Feature Branch

```bash
git checkout -b feature/amazing-feature
# Or for bug fixes:
git checkout -b fix/bug-description
```

### 3. Make Your Changes

- Write tests first (TDD approach)
- Make clear, atomic commits
- Follow the commit message conventions below

### 4. Run All Checks

```bash
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src/outlook_mcp tests
./tests/run_tests.sh
```

### 5. Open a Pull Request

```bash
gh pr create --title "feat: add amazing feature" --body "Description of changes"
```

### 6. Wait for CI to Pass

All CI checks must pass before merging.

### 7. Address Review Feedback

Respond to review comments and make requested changes.

---

## Commit Message Convention

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```text
<type>(<scope>): <description>

[optional body]

[optional footer]
```

### Types

| Type | Description |
| ---- | ----------- |
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `style` | Formatting, no code change |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `test` | Adding or updating tests |
| `chore` | Build process or auxiliary tool changes |
| `ci` | CI configuration changes |
| `perf` | Performance improvement |
| `build` | Build system changes |

### Examples

```text
feat: add user authentication
fix: resolve race condition in data sync
docs: update installation instructions
test: add unit tests for validation module
chore: update dependencies
```

---

## Branch Naming Convention

| Type | Pattern | Example |
| ---- | ------- | ------- |
| Feature | `feature/<description>` | `feature/user-auth` |
| Bug fix | `fix/<description>` | `fix/login-redirect` |
| Hotfix | `hotfix/<description>` | `hotfix/security-patch` |
| Documentation | `docs/<description>` | `docs/api-reference` |
| Release | `release/<version>` | `release/v1.2.0` |

---

## Types of Contributions

We welcome various types of contributions:

- 🐛 **Bug reports** — Help us identify issues
- ✨ **Feature requests** — Suggest new functionality
- 📝 **Documentation** — Improve guides and references
- 🧪 **Test coverage** — Add missing tests
- 🔧 **Code improvements** — Refactoring and optimisation
- 🌐 **Translations** — Help localise the project

---

## Reporting Issues

### Bug Reports

When reporting bugs, please include:

1. A clear, descriptive title
2. Steps to reproduce the issue
3. Expected behaviour
4. Actual behaviour
5. Your environment (OS, versions, etc.)
6. Any relevant logs or screenshots

### Feature Requests

For feature requests, please include:

1. A clear description of the feature
2. The problem it solves
3. Possible implementation approaches
4. Any alternatives you've considered

---

## Questions?

- Open an issue for general questions
- Start a discussion for broader topics
- Contact us at <oss@xmv.de>

---

## Recognition

Contributors will be recognised in our release notes and README. Thank you for helping make this project better!

---

*This contributing guide is licensed under MIT OR Apache-2.0.*
