<!--
SPDX-License-Identifier: LicenseRef-XMV-Proprietary
SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
SPDX-FileContributor: David Koller <david.koller@xmv.de>
-->

# Engineering Principles

A reusable, project-agnostic baseline for software development. These principles apply to every project where this file is dropped in. **Read this file before starting any task; it is the default behaviour, with project-specific overrides in `AGENTS.md` (or equivalent).**

This file is intentionally generic — nothing in here mentions a specific product, customer, or technology. Project-specific conventions go in `AGENTS.md`.

---

## 0. Maintenance of this file

This file evolves as we discover better ways to work. The maintenance contract:

- When a principle is **added or refined** in one project, evaluate whether to **back-port it** to other projects that already carry a copy of this file.
- When **starting a new project** with the same maintainer, check for this file; if it's missing, offer to seed it from the most up-to-date canonical version.
- Avoid project-specific drift. If you find yourself adding "for project X, do Y instead", that belongs in `AGENTS.md`, not here.

---

## 1. Language

All in-repo content is in **British English (en-GB)**: code, comments, docstrings, file and directory names, commit messages, PR titles and descriptions, configuration values, log messages, error strings, exception messages. Use *colour* not *color*, *initialise* not *initialize*, *behaviour* not *behavior*, *licence* (noun) and *license* (verb).

Chat / spoken communication may be in any language — only what lands in git is governed.

When you find non-English (or American-English) content in any file you touch, translate it as part of the current task. Domain terms with no clean English equivalent are translated, with the original noted once in a glossary.

**Exempt from this rule:** translation/localisation files containing strings shown to end users of the application in a multilingual context (e.g. `locales/de.json`, `i18n/fr/messages.po`, gettext `.po` catalogues). The non-English content in these files is the entire point of the file. The English source strings (and the keys, comments, and metadata around them) still follow this rule.

---

## 2. Sustained traceability of work

Every project must keep durable records of:

- **Planned work** — what's coming, what's in flight (the backlog).
- **Problems encountered + how they were solved** (the issues log).

The point of the issues log: **future-you searches past pain**. If the same root cause surfaces twice, you should be reading the prior resolution, not re-discovering it.

### Tooling

**Default for XMV projects: GitHub Issues + a repo-bound GitHub Project.** Both planned work and resolved-issue records live there from day one. The repo's GitHub Project is the canonical board; issues are the canonical units of work.

This is a deliberate update over the older "markdown TODO/ISSUES files in `docs/`" pattern that early XMV projects used. We learned that the markdown files drift, get forgotten, and lack the search / linking / assignment / labels / cross-repo references that make a backlog actually useful. GitHub gives those for free, and the repo-bound Project keeps the board scoped tightly to the repo it serves.

| Situation | Use |
|---|---|
| New XMV project | **GitHub Issues + a repo-bound GitHub Project from day one.** No markdown TODO/ISSUES files. |
| Existing XMV project still on markdown tracking | Migrate to GitHub Issues; keep the markdown file as a frozen historical artefact (read-only), do not extend it. |
| External tracker (Linear / Jira) is mandated by the customer | Use it instead of GitHub Issues. The principle is "one canonical tracker per project", not "GitHub specifically". |
| Pre-bootstrap moment, before the repo even exists | Capture decisions in chat or a scratch note, but file the issues immediately once the repo is up. |

External tools win because of search, assignment, labels, comments, milestones, cross-repo references, and integrations with PRs / CI / releases. Markdown files lose on every one of those.

### Issue format

Each issue has:

- **Title** — short, English.
- **Body** — at minimum: **Context** (what / why), **Acceptance criteria** (checkbox list of observable outcomes), **Out of scope** (what this issue does *not* cover), **Links** (related issues, PRs, docs).
- **Labels** — `type:feat` / `type:fix` / `type:chore` / `type:docs` / `type:test`; `area:<component>`; `priority:p0` / `p1` / `p2`. Add an `agent:<tool>` label (e.g. `agent:codex`, `agent:claude`) when an AI agent is the executor.
- **Milestone** — maps to a release where applicable (`v0.1.0 — MVP`, `v0.2.0`, …).
- **Status** — managed via the repo's GitHub Project columns; mirrors the legend in § 3.

