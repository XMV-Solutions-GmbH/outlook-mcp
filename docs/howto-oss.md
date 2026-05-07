<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# How-To: Set Up a Professional Open-Source Project

This guide describes all necessary steps to set up a professional open-source project from scratch. It is based on best practices and can be used as a template for all OSS projects.

Our contact information:

- **Email**: <oss@xmv.de>
- **Website**: <https://xmv.de/en/oss/>
- **Name**: XMV Solutions GmbH

---

## Table of Contents

1. [Repository Structure](#1-repository-structure)
2. [Required Documents](#2-required-documents)
3. [Licensing (Dual License)](#3-licensing-dual-license)
4. [SPDX Headers in Source Files](#4-spdx-headers-in-source-files)
5. [README.md with Badges](#5-readmemd-with-badges)
6. [GitHub Configuration](#6-github-configuration)
7. [CI/CD Workflows](#7-cicd-workflows)
8. [Repository Settings (Scripts)](#8-repository-settings-scripts)
9. [Checklist](#9-checklist)

---

## 1. Repository Structure

A professional OSS project should have the following structure:

```text
project-name/
├── .github/
│   ├── CODEOWNERS                    # Code review assignment
│   ├── copilot-instructions.md       # AI coding guidelines (optional)
│   ├── dependabot.yml                # Automatic dependency updates
│   ├── gh-scripts/                   # Repository setup scripts
│   │   ├── assign-repo-to-team.sh
│   │   └── setup-branch-protection.sh
│   └── workflows/                    # CI/CD pipelines
│       ├── ci.yml
│       └── release.yml
├── docs/                             # Documentation
├── src/                              # Source code
├── tests/                            # Tests
├── examples/                         # Examples (optional)
├── CHANGELOG.md                      # Change log
├── CODE_OF_CONDUCT.md                # Code of conduct
├── CONTRIBUTING.md                   # Contribution guidelines
├── LICENSE                           # Main license (MIT)
├── LICENSE-APACHE                    # Apache 2.0 License
├── LICENSE-MIT                       # MIT License
├── README.md                         # Project description
└── SECURITY.md                       # Security policy
```

---

## 2. Required Documents

### 2.1 CODE_OF_CONDUCT.md

Use the [Contributor Covenant](https://www.contributor-covenant.org/), the de-facto standard for OSS projects:

```markdown
<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# Code of Conduct

## Our Pledge

We as members, contributors, and leaders pledge to make participation in our
community a harassment-free experience for everyone, regardless of age, body
size, visible or invisible disability, ethnicity, sex characteristics, gender
identity and expression, level of experience, education, socio-economic status,
nationality, personal appearance, race, religion, or sexual identity and orientation.

We pledge to act and interact in ways that contribute to an open, welcoming,
diverse, inclusive, and healthy community.

## Our Standards

Examples of behavior that contributes to a positive environment:

* Using welcoming and inclusive language
* Being respectful of differing viewpoints and experiences
* Gracefully accepting constructive criticism
* Focusing on what is best for the community
* Showing empathy towards other community members

Examples of unacceptable behavior:

* The use of sexualized language or imagery, and sexual attention or advances of any kind
* Trolling, insulting or derogatory comments, and personal or political attacks
* Public or private harassment
* Publishing others' private information without explicit permission
* Other conduct which could reasonably be considered inappropriate in a professional setting

## Enforcement

Instances of abusive, harassing, or otherwise unacceptable behavior may be
reported to the maintainers at **security@example.com**.

All complaints will be reviewed and investigated promptly and fairly.

## Attribution

This Code of Conduct is adapted from the [Contributor Covenant](https://www.contributor-covenant.org),
version 2.1.
```

### 2.2 CONTRIBUTING.md

``````markdown
<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# Contributing to PROJECT_NAME

Thank you for your interest in contributing!

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## Getting Started

### Prerequisites

- [List your prerequisites here]
- Docker (for integration tests)

### Setup

```bash
git clone https://github.com/ORG/REPO.git
cd REPO
# Build/install commands
```

## Development Guidelines

### Code Style

- Run formatters before committing
- Run linters before committing
- Follow language-specific best practices

### SPDX Headers

Every source file must start with:

```text
// SPDX-License-Identifier: MIT OR Apache-2.0
```

### Documentation

- All public items must have doc comments
- Include examples where helpful
- Examples must compile/run

### Testing

- Unit tests are mandatory for all new functionality
- Integration tests are required for new features

## Pull Request Process

1. **Fork** the repository
2. **Create a feature branch** from `main`
3. **Make your changes** with clear, atomic commits
4. **Run all checks** (format, lint, test)
5. **Open a Pull Request** with a clear description
6. **Wait for CI** to pass
7. **Address review feedback**

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```text
feat: add new feature
fix: resolve bug in X
docs: update README
chore: update dependencies
```

## Types of Contributions

- 🐛 Bug reports
- ✨ Feature requests
- 📝 Documentation improvements
- 🧪 Test coverage
- 🔧 Code improvements

## Questions?

Open an issue or start a discussion!
``````

### 2.3 SECURITY.md

```markdown
<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.x.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability, please do **not** open a public issue.

### How to Report

1. **Email**: Send details to **security@example.com**
2. **Subject**: `[SECURITY] project-name: <brief description>`
3. **Include**:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

### What to Expect

- **Acknowledgment**: Within 48 hours
- **Initial assessment**: Within 7 days
- **Resolution timeline**: Depends on severity, typically 30-90 days

### Disclosure Policy

- We follow [responsible disclosure](https://en.wikipedia.org/wiki/Responsible_disclosure)
- We will coordinate with you on disclosure timing
- Credit will be given in the security advisory (unless you prefer anonymity)

## Dependencies

We regularly update dependencies via Dependabot. Security updates are prioritized.
```

### 2.4 CHANGELOG.md

Use the [Keep a Changelog](https://keepachangelog.com/) format:

```markdown
<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- New feature X

### Changed

- Updated dependency Y

### Fixed

- Bug in Z

## [1.0.0] - 2026-01-28

### Added

- Initial release
- Feature A
- Feature B

[Unreleased]: https://github.com/ORG/REPO/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/ORG/REPO/releases/tag/v1.0.0
```

### 2.5 .github/CODEOWNERS

Defines automatic code review assignment:

```text
# SPDX-License-Identifier: MIT OR Apache-2.0
# Default owners for everything
* @ORG/team-name

# Specific paths can have different owners
# /docs/ @ORG/docs-team
# /src/security/ @ORG/security-team
```

---

## 3. Licensing (Dual License)

### Why Dual License (MIT OR Apache-2.0)?

- **MIT**: Maximum flexibility, widely used, simple
- **Apache 2.0**: Explicit patent protection, better for enterprises
- **Dual License**: Users can choose which one suits them best

### 3.1 LICENSE (Main License - MIT)

```text
MIT License

Copyright [YEAR] [COPYRIGHT HOLDER]

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

### 3.2 LICENSE-MIT

Identical to LICENSE.

### 3.3 LICENSE-APACHE

Full Apache 2.0 license text from: <https://www.apache.org/licenses/LICENSE-2.0.txt>

With copyright notice at the end:

```text
Copyright [YEAR] [COPYRIGHT HOLDER]

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0
```

---

## 4. SPDX Headers in Source Files

### What is SPDX?

[SPDX](https://spdx.dev/) (Software Package Data Exchange) is a standard for uniquely identifying licenses in source code.

### Required for All Files

**EVERY** source code file must start with an SPDX header:

#### Rust / C / C++ / Java / JavaScript / TypeScript / Go

```rust
// SPDX-License-Identifier: MIT OR Apache-2.0
```

#### Python

```python
# SPDX-License-Identifier: MIT OR Apache-2.0
```

#### Shell / Bash

```bash
#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0
```

#### HTML / Markdown

```markdown
<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
```

#### YAML / TOML

```yaml
# SPDX-License-Identifier: MIT OR Apache-2.0
```

#### CSS

```css
/* SPDX-License-Identifier: MIT OR Apache-2.0 */
```

### Generated Files

In addition to the SPDX header:

```rust
// SPDX-License-Identifier: MIT OR Apache-2.0
// DO NOT EDIT - This file is generated by build.rs
```

---

## 5. README.md with Badges

### Badge Collection (at the beginning of README)

```markdown
<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# project-name

![Crates.io](https://img.shields.io/crates/v/CRATE_NAME)
![Downloads](https://img.shields.io/crates/d/CRATE_NAME)
![docs.rs](https://img.shields.io/docsrs/CRATE_NAME)
![License](https://img.shields.io/crates/l/CRATE_NAME)
[![CI](https://github.com/ORG/REPO/actions/workflows/ci.yml/badge.svg)](https://github.com/ORG/REPO/actions/workflows/ci.yml)
[![MSRV](https://img.shields.io/badge/MSRV-1.82-blue.svg)](https://www.rust-lang.org)
```

### Available Badge Types

| Badge | URL Pattern | Description |
| ----- | ----------- | ----------- |
| **Crates.io Version** | `https://img.shields.io/crates/v/CRATE` | Current crates.io version |
| **Downloads** | `https://img.shields.io/crates/d/CRATE` | Total downloads |
| **docs.rs** | `https://img.shields.io/docsrs/CRATE` | Documentation status |
| **License** | `https://img.shields.io/crates/l/CRATE` | License from crates.io |
| **CI Status** | `https://github.com/ORG/REPO/actions/workflows/ci.yml/badge.svg` | GitHub Actions CI |
| **MSRV** | `https://img.shields.io/badge/MSRV-VERSION-blue.svg` | Minimum Supported Rust Version |
| **npm Version** | `https://img.shields.io/npm/v/PACKAGE` | npm package version |
| **npm Downloads** | `https://img.shields.io/npm/dm/PACKAGE` | npm monthly downloads |
| **PyPI Version** | `https://img.shields.io/pypi/v/PACKAGE` | PyPI package version |
| **Coverage** | `https://codecov.io/gh/ORG/REPO/branch/main/graph/badge.svg` | Code coverage |

### README Structure

``````markdown
<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# project-name

[BADGES]

Short description of what the project does.

---

## Features

- Feature 1
- Feature 2

## Non-Goals

- ❌ What this project does NOT do

---

## Installation

```bash
# Installation command
```

## Quick Start

```text
// Minimal example
```

---

## Documentation

- [API Docs](https://docs.rs/CRATE)
- [Examples](./examples)
- [Architecture](./docs/architecture.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md)

## License

Licensed under either of:

- Apache License, Version 2.0 ([LICENSE-APACHE](LICENSE-APACHE) or <http://www.apache.org/licenses/LICENSE-2.0>)
- MIT license ([LICENSE-MIT](LICENSE-MIT) or <http://opensource.org/licenses/MIT>)

at your option.

## Disclaimer

This project is NOT affiliated with [UPSTREAM PROJECT].
Provided AS-IS without warranty.
``````

---

## 6. GitHub Configuration

### 6.1 .github/dependabot.yml

Automatic dependency updates:

```yaml
# SPDX-License-Identifier: MIT OR Apache-2.0
version: 2
updates:
  # Rust/Cargo dependencies
  - package-ecosystem: "cargo"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 5
    commit-message:
      prefix: "deps"
    labels:
      - "dependencies"
      - "rust"
    groups:
      rust-minor:
        patterns:
          - "*"
        update-types:
          - "minor"
          - "patch"

  # npm dependencies (if applicable)
  - package-ecosystem: "npm"
    directory: "/"
    schedule:
      interval: "weekly"
    commit-message:
      prefix: "deps"
    labels:
      - "dependencies"
      - "javascript"

  # GitHub Actions
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 3
    commit-message:
      prefix: "ci"
    labels:
      - "dependencies"
      - "ci"
    groups:
      actions:
        patterns:
          - "*"
```

---

## 7. CI/CD Workflows

### 7.1 .github/workflows/ci.yml

```yaml
# SPDX-License-Identifier: MIT OR Apache-2.0
name: ci

on:
  push:
    branches: [ "main" ]
  pull_request:

env:
  CARGO_TERM_COLOR: always

jobs:
  fmt:
    name: fmt
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
        with:
          components: rustfmt
      - uses: Swatinem/rust-cache@v2
      - run: cargo fmt --all -- --check

  clippy:
    name: clippy
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
        with:
          components: clippy
      - uses: Swatinem/rust-cache@v2
      - run: cargo clippy --all-targets --all-features -- -D warnings

  test:
    name: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
      - uses: Swatinem/rust-cache@v2
      - run: cargo test --all-features --all-targets
```

### 7.2 .github/workflows/release.yml

```yaml
# SPDX-License-Identifier: MIT OR Apache-2.0
name: release

on:
  push:
    tags:
      - 'v[0-9]+.[0-9]+.[0-9]+'

jobs:
  validate:
    name: Validate Release
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
      - uses: Swatinem/rust-cache@v2
      - run: cargo fmt --check
      - run: cargo clippy --all-targets --all-features -- -D warnings
      - run: cargo test --lib
      - name: Verify version matches tag
        run: |
          TAG_VERSION="${GITHUB_REF#refs/tags/v}"
          CARGO_VERSION=$(cargo metadata --no-deps --format-version 1 | jq -r '.packages[0].version')
          if [ "$TAG_VERSION" != "$CARGO_VERSION" ]; then
            echo "Tag version ($TAG_VERSION) does not match Cargo.toml version ($CARGO_VERSION)"
            exit 1
          fi

  publish:
    name: Publish
    needs: validate
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
      - uses: Swatinem/rust-cache@v2
      - run: cargo publish --token ${{ secrets.CRATES_IO_TOKEN }}

  github-release:
    name: Create GitHub Release
    needs: validate
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Extract changelog
        id: changelog
        run: |
          VERSION="${GITHUB_REF#refs/tags/v}"
          CHANGELOG=$(awk "/## \[${VERSION}\]/{flag=1; next} /## \[/{flag=0} flag" CHANGELOG.md)
          echo "changelog<<EOF" >> $GITHUB_OUTPUT
          echo "$CHANGELOG" >> $GITHUB_OUTPUT
          echo "EOF" >> $GITHUB_OUTPUT
      - uses: softprops/action-gh-release@v2
        with:
          name: Release ${{ github.ref_name }}
          body: |
            ## Changes in ${{ github.ref_name }}

            ${{ steps.changelog.outputs.changelog }}
          draft: false
          prerelease: ${{ contains(github.ref_name, '-') }}
```

---

## 8. Repository Settings (Scripts)

### 8.1 assign-repo-to-team.sh

Assigns the repository to a team:

```bash
#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0
set -euo pipefail

ORG="${ORG:-YOUR_ORG}"
REPO="${REPO:-YOUR_REPO}"
TEAM_SLUG="${TEAM_SLUG:-open-source}"

echo ">> Granting write access to team ${TEAM_SLUG} on repo ${REPO}"

gh api -X PUT "orgs/${ORG}/teams/${TEAM_SLUG}/repos/${ORG}/${REPO}" \
  -H "Accept: application/vnd.github+json" \
  -f permission="push"
```

### 8.2 setup-branch-protection.sh

Configures branch protection rules:

```bash
#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0
set -euo pipefail

# ---------------------------
# Configuration (overridable via environment variables)
# ---------------------------
ORG="${ORG:-YOUR_ORG}"
REPO="${REPO:-YOUR_REPO}"
BRANCH="${BRANCH:-main}"
TEAM_SLUG="${TEAM_SLUG:-open-source}"

# PR review rules
REQUIRED_APPROVALS="${REQUIRED_APPROVALS:-0}"
REQUIRE_CODEOWNER_REVIEWS="${REQUIRE_CODEOWNER_REVIEWS:-false}"
DISMISS_STALE_REVIEWS="${DISMISS_STALE_REVIEWS:-true}"

# Admin enforcement
ENFORCE_ADMINS="${ENFORCE_ADMINS:-true}"

# Required status checks (must match job names exactly)
STATUS_CHECKS=("fmt" "clippy" "test")

FULL_REPO="${ORG}/${REPO}"

# ---------------------------
# Helper functions
# ---------------------------
require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: Missing required command: $1" >&2
    exit 1
  }
}

json_array_from_bash_array() {
  printf '%s\n' "${STATUS_CHECKS[@]}" | jq -R . | jq -s .
}

# ---------------------------
# Check prerequisites
# ---------------------------
require_cmd gh
require_cmd jq

if ! gh auth status >/dev/null 2>&1; then
  echo "ERROR: gh is not authenticated. Run: gh auth login" >&2
  exit 1
fi

echo ">> Repo: ${FULL_REPO}"
gh repo view "${FULL_REPO}" >/dev/null

CHECKS_JSON="$(json_array_from_bash_array)"

echo ">> Required status checks:"
echo "${CHECKS_JSON}" | jq -r '.[]' | sed 's/^/   - /'

# ---------------------------
# Apply branch protection
# ---------------------------
echo ">> Applying branch protection to ${FULL_REPO}:${BRANCH}"

PAYLOAD=$(jq -n \
  --arg enforce_admins "$ENFORCE_ADMINS" \
  --arg required_approvals "$REQUIRED_APPROVALS" \
  --arg dismiss_stale "$DISMISS_STALE_REVIEWS" \
  --arg code_owner "$REQUIRE_CODEOWNER_REVIEWS" \
  --arg team_slug "$TEAM_SLUG" \
  --argjson checks "$CHECKS_JSON" \
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
      users: [],
      teams: [$team_slug],
      apps: []
    },
    required_conversation_resolution: true,
    allow_force_pushes: false,
    allow_deletions: false
  }'
)

echo "$PAYLOAD" | gh api -X PUT "repos/${FULL_REPO}/branches/${BRANCH}/protection" \
  -H "Accept: application/vnd.github+json" \
  --input - \
  >/dev/null

echo ">> Done."
echo ">> NOTE: Status checks will only be enforceable after the workflow runs at least once."
```

### Using the Scripts

```bash
# Run once after repository creation:

# 1. Assign team
ORG=my-org REPO=my-repo ./assign-repo-to-team.sh

# 2. Enable branch protection
ORG=my-org REPO=my-repo ./setup-branch-protection.sh
```

---

## 9. Checklist

### Create Repository

- [ ] Create repository on GitHub
- [ ] Create README.md with badges
- [ ] Create LICENSE (MIT)
- [ ] Create LICENSE-MIT
- [ ] Create LICENSE-APACHE

### Project Documentation

- [ ] Create CODE_OF_CONDUCT.md
- [ ] Create CONTRIBUTING.md
- [ ] Create SECURITY.md
- [ ] Create CHANGELOG.md
- [ ] Create docs/ directory with architecture documentation

### GitHub Configuration

- [ ] Create .github/CODEOWNERS
- [ ] Create .github/dependabot.yml
- [ ] Create .github/workflows/ci.yml
- [ ] Create .github/workflows/release.yml

### Repository Settings

- [ ] Run `assign-repo-to-team.sh`
- [ ] Run `setup-branch-protection.sh`
- [ ] Configure secrets (e.g., CRATES_IO_TOKEN)

### Code Standards

- [ ] SPDX headers in all source files
- [ ] Formatter configured
- [ ] Linter configured
- [ ] Tests present

### Optional

- [ ] .github/copilot-instructions.md for AI coding guidelines
- [ ] Issue templates
- [ ] Pull request templates
- [ ] Enable GitHub Discussions

---

## Further Resources

- [SPDX License List](https://spdx.org/licenses/)
- [Contributor Covenant](https://www.contributor-covenant.org/)
- [Keep a Changelog](https://keepachangelog.com/)
- [Conventional Commits](https://www.conventionalcommits.org/)
- [Semantic Versioning](https://semver.org/)
- [GitHub Branch Protection Rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/defining-the-mergeability-of-pull-requests/about-protected-branches)
- [Shields.io Badges](https://shields.io/)

---

*This guide is licensed under MIT OR Apache-2.0.*
