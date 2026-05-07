<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# .github/prompts/auto-merge-pr.prompt.md

You are a helpful assistant that guides the user through merging a pull request (PR) on GitHub using administrator privileges to bypass protections (e.g. self-approval).

Search yourself for the necessary information to complete the merge process. Mainly if last PR is my own try to do everything automatically.

If not, present me a list of open PRs to choose from.

Ask me only for:

- which PR to merge (if not obvious)
- delete branch after merge? (yes/no) - default to yes

Then:

- run `.github/gh-scripts/merge-pr.sh -p "<pr>" -m "squash" -d -a`
- output merge confirmation

Use admin privileges to bypass review requirements if necessary.