### Resolved-issue records (post-mortems)

When an issue documents a problem-and-resolution (a bug, an incident, a near-miss), close it with a comment that captures:

- **Symptom** — what was observed.
- **Root cause** — what was actually wrong (resist the temptation to describe the fix here).
- **Resolution** — what fixed it; link the merging PR / commit.
- **Prevention** — what changed so it won't recur (test added, monitoring, doc, design change).

This is the searchable post-mortem trail. The PR's commit message is *not* a substitute — commit messages describe the change, not the historical incident. Future-you searches issues, not git log.

---

## 3. Status workflow

The default status legend, used by both TODOs and issues:

| Status | Meaning |
|---|---|
| `BACKLOG` | Identified, not yet planned for this cycle. |
| `TODO` | Ready to start. |
| `DOING` | Actively in progress. |
| `BLOCKED` | Waiting on something external (always note what). |
| `REVIEW` | Work done, awaiting human review/QA. |
| `DONE` | Reviewed and accepted by a human. |

For implementation-heavy projects, `DONE` may be split into `IMPLEMENTED → RELEASED → DONE`. Don't introduce these states until they're actually useful.

For concept/design work: draft → review → revise → `DONE`. Concept work is **never** marked `DONE` without explicit human sign-off.

### Critical rule

**An AI agent never self-marks a task as `DONE`.** The transition `REVIEW → DONE` is reserved for a human.

---

## 4. QA is mandatory

No work reaches `DONE` without quality review.

- For code: at minimum, code is read by a human; at best, automated tests pass and a smoke test against the real target environment passes.
- For concept work: another human reads the document and confirms the conclusions match intent.
- For one-off operational scripts: dry-run output is reviewed before live execution.

Skipping QA is acceptable only with explicit, recorded human override (e.g. "ship this hotfix now, post-QA tomorrow"). Default behaviour: QA every change.

---

## 5. AI as developer (vibe coding)

When an AI agent is the primary developer ("vibe coding"), the project must be set up so the agent can **actually verify what it builds**. This requires being precise about what kind of test verifies what — three layers, each with a different purpose, and the third is the one most often neglected.

### The three test layers

| Layer | What it verifies | External world | Speed |
|---|---|---|---|
| **Unit tests** | Pure-function / method-level logic | All externals mocked or stubbed | sub-second |
| **Integration tests** | Component contracts **within our own codebase** — handlers, modules, internal interfaces | **Mocks at the system boundary are acceptable** (e.g., a mock HTTP server standing in for an external API) | seconds |
| **Harness tests** | Our code against the **real external system**, in a **dedicated sandbox that is configured the way production is** | **Real** — real API endpoints, real auth flow, real tokens, real network | seconds to minutes |

These three are **not interchangeable**, and harness is **not** "an integration test that happens to use the real network." The distinction is load-bearing — see below.

### Why harness is its own category

Mocks codify **our assumptions** about an external API. Harness exercises **the API itself**.

Without a harness layer, the AI agent codes against its own mental model of an API — and has no feedback loop to discover when that model is wrong:

- when a permission scope means something different from what the docs imply,
- when the external API ships a behavioural change between SDK versions,
- when an edge-case response shape we never anticipated turns out to be the common case,
- when "it works in the SDK README" doesn't hold for our specific tenant/account/configuration.

**Harness is the AI-development enabler.** It is what lets the agent self-verify against reality, not just against its own assumptions. Unit + integration alone leave the agent confident in code that has never met the world it integrates with.

### What a harness sandbox is

A harness sandbox is **a real, dedicated test environment that mirrors production configuration as closely as possible**, accessed by **a real, dedicated test account** with **least-privilege scoping to the sandbox**.

- Real test tenant / sandbox account / isolated namespace (not a mock, not a stub server).
- Real OAuth / API-key / kubeconfig flow to authenticate (the agent goes through the same auth pipeline the production user would).
- The account is **scoped to the sandbox** — it must not have access to anything outside the test environment. Compromised harness credentials should not put production data at risk.
- The sandbox is configured the same way production would be (same library settings, same checkout policies, same cluster shape — whatever the relevant invariants are).

### Required from day one

The agent's working machine has all credentials and tools it needs to test against the harness sandbox:

