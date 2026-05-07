<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
<!-- test: verify branch protection -->
# OSS Project Template

[![Licence](https://img.shields.io/badge/licence-MIT%20OR%20Apache--2.0-blue.svg)](LICENSE)
[![CI](https://github.com/XMV-Solutions-GmbH/oss-project-template/actions/workflows/ci.yml/badge.svg)](https://github.com/XMV-Solutions-GmbH/oss-project-template/actions/workflows/ci.yml)
[![Coverage Status](https://coveralls.io/repos/github/XMV-Solutions-GmbH/oss-project-template/badge.svg?branch=main)](https://coveralls.io/github/XMV-Solutions-GmbH/oss-project-template?branch=main)
[![contributions welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg?style=flat)](https://github.com/XMV-Solutions-GmbH/oss-project-template/issues)

🚀 **Production-ready template for AI-assisted open source development.**

This template provides everything you need to start a professional open source project with optimised support for AI-assisted development using GitHub Copilot or similar tools.

---

## ✨ Features

- **AI-First Development** — Copilot instructions optimised for autonomous quality assurance
- **Test Harness Patterns** — Tech-stack agnostic testing strategies for AI verification
- **GitHub Automation** — Branch protection, team assignment, and CI/CD workflows
- **Configurable Setup** — Single `repo.ini` file for project-specific customisation
- **Dual Licence** — MIT OR Apache-2.0 for maximum compatibility

---

## 🚀 Quick Start

### 1. Create Your Repository

Use this template to create a new repository:

```bash
# Via GitHub CLI
gh repo create YOUR-ORG/YOUR-REPO --template XMV-Solutions-GmbH/oss-project-template --public

# Or click "Use this template" on GitHub
```

### 2. Configure Your Project

Edit `repo.ini` with your project details:

```ini
ORG="YOUR-ORG"
REPO="YOUR-REPO"
PROJECT_NAME="Your Project Name"
PROJECT_DESCRIPTION="Your project description"
```

### 3. Run Setup Scripts

```bash
# Assign repository to team
./.github/gh-scripts/assign-repo-to-team.sh

# Set up branch protection
./.github/gh-scripts/setup-branch-protection.sh
```

### 4. Create Project Documentation

Before writing any code, create:

- `docs/app-concept.md` — Project vision and architecture
- `docs/todo.md` — Prioritised task list

See templates in [docs/](docs/) directory.

---

## 📁 Repository Structure

```text
.
├── .github/
│   ├── copilot-instructions.md    # AI coding guidelines
│   ├── CODEOWNERS                 # Code review assignment
│   ├── gh-scripts/                # Repository setup scripts
│   │   ├── assign-repo-to-team.sh
│   │   ├── setup-branch-protection.sh
│   │   └── ...
│   └── workflows/                 # CI/CD pipelines
├── docs/
│   ├── app-concept.md             # Project concept template
│   ├── howto-oss.md               # OSS setup guide
│   ├── testconcept.md             # Testing strategy
│   └── todo.md                    # Task tracking
├── tests/
│   └── run_tests.sh               # Test runner
├── CHANGELOG.md                   # Version history
├── CODE_OF_CONDUCT.md             # Community standards
├── CONTRIBUTING.md                # Contribution guidelines
├── LICENSE                        # MIT licence
├── LICENSE-APACHE                 # Apache 2.0 licence
├── LICENSE-MIT                    # MIT licence
├── README.md                      # This file
├── repo.ini                       # Project configuration
└── SECURITY.md                    # Security policy
```

---

## 🧪 AI-Assisted Development

This template is designed for **AI-first development**. The key principle:

> **Test harness before implementation.**

Every project must have a local test harness that:

1. Runs entirely on the command line
2. Executes without external dependencies (mocks where necessary)
3. Mirrors production as closely as possible
4. Provides clear pass/fail output

This enables AI agents to autonomously verify their implementations.

See [docs/testconcept.md](docs/testconcept.md) for detailed testing strategies.

---

## 📚 Documentation

| Document | Description |
| -------- | ----------- |
| [How-To: OSS Setup](docs/howto-oss.md) | Complete guide to setting up OSS projects |
| [Test Concept](docs/testconcept.md) | Testing strategies for AI-assisted development |
| [Contributing](CONTRIBUTING.md) | How to contribute to this project |
| [Security Policy](SECURITY.md) | How to report vulnerabilities |

---

## 🤝 Contributing

Contributions are welcome! Please read our [Contributing Guidelines](CONTRIBUTING.md) and [Code of Conduct](CODE_OF_CONDUCT.md) first.

### Quick Contribution Guide

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Make your changes with tests
4. Commit: `git commit -m 'feat: add amazing feature'`
5. Push: `git push origin feature/amazing-feature`
6. Open a Pull Request

---

## 📄 Licence

Licensed under either of:

- Apache License, Version 2.0 ([LICENSE-APACHE](LICENSE-APACHE) or <http://www.apache.org/licenses/LICENSE-2.0>)
- MIT license ([LICENSE-MIT](LICENSE-MIT) or <http://opensource.org/licenses/MIT>)

at your option.

### Contribution

Unless you explicitly state otherwise, any contribution intentionally submitted for inclusion in this project by you, as defined in the Apache-2.0 license, shall be dual licensed as above, without any additional terms or conditions.

---

## 📬 Contact

- **Organisation**: XMV Solutions GmbH
- **Email**: <oss@xmv.de>
- **Website**: <https://xmv.de/en/oss/>
- **GitHub**: [@XMV-Solutions-GmbH](https://github.com/XMV-Solutions-GmbH)
