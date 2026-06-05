<!--
SPDX-License-Identifier: LicenseRef-XMV-Proprietary
SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
SPDX-FileContributor: David Koller <david.koller@xmv.de>
-->

# AGENTS.md — canonical brief for AI coding agents

This is the tool-agnostic brief for AI agents working in this repo. Claude Code, Codex, GitHub Copilot, Cursor, Aider — every coding agent reads this same file. The tool-specific files at conventional locations (`CLAUDE.md`, `.github/copilot-instructions.md`, `.cursor/rules/*.mdc`, `CONVENTIONS.md`) are one-line pointers back here; do not expect content there.

This file is **project-agnostic**. Identical across every repo. Anything project-specific (tech stack, tracker URL, environment hostnames, mailbox addresses, repo or subproject map, overrides of the engineering baseline) lives in `PROJECT_SPECIFICS.md` — read that next if it exists.

## Reading order

**MANDATORY — at the very start of every session, before responding to anything, read items 1 and 2 below in full. Do this unconditionally, regardless of what the operator asks. Do not assume you already know their contents from a prior session.**

1. **[`ENGINEERING_PRINCIPLES.md`](ENGINEERING_PRINCIPLES.md)** — XMV's project-agnostic engineering baseline. Language, status workflow, three test layers, source-control rules, CI vigilance, doc-mirrors-repo, source-of-truth, PR discipline, licensing. Read in full.
2. **[`PROJECT_MANAGEMENT_PRINCIPLES.md`](PROJECT_MANAGEMENT_PRINCIPLES.md)** — XMV's project-agnostic coordination baseline. Orchestrator role, contributor briefs, serialised merges, escalation, lessons-learned, communication brevity. Read in full.
3. **This file** — what you're reading. AI-specific behaviour rules that apply to every repo.
4. **[`PROJECT_SPECIFICS.md`](PROJECT_SPECIFICS.md)** *(optional — read if present)* — project-specific facts and overrides for this repo. If the file does not exist, the project has no project-specific content beyond what the principle files cover.
5. **[`README.md`](README.md)** and any documents referenced from `PROJECT_SPECIFICS.md` (typically `docs/app-concept.md`, `docs/architecture.md`, `docs/testconcept.md`).

Anything that applies to **humans too** lives in `ENGINEERING_PRINCIPLES.md` or `PROJECT_MANAGEMENT_PRINCIPLES.md`, not here. This file is for the failure modes and operational rules that are specific to AI agents.

---

## How to behave as an AI agent in any repo

### Communication with the operator: be brief

`PROJECT_MANAGEMENT_PRINCIPLES.md` § 11 covers this in full and applies to every interaction. Short version: keep questions one or two sentences, state options + recommendation, do not pre-emptively explain the reasoning. The operator asks "why?" if they want the long version.

### Stop and ask before external actions

External actions are anything visible outside this working copy. Before any of these, **stop and confirm with the operator** unless the operator has explicitly authorised the action in the current task:

- `git push`, `git push --force`, deleting a remote branch.
- `gh pr create`, `gh pr merge`, closing or reopening issues, posting issue or PR comments.
- `git tag -a` followed by `git push origin <tag>`, anything that triggers a release pipeline.
- `gh secret set`, secret rotation, anything touching repository or organisation settings.
- `gh release create`, package publishing.
- Any external API call that mutates remote state (cloud APIs, SaaS APIs, Slack, email, …).

The operator authorising one external action authorises that action's stated scope only — not the next external action.

### Self-verification before claiming done

After every code change, run the test harness. After every push, watch CI to completion (`gh run watch <id> --exit-status`) and react if it goes red. Never claim a task complete without:

- Tests pass locally (unit + integration; harness if relevant — see `ENGINEERING_PRINCIPLES.md` § 5).
- CI on the pushed commit is green.
- Tracking issue is closed via the PR (or status moved on the Project board).
- Docs reflect what shipped — `README.md`, `CHANGELOG.md`, app concept, secrets, architecture, whichever apply (`ENGINEERING_PRINCIPLES.md` § 15).
- No new `(TBD)` markers without a follow-up issue filed.