- Credentials for the harness account (refresh token, OAuth-cached token, service-account key, kubeconfig). Cached locally on the agent's machine — **always, without exception**. Local harness access is the primary development feedback loop; no feature ticket enters "Doing" without it.
- Repo write access so the agent can commit.
- Tooling installed (via a project setup script — see § 8).

Tests are runnable from the agent's machine, not exclusively from CI. CI is for repeatable verification of merged changes; the agent's local environment is for **iterative development of those changes in the first place**.

**Testing is not CI's job.** Before any non-trivial push, run the relevant test layers locally — every human developer does this, and every AI agent must too. The local commands are project-specific (`make test`, `pytest`, `cargo test`, `go test`, `npm test`, …); what matters is that the agent runs them all before the push, not the spelling.

Three reasons this is non-negotiable:

1. **Speed of feedback.** A failing test that takes 30 seconds to surface locally takes 5–25 minutes via CI (queue + cold-start + sequential matrix + retries). Multiplied across the day, the difference is the difference between "ship a clean fix in one push" and "trial-and-error on green-checks-bingo via 8 force-pushes."
2. **Cost of CI minutes.** Hosted runners (GitHub Actions, GitLab CI, your own self-hosted fleet) and metered AI-agent runtimes bill by the minute. Burning CI minutes to discover a typo a type-checker or linter would have caught locally is throwing money at avoidance of a 30-second discipline. The cost is real and metered; treat it as such.
3. **CI as confirmation, not discovery.** When CI fails on a push, that should be a surprise — a regression in something local tests didn't cover, or an environment-specific issue (different OS, different language version, missing credentials the agent didn't have). CI catching an obvious local bug means the local test step was skipped, which is a discipline failure, not a CI feature.

The push-without-local-test pattern is sometimes rationalised as "CI is fast enough" or "I trust the lint passes." Both are wrong: CI is slow at the granularity of iteration, and obvious bugs ship through lint constantly. **If running the test suite locally is painful, fix the dev-experience setup before the next feature commit** — it is paying off interest on the slowest part of the workflow.

Special note for AI agents: the temptation to push-and-watch is high because watching feels like progress; it is not. Each iteration that goes through CI when it could have gone through a local test run costs the maintainer an order of magnitude more attention and time.

**Harness layer too — not just unit/integration.** "Locally" includes the harness layer (per § 5 "Required from day one"), not only the fast layers. A harness suite that is only ever run by CI is a harness suite that fails on environment-specific issues the agent could have caught in 60 seconds. Lint, type-check, full test ladder, harness: all locally, before the push.

**Fix all errors locally before the next push.** When local testing surfaces several failures, fix them all and run the suite once more locally to confirm green; do *not* push after the first fix, watch CI fail on the second, push again, watch CI fail on the third. That iteration is the most expensive shape of the same mistake: it converts a single local round into N CI rounds at N× the wall-clock and N× the metered cost.

### Required in every App Concept

Every project's App Concept (or equivalent product/architecture document) must include a **Testability** section that names all three layers explicitly:

- **Unit**: where unit tests live, what's mocked.
- **Integration**: which boundary mocks exist, what internal contracts are tested.
- **Harness**: what the sandbox is, who the test account is, how the agent authenticates against it, what the least-privilege scope is, what end-to-end paths are validated.

Plus the operational answers per § 5:

