<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# .github/prompts/new-feature.md

When creating a new feature, please provide the following information to ensure consistency and clarity in our project management.

Ask me what we doing next, and provide:

- kind: feature|fix|proto|update|chore|docs|refactor|test|release
- title
- short description (what/why)

When I acknowledge, then:

- choose a slug yourself (lowercase, hyphenated)
- run:
  `.github/gh-scripte/new-feature.sh -k "<kind>" -t "<title>" -d "<description>"`
- confirm branch output (BRANCH/SLUG/KIND)
- implement the change following `.github/copilot-instructions.md`
- commit atomic commits
- push branch to origin

Do not leave any temporary files in the repository.