### Large multi-PR work: orchestrator mode

For investigations, repetitive triage, and self-contained chores, delegate to a sub-agent when the work would meaningfully distract from a primary goal — see the sub-agent delegation guidance below.

For larger work — multi-PR implementations, multi-repo migrations, projects with their own concept ticket — switch into orchestrator mode and follow `PROJECT_MANAGEMENT_PRINCIPLES.md` § 2–9 in full. Note especially **§ 4: plan the parallelisation roadmap *before* spawning any contributor** — breadth-first planning precedes depth-first execution. Then hold the concept ticket as single source of truth, spawn sub-agents on their own feature branches (one branch per contributor), never let sub-agents merge themselves, serialise merges yourself, relay operator escalations.

**Always ask the operator before activating orchestrator mode** (PMP § 3) — even when the heuristics clearly trigger.

### Delegate parallelisable work to sub-agents

When a task is logically self-contained, can run in parallel with your current main thread, and would meaningfully distract you from a primary goal if done inline, spawn a sub-agent for it. Brief the sub-agent with the three named parts from `PROJECT_MANAGEMENT_PRINCIPLES.md` § 5.3 (Mission, Constraints, Output specification) — nothing else load-bearing. Constraints must always include the four visibility rules from § 5.7 (wall-clock budget, early-PR rule, 3-iteration rule, mandatory Output fields) — without those the sub-agent can disappear into a silent rabbit hole. The orchestrator also caps in-flight parallel contributors per § 5.6 (typical: 5).

Concrete examples of what to delegate: investigations, multi-step diagnostics, repetitive triage of similar items, multi-hour bring-ups, code-base sweeps.

What not to delegate: single-step actions, tasks the operator explicitly handed to you personally, decisions that need operator input (those stay in the main thread so the operator sees them).

### Cross-project work

If a task touches two repos under the same workspace, read both repos' `PROJECT_SPECIFICS.md` (where present) and any project-specific docs they reference, then decide which repo the deliverable belongs in. Stay on one repo at a time; do not edit cross-repo from a parent directory if it can be avoided.

### Initialisation gate

If `docs/app-concept.md` (or the project's equivalent product/architecture document) is missing, **stop and prompt the operator**. Do not begin implementation. Per `ENGINEERING_PRINCIPLES.md` § 5 the harness layer must also be green before feature tickets enter "Doing" — verify this gate too on the first feature ticket of a project.

### When you edit Markdown

If a project-specific Markdown style guide exists (typically `docs/markdown-style.md`, referenced from `PROJECT_SPECIFICS.md`), read it before editing Markdown in this repo. The style rules live in a separate file precisely so they do not load as context when you are working on code that does not touch Markdown.

### Iteration protocol (default)

```text
1. Operator describes feature requirement.
2. Agent files a GitHub Issue capturing the work
   (## Context / ## Acceptance criteria / ## Out of scope / ## Links).
3. Agent writes failing tests in the test harness (TDD).
4. Agent runs tests (expected: FAIL).
5. Agent implements minimal code.
6. Agent runs tests (expected: PASS).
7. Agent refactors while keeping tests green.
8. Agent opens a PR that closes the issue ("Closes #N" in the PR body).
9. Agent watches CI to completion; reverts or fixes if red.
```

For non-trivial changes, log the design decision under `docs/proposals/` before writing code (see that folder's README for the lifecycle).

### Pre-completion checklist

Before declaring work done, verify each item:

- [ ] Tests pass locally (unit + integration; harness if relevant).
- [ ] CI on the pushed commit is green.
- [ ] Tracking issue is closed via the PR (or status moved on the Project board).
- [ ] Docs reflect what shipped — README, CHANGELOG, app concept, secrets, architecture, whichever apply.
- [ ] Commit messages follow Conventional Commits (`feat(scope): subject`, etc.; see `ENGINEERING_PRINCIPLES.md` § 6).
- [ ] No `Co-Authored-By: <AI tool>` lines, no AI tool names in source comments or SPDX headers (see `ENGINEERING_PRINCIPLES.md` § 12).
- [ ] No new `(TBD)` markers without a follow-up issue filed.