- What environments exist (local, sandbox-harness, staging, production) and what each is for.
- Where the AI runs each layer of tests (unit + integration: locally and in CI; harness: always locally on the agent's machine; in CI: project-specific decision — see § 5 "Harness tests in CI").
- What's tested automatically vs. what requires human eyes.

Without all of this, vibe coding degrades to "the AI writes plausible-looking code that nobody actually verifies against reality."

### Required ticket order

For projects where AI is the primary developer, the ticket sequence is:

1. **Package / repo skeleton.**
2. **Harness sandbox setup** — provision the sandbox, create the least-privilege test account, install credentials on the agent's machine, write **one** harness test that proves end-to-end auth works against the real system. **No feature tickets enter "Doing" before this is green.**
3. **Unit + integration test scaffolding** — pytest/vitest/etc. structure, the first failing test of each kind.
4. **Feature tickets** — each ships a harness test, or explicitly justifies why unit/integration suffices for that piece. The harness test covers **both the sunny path and the key error paths** — at minimum: resource not found, access denied, conflicting state. Error paths are where real API behaviour most often diverges from documentation and mock assumptions.

The harness-setup ticket is the gate. If the gate isn't green, feature work cannot start — because feature work without harness is feature work without verification, and we end up shipping code that compiles and passes mocks but breaks against the real API on first contact.

### Issue-spawn discipline

When deriving an issue backlog from a concept document for an AI-driven project:

- **Spawn one ticket per test layer.** Unit, integration, and harness each get their own issue. Never roll harness into integration "to keep the count down" — it loses the property that the harness layer is a hard gate, and it lets feature work proceed without real-system verification.
- **Fix the concept before spawning issues.** If the concept's Testability section is missing or names fewer than three layers, that is a concept-doc defect. Patch the concept first; only then derive the backlog. Otherwise the backlog inherits the concept's blind spot — which is exactly the failure mode this section exists to prevent.
- **Mark the harness-setup ticket as the gate** in whatever your tracker calls dependencies. Feature tickets must list it under "Depends on". The visual reminder keeps the rule alive after the initial planning session.

### Anti-patterns

- **Running tests only from CI.** The agent gets no feedback loop, every iteration burns billable CI minutes, and trivial bugs that a type-checker / unit-test runner / linter would have caught in 30 s instead waste 15+ minutes of queue-and-matrix CI time per push. CI is for confirmation, not discovery. Provide local harness access on the agent's machine and use it before every push.
- Treating "integration" and "harness" as the same thing. They aren't. Mocks-at-boundary integration tests are valuable but they validate our assumptions, not the external API. Both layers exist for different reasons; you need both.
- Letting feature tickets land before the harness layer works. The first time the code talks to the real system is the worst time to discover the auth flow is broken or the scope is wrong.
- Using a powerful test account "because it's faster to set up." The harness account is least-privilege scoped to the sandbox, full stop. A leaked admin token from the agent's machine is not an acceptable failure mode.
- Generating an issue backlog from a concept that has no Testability section. The missing section is the defect; spawning issues first only buries it.
- Harness tests that cover only the sunny path. The most valuable thing a harness test can verify is the error shape: does a missing resource really return 404? Does a locked item really block writes? Is the error body structured the way our code expects? A harness suite without error-path tests fails to catch the class of divergence it was built to catch.

### Harness tests in CI: a project-specific trade-off

Running harness tests as a gate in the CI pipeline is **not universally required**. It carries ongoing costs that vary by project:

- **Credentials in CI** — harness credentials must be stored as repository secrets. Every CI runner executing the harness job has access to tokens for the real external system. A compromised secret means compromised external access.
- **External availability** — CI becomes dependent on the external system. An unrelated API blip can fail a PR that touches nothing API-related.
- **Maintenance burden** — credentials expire, test accounts need reprovisioning, sandbox environments drift. That maintenance falls on the project's maintainer at the worst possible moment.
- **CI speed** — harness tests are seconds to minutes. They extend PR cycle time for every contributor.

The **benefits** are also real: regressions in external API behaviour are caught before merge; contributors without local harness access have their PRs verified end-to-end.

**The decision is project-specific and must be recorded.** If harness tests run in CI, the decision — and the reasoning — must be captured in a Decision Record in `docs/proposals/` (see § 16). A future agent or maintainer needs to understand why, without access to the founding conversation.

---

## 6. Source control

- All source in **GitHub**.
- English commit messages, **conventional-commit** style (`feat(scope): subject`, `fix(scope): subject`, `chore: subject`, `docs: subject`).
- One logical change per commit.
- Never commit secrets, generated configs, lock files for ephemeral state, vendored binaries (use `.gitignore`).
- **No `git push` without explicit human request.**
- **No `git config` modification without explicit human request.**
- Prefer creating new commits over amending. Amend only on un-pushed commits and only with explicit reason (e.g. fixing the author of a fresh initial commit).

### CI vigilance: watch every push, fix red immediately

Every `git push` (direct-to-trunk or via merging a PR) implicitly creates a CI run. The committer's job does not end at "push succeeded" — it ends at **"CI for that commit went green"**.

Operationally:

- **Watch the CI run** for the commit you just pushed. `gh run watch <id> --exit-status` blocks until completion and exits non-zero on failure; use it.
- **Red CI on the trunk branch is a P0 incident.** The person who broke it fixes it before doing any other work. If a fix is non-trivial, **revert the breaking commit** rather than leaving trunk red while you investigate. Trunk red blocks every other contributor's ability to merge.
- **Don't assume CI agrees with you because the local tests pass.** CI runs different OS, different Python, different env-var defaults, fresh-clone state. A "works on my machine" with red CI is still red CI.
- **Notifications can lag.** If GitHub emails you about a CI failure five minutes after you've pushed three more commits, check the SHA the email references — it may already be old news. But the converse also holds: if the email is recent and the SHA matches your latest push, react.

This is the discipline that keeps trunk deployable per § 13. Without it, "PR is always in a deployable state" degrades to "PR is in a deployable state until something quietly broke and nobody noticed."

### PR-batching for thematic ticket-series

When a single planned outcome spans multiple tickets touching the same surface — a refactor series, a migration, an audit-driven fix run — default to one *bundle* PR that closes the whole series, not one PR per ticket.

**The footgun this defuses.** When CI runs on every push, the natural response from both human contributors and AI agents is "CI is testing this anyway, I'll skip the local run." That hollows out the local-test discipline § 5 spends real effort defending. Trial-and-error against CI is an order of magnitude slower than against `make test` — and on metered runners (§ 5, point 2) it is also expensive. Bundle PRs pull the equilibrium back: one CI gate at the end of the series, not N.

**How to apply.**

- Open a long-lived feature branch off trunk; each ticket merges into it as a regular commit (or a stacked PR if reviewers need per-ticket sign-off).
- Run the full local test suite before each push to the feature branch — § 5 applies *inside* the branch, not only at the final merge into trunk.
- Each commit references the ticket it closes (`closes #123`) so the audit trail survives the squash.
- Only the final merge of the feature branch into trunk is the "must be CI-green" gate.

**When 1-ticket-1-PR is right.** Independent fixes against unrelated surfaces, or when a reviewer genuinely needs a smaller diff for a sensitive change. The default is *bundle*; the override is *per-ticket with reason*.

---

## 7. Documentation baseline

Every project must have, at repo root or under `docs/`:

| Doc | Purpose |
|---|---|
| `README.md` | What this is, how to set it up, how to run it. |
| App Concept (e.g. `docs/app-concept.md`) | What the product does, who for, why. Includes a Testability section per § 5. |
| Architecture (e.g. `docs/architecture.md`) | Target-state of how the system runs. |
| Secret management (e.g. `docs/secrets.md`) | How secrets are generated, stored, propagated, rotated. |
| `AGENTS.md` (or equivalent) | Project-specific conventions, tech stack, and AI-agent behaviour for this repo. Referenced by tool-specific files (`CLAUDE.md`, `.github/copilot-instructions.md`) which are pointers back here. |

The backlog and the resolved-issue log live in **GitHub Issues + the repo-bound GitHub Project** (see § 2), not in markdown files.

Docs are kept in sync with reality. **Stale docs are a bug** — fix as part of the change that makes them stale.

### README structure

A `README.md` is the first thing a new reader (human or agent) sees. The skeleton that pays back across XMV projects:

1. **Title + badges** (licence, build status, coverage where applicable).
2. **One-sentence pitch as a blockquote**, immediately under the badges. Under 200 characters. This shows up unrendered in search results, so it has to stand alone.
3. **"What is this for?"** — two or three paragraphs of the user's actual situation: what they have, what they want to do, why the obvious alternatives don't quite fit. Concrete and specific (named artefacts, named constraints) before any feature list. End with one sentence on how this project solves it differently.
4. **Features** — what each feature does for the user, not how it's implemented.
5. **Installation** — copy-pasteable, common path first.
6. **Use case** — a short dialogue or worked example showing the headline workflow. Make it the golden path, not an edge case.
7. **Usage** — detailed, one sub-section per major surface.
8. **Documentation** — link out to the deeper docs.
9. **Contributing** — link to `CONTRIBUTING.md`.
10. **Licence** — name the licence; link the file.

---

## 8. Reproducible setup

Any environment setup, tool install, or one-off operational step must be **scripted and committed to the repo**, never run ad-hoc on a live shell.

- Dev environment install → `scripts/setup-dev-env.sh` (or equivalent), idempotent, supports the maintainer's primary OSes.
- Bootstrap of new infra / cluster / database → `scripts/bootstrap-*.sh`.
- Routine operations (backup, restore, smoke test) → individual scripts under `scripts/`.

If a step is not scripted, the next person to need it has to re-derive it. That's a slow-moving outage.

---

## 9. Transparent implementations

When composing operational scripts, **prefer primitives over wrapper tools** unless the wrapper provides clear durable value beyond convenience.

- Use the platform's official CLI / SDK directly rather than a third-party wrapper that does the same in opaque steps.
- Wrappers are acceptable when they encapsulate non-trivial state — but the operator still needs to understand the underlying mechanic.

The principle: a competent reader of the script should understand each step without learning a new tool's CLI.

---

## 10. Principle of least surprise for the next agent

Every change leaves the repo in a state where the next agent — human or AI — can pick up and continue **without asking questions**.

- The backlog and the resolved-issue records (GitHub Issues per § 2) reflect current state, including in-flight work.
- Status reflects reality (no `DONE` items that aren't actually done).
- Decisions made in conversation that affect the codebase are written into the relevant doc, not left in chat.
- Open questions are recorded as `(TBD)` markers in the doc and as open issues in the tracker, not held in someone's head.

A new agent should be able to read `AGENTS.md` + this file + recent commits + the repo's GitHub Project board and know what to do next.

---

## 11. Licensing & attribution

Every XMV proprietary project has:

- A `LICENSE` file at the repo root containing the XMV Proprietary Licence (version as agreed for the project). The specific version and any amendments are noted in `AGENTS.md`.
- A `README.md` "Licence" section that names the licence and links to the file.
- File-level attribution per **SPDX** so each source file declares its licence and contributors machine-readably.

### Per-file SPDX header

Every source file authored in the project carries an **SPDX-style header** at the very top (after a shebang line if any):

```text
SPDX-License-Identifier: LicenseRef-XMV-Proprietary
SPDX-FileCopyrightText: <year> XMV Solutions GmbH
SPDX-FileContributor: <name> <<email>>
```

- The SPDX identifier `LicenseRef-XMV-Proprietary` is used because this licence is not an SPDX standard licence — the `LicenseRef-` prefix is the SPDX-compliant way to reference a custom licence.
- The first `SPDX-FileContributor` line is set when the file is **created** and is **never overwritten**. This honours the German *Urheberrecht* (moral right of authorship), which is inalienable.
- Subsequent substantial contributors **append** additional `SPDX-FileContributor` lines; they do not replace the original.
- The agent populates the contributor line from the current `git config user.name` / `user.email`.

### Files exempt from headers

- `LICENSE` — this IS the licence.
- Auto-generated files (lock files, build artefacts, vendored binaries).
- Third-party code (already carries upstream licence; do not replace with XMV SPDX).

All other files we author — including documentation (Markdown) — get a header. For Markdown the header is an HTML comment block at the very top of the file, before any content.

### Third-party dependencies

When the project uses open-source dependencies (packages, libraries), their licences are not affected by this file. Ensure all dependencies have compatible licences for the intended distribution model. For customer-deliverable projects, verify that included open-source licences permit the delivery scope (e.g. LGPL in a SaaS delivery vs. on-premises install). Maintain a `docs/third-party-licences.md` for any project that is delivered to external parties.

---

## 12. No AI attribution in source

The AI agent (Claude, GPT, any other) is a tool. **It is not credited as an author or co-author anywhere in the codebase or its history.**

- No `Co-Authored-By: Claude …` (or any AI tool) lines in commit messages.
- No "Generated by AI" headers in source files.
- No mention of model names or versions in code or comments.
- No AI-named `SPDX-FileContributor` entries.

**Why:** the codebase is a deliverable. Users / auditors / future maintainers should see the human authors who ran the toolchain — not the toolchain itself. Attribution to the toolchain belongs in dev process documentation, not in source.

The author of every commit is the **human user** (whose identity is in `git config user.name` / `user.email`). The agent acts on the human's behalf — it is not a co-author.

---

## 13. Pull request discipline

A new project starts as **single developer, direct-to-`main`**. There is no value in PR overhead when one person is committing.

Switch to **feature branches + Pull Requests** when **any** of these becomes true:

- A second developer (human or agent) joins the project.
- The project has external users (a published release, deployed service, customer deliverable) — i.e. an unreviewed bad commit has user impact.

From the moment PRs are introduced, the following rules apply.

### A PR is always in a deployable state

Every PR opened for review represents work that **could merge as-is**:

- **CI is green on the PR's head commit at merge time.** Not "was green earlier and probably still is", not "would be green if the flake settled" — actively green when the merge button is clicked. Branch protection should require this; if it doesn't, the PR author manually verifies it.
- All tests pass — unit, integration, harness (the three layers from § 5).
- Documentation is updated alongside the change (App Concept, Architecture, Secrets, README, CHANGELOG). No new `(TBD)` markers without a corresponding follow-up issue.
- New behaviour either has tests, or the PR explicitly notes why not.
- No half-finished work, no commented-out blocks, no dead branches.
- Test automation has been **extended** for any new behaviour — adding a feature without extending the harness counts as half-finished.

A PR is not a "save point" or a "share-with-the-team-for-feedback" mechanism. It's a proposal to merge into trunk. Use draft PRs explicitly when you want to share work-in-progress.

After merge, see § 6 "CI vigilance" — the post-merge CI run on trunk is the committer's responsibility too, not just the pre-merge one on the PR branch.

### Four-eyes review is a separate concern from PR discipline

Strictly two different things:

- **Pull request discipline** (above) — a clean unit of work. Always applies once we use PRs, even with one developer.
- **Four-eyes review** — a second human reads and approves before merge. Introduce this when team size justifies it; until then, the PR author may merge their own PR.

### Branch protection grows with the team

Branch protection rules (require status checks, require review, prevent force-push to `main`) get configured **as the team grows into them**. Don't pre-emptively lock down a one-developer repo — it just slows down the only person working.

A reasonable progression:

1. Single dev, direct commits — no protection.
2. Single dev, PR-only (self-merge) — `main` requires PR + linear history.
3. Multi-dev — add required status checks (CI green) + required review.
4. Customer-facing — add CODEOWNERS + required review from owners.

### Multi-contributor coordination is a separate concern

When a project has more than one contributor working in parallel — human developers, AI agents, or a mix — the *coordination* of those parallel streams (how work is broken down, who picks up what, how branches converge back to trunk without merge-hell, how stakeholder escalations are routed) is described in **`PROJECT_MANAGEMENT_PRINCIPLES.md`**, not here. Engineering Principles cover how a unit of work is done well; Project Management Principles cover how multiple units of work are coordinated to a clean trunk.

The PR-discipline rules above (deployable state at merge time, CI green, docs updated) still apply to every branch at the moment it's merged — `PROJECT_MANAGEMENT_PRINCIPLES.md` adds the rule that *who* merges and *in what order* is the orchestrator's call, not the individual contributor's.

---

## 14. Source is the source of truth (no drift, ever)

Every change to a system's running state must be made by changing the source it derives from — never by mutating the live system directly. If a divergence between actual state and source ("drift") is discovered, **the source is corrected**, the change is committed, and the source is re-applied to bring the system back. The live mutation is never the endpoint.

Concrete behaviours:

- **No "I'll fix the migration later".** If you patch a database by hand, the same change goes into a migration file in the same change session, and the migration is run on a fresh DB to verify it lands the same shape.
- **No long-lived hand-tuned config on a server.** If you SSH in and edit a config to fix something, the same fix goes into the source within hours, with a test (or at least a smoke check) that prevents recurrence — captured as an issue with `Prevention:` filled in.
- **No "released artefact patched in place".** If a published package has a bug, the next release fixes it; the previous artefact is yanked / superseded, not silently rebuilt.

### Why this matters

The source in git **is** the system. If it doesn't describe what's running, the source is wrong (or the system is — fix whichever). Otherwise:

- **Source loses authority** — people start treating it as advisory.
- **Reproducibility dies** — a fresh build / install / deploy doesn't produce the running state.
- **Reviews become theatre** — what's reviewed in PRs no longer matches what's deployed.
- **Onboarding becomes folklore** — newcomers can't learn the system from the repo, only from the people who hand-tuned it.

Source-of-truth discipline is what separates a maintained system from a haunted one.

---

## 15. Documentation mirrors the repo (TODO closes only after docs catch up)

The repo is the source of truth for **what** behaves how; documentation is the source of truth for **why and how to operate it**. They must agree at all times.

Operationally:

- **Every TODO is captured before work starts.** Even if the work is a 30-min tweak — write the entry, link it from the commit. "Forgetting" a TODO means losing the audit trail that lets a later reviewer / future-you reconstruct intent.
- **Every TODO closes only after the documentation that describes what shipped reflects the new reality.** The work is not done until anyone reading the relevant doc would be told the right thing. Closing a ticket "because the code works" while leaving stale README/SECURITY/USAGE sections behind is a defect.
- **Implementation drifts from plan — that's fine, document the new shape.** When reality differs from the original plan (and it usually does at the margins), the doc reflects what shipped, not what was planned. Lessons learned belong in the entry's body, not in a parallel "draft" page.
- **Stale docs are open work, not "well, technically the code is right."** If `docs/X.md` says X happens but the code does Y, that is a bug to log and fix — not a quirk to tolerate.

### What this rules out

- Composing artifacts that have to be re-edited on every code change but add no information beyond what the repo itself shows. Concrete example: an ASCII tree of the repo layout in `README.md` provides no information that `ls -R` doesn't, and bit-rots quickly. **If a doc artifact requires per-change maintenance without commensurate value, delete it. The repo is the freshest reference.**
- Multi-page TODOs that promise "I'll update the docs later." Update them now or revert the change.
- Documentation as marketing — overstating what's implemented, hiding caveats, or leaving "phase 2" features as undated TODOs in a doc that reads like spec.

### What this requires

- A doc-pass at the end of every meaningful piece of work. The relevant doc gets read end-to-end and corrected.
- The PR description (or commit message in the trunk-only era) lists the docs that were touched alongside the code change.

---

## 16. Project-specific decisions as permanent records

Engineering Principles are project-agnostic by design. Some principles explicitly name a trade-off that each project must decide individually — "whether to run harness tests in CI" (§ 5) is one example; "which third-party auth library to use" is another. When a project exercises one of those choices, **the chosen path and the reasoning must survive in a permanent, findable record**.

The record lives in `docs/proposals/`, using the format described in `docs/proposals/README.md`. Each Decision Record captures:

- **What was decided** — the chosen option, stated plainly.
- **Why** — the constraints and trade-offs that drove the choice: costs accepted, benefits sought, alternatives discarded.
- **Consequences for future maintainers** — what assumptions are now baked in; what to revisit if the context changes.

### Why Decision Records matter

A new agent (or human maintainer) who inherits the project has no memory of founding conversations. It can read the code. It can read the issue tracker. But it cannot recover the reasoning behind choices that are invisible in the code — *"why is harness wired into CI?" "why this library and not that one?"* — unless someone wrote it down.

Decision Records are that writing-down. They are append-only history: a record is never deleted, only superseded. If a later decision reverses or refines an earlier one, the new record references the old one and explains the change.

### When to write a Decision Record

- Whenever Engineering Principles say "this is a project-specific trade-off." The Decision Record is the documented answer.
- Whenever a choice is **costly to reverse** and the reasoning will not be obvious from the code six months later.
- Whenever a choice was **made in conversation** (chat, verbal, comment thread) and carries lasting weight for the project. Conversations evaporate; records do not.

### What not to put here

Routine implementation choices (variable names, small refactors, which test file to add a test to) do not need Decision Records. The test: *"would a future maintainer, reading only the repo, think this was a mistake and undo it?"* If yes, write the record.

### Finding decisions in an unfamiliar project

The first place to look is `docs/proposals/`. The README there lists all proposals with status. Decision Records are accepted proposals with `Status: Implemented` or `Status: Accepted`. Reading that directory is part of any new agent's bootstrap for the project.
