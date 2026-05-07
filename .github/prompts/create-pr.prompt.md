<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# .github/prompts/create-pr.md

You act as a senior developer creating a pull request for the Talos API Rust client library.

Exit with error if on a main branch. Perhaps give advice to create a feature branch with prompt /new-feature

If in a feature branch,
try to create from our current branch

- PR title
- What (1 paragraph)
- Why (1 paragraph)

if I acknowledge, then:

- draft How + Tests bullets yourself and ask me to confirm quickly (single message)
- run cargo fmt, cargo clippy, cargo test
- if any fail, correct errors
- run `.github/gh-scripts/create-pr.sh` with:
  - -t title
  - -w what
  - -y why
  - -h how-bullets
  - -x tests-bullets
  - optional -d docs
- output PR URL and the final PR title/body

Do not change code during PR creation.
Do not create or commit any PR text files (temp/heredoc only).
