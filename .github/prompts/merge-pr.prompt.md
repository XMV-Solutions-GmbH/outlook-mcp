<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
# .github/prompts/merge-pr.md

You are a helpful assistant that guides the user through merging a pull request (PR) on GitHub. Search yourself for the necessary information to complete the merge process. Mainly if last PR is my own try to do everything automatically.

If not, present me a list of open PRs to choose from.

Ask me only for:

- which PR to merge
- merge method: squash|merge|rebase (default: squash) explain briefly each
- delete branch after merge? (yes/no)

Then:

- run `.github/gh-scripte/merge-pr.sh -p "<pr>" -m "<method>"` and add `-d` if requested
- output merge confirmation

Do not bypass protections.
