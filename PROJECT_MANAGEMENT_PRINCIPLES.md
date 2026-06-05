<!--
SPDX-License-Identifier: LicenseRef-XMV-Proprietary
SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
SPDX-FileContributor: David Koller <david.koller@xmv.de>
-->

# Project Management Principles

A reusable, project-agnostic baseline for coordinating multi-contributor work — human developers, AI agents, or any mix of the two. These principles apply to every project where this file is dropped in. **Read this file before starting any multi-contributor implementation; it is the default behaviour, with project-specific overrides in `AGENTS.md` (or equivalent).**

This file is intentionally generic — nothing in here mentions a specific product, customer, or technology. Project-specific conventions go in `AGENTS.md`. Engineering practice (test layers, source control hygiene, SPDX headers, licence handling) lives in `ENGINEERING_PRINCIPLES.md` — this file is about *how the work is coordinated*, not how the work itself is done.

---

## 0. Maintenance of this file

This file evolves as we discover better ways to coordinate work. The maintenance contract mirrors `ENGINEERING_PRINCIPLES.md` § 0:

- When a principle is **added or refined** in one project, evaluate whether to **back-port it** to other projects that already carry a copy of this file.
- When **starting a new project** with the same maintainer, check for this file; if it's missing, offer to seed it from the most up-to-date canonical version.
- Avoid project-specific drift. If you find yourself adding "for project X, do Y instead", that belongs in `AGENTS.md`, not here.

---

## 1. Language

Same rule as `ENGINEERING_PRINCIPLES.md` § 1: all in-repo content is in **British English (en-GB)**. Code, comments, commit messages, PR titles, issue bodies, ticket comments, lessons-learned notes. Chat and spoken communication may be in any language.

---

## 2. The orchestrator role

Every multi-contributor project has exactly one **orchestrator** at any given moment — the person or designated coordinating thread who:

- Holds the **concept ticket** (or planning document) as the single source of truth for what's being built and why.
- Decides what gets broken into parallel work-streams and who picks up each one.
- **Serialises convergence** — sub-streams produce branches; the orchestrator decides the order in which those branches merge back to trunk, handles rebases, and runs the merge themselves.
- Acts as the **single point of escalation** to the project stakeholder (operator, customer, product owner). Contributors do not talk to the stakeholder directly while work is in flight.
- Captures **lessons-learned** as the project runs, so the next iteration of this same pattern goes smoother.

In a single-contributor project the orchestrator role collapses into the contributor — there's nothing to coordinate. The role only becomes load-bearing once more than one stream of work needs to land in the same trunk.

### Who can be an orchestrator

- A human technical lead / project manager.
- An AI main thread (the conversation the stakeholder is interacting with), with sub-agents acting as contributors.
- A mix: a human orchestrator coordinating one human pair and one AI sub-agent, for example.

The role is defined by the **responsibilities** above, not by what kind of entity holds it.

---

## 3. When to apply the orchestrator pattern

A project qualifies as **"large enough to need orchestration"** — and therefore triggers this whole document — when it meets at least one of:

- Estimated to need **≥ 3 PRs** across one or more repos.
- **Multiple repos** are touched by the same logical change.
- Implementation is expected to span **more than one working day**.
- A **separate concept ticket or planning document** already exists for it (the existence of a concept doc is itself a signal that the work is too large to wing).

### Always ask the stakeholder before activating

Heuristics catch most cases but not all. The stakeholder may have reasons to keep a small-looking project under direct main-thread control (e.g. they want to learn the codebase by reading every diff themselves), or to escalate a small-looking project that touches load-bearing infrastructure.

**Before activating orchestrator mode, ask explicitly.** Phrase the question with the heuristics that triggered it:

> *"This project hits {N} of the four orchestrator-mode criteria — {list them}. Shall I run it as orchestrator (contributors do the implementation on their own branches, I coordinate the merges and stakeholder escalations), or do you prefer that I do it inline myself?"*

The stakeholder decides; never assume. **Skipping this confirmation is the most common failure mode** — it removes the stakeholder's chance to keep visibility over something they considered theirs to drive.

### 3.1 Concept-first: assess size, write the concept, get it reviewed

Before any project-sized work begins implementation, it passes through a concept gate. The four moves below run in order; together they turn "a task the operator just handed over" into "a reviewed, corrected, operator-approved concept".

#### 1. Assess size on every handed task — and reassess mid-task

On every task the operator hands over, the orchestrator estimates scope against the four § 3 criteria (≥ 3 PRs, multiple repos, > 1 working day, a concept doc already exists). The assessment is **not** a one-off at hand-over: if a task that looked small turns out mid-implementation to be project-sized, the orchestrator **stops the moment it notices** and reclassifies — *"this is bigger than it looked; it's actually its own project."*

This is a § 6 **escalation**, not an ordering call: starting a project-sized effort the wrong way (no plan, no operator visibility) is expensive-to-irreversible, so the orchestrator raises it through the structured-question path (`AskUserQuestion`, § 6) — *"this hits {N} of the § 3 criteria; shall I write a concept first?"* — rather than deciding silently.

**In-flight work is never discarded.** When the bar is crossed mid-implementation, the orchestrator snapshots whatever already exists into the new concept's *Approach* as "already built", moves it onto the first contributor branch, and only then escalates. (Cross-link § 7 on redirecting a sub-task and § 5.11 on re-evaluating after an event.)

#### 2. Write the concept — heavy or light, by a decidable rule

Which ticket format applies is **not** a judgement call:

- **Concept ticket (heavy template)** — used **iff the task meets ≥ 1 of the § 3 criteria**. Mandated sections:
  **Goal · Value · Approach · Acceptance criteria · Testability (unit / integration / harness) · Roadmap / Streams · Out of scope · Links.**
- **Feature ticket (light format)** — everything below the § 3 bar. Uses the `ENGINEERING_PRINCIPLES.md` § 2 issue format (Context · Acceptance criteria · Out of scope · Links). Do not apply the heavy template to small work.

Two requirements on the heavy template earn their own note:

- **Roadmap / Streams is part of the concept body**, written at concept-authoring time — this *is* the § 4 step 7 rule, surfaced here so the template satisfies it by construction. For a single-PR concept it may be a one-line "single PR, no parallel streams"; when the § 3 multi-PR criterion fires it carries the real dependency graph.
- **Testability names all three layers explicitly** (unit / integration / harness), per `ENGINEERING_PRINCIPLES.md` § 5, with the harness layer called out as the load-bearing one for AI-developed work. Where a real-system harness genuinely does not apply (a doc-only or pure-process concept), the section states **"harness N/A because …"** with an explicit justification — mirroring EP § 5's allowance that a piece may justify why unit/integration suffices. An unstated omission is a defect; a justified N/A is not.

#### 3. Adversarial gap-review — one independent pass

Before the operator spends any attention on the concept, the orchestrator has it reviewed by an **independent reviewer**: a *fresh sub-agent with no authoring-thread context*, briefed per § 5.3, tasked to **find gaps** — missing acceptance criteria, an absent or hand-wavy harness story, unstated assumptions, scope ambiguity, broken cross-references. The reviewer reports; the orchestrator applies corrections and records what changed.

**Both the findings and the corrections are recorded as comments** on the concept ticket, so the improvement trail is visible — not just the polished end state.

**One pass is the standing default.** The operator is the second set of eyes, so there is no reviewer-of-the-reviewer and no routine second round; corrections are recorded, not re-adjudicated. A **second independent round is a deliberate orchestrator choice, reserved for high-stakes or contested concepts** — empirically, a first round plus correction catches the substantive gaps, and a second round hits diminishing returns. Reach for it when the cost of a missed gap is high, not as routine.

#### 4. Hand the concept to the operator — always a clickable link

Only *after* the review-and-correct loop does the operator receive the concept, and always as a **clickable link to the checked-in artefact** — a GitHub issue, or a feature branch if the work is large enough to warrant one — never paraphrased into chat (§ 12.1). The operator reviews the already-gap-checked, already-corrected concept; their scarce attention goes to judgement, not proofreading. Implementation begins only after the operator approves.

---

## 4. Plan the parallelisation roadmap before spawning

Project-management 101: breadth-first planning precedes depth-first execution. The orchestrator's *first* action after activation is **not** to spawn a contributor — it is to decompose the project into a roadmap. Skipping this step and starting with "the first task that comes to mind" is the most common orchestrator failure; it costs the project days of wall-clock time by serialising work that could have run in parallel.

### Steps

1. **List the deliverables.** Read the concept ticket end-to-end; enumerate every concrete output (schema changes, code refactors, infrastructure adjustments, documentation updates). Group them by component boundary — same repo, same module, same feature stream.
2. **Identify dependencies — and distinguish task blockers from external blockers.** For each deliverable, name what must finish first. *Example dependencies:* a visual-regression baseline must exist before any refactor PR merges; a shared component schema must merge before content-types that consume it; a schema rename must merge before the code rename PR can be opened.
   - A **task blocker** is another sub-task in *this* roadmap that must complete first. It belongs in the dependency graph and gates when the blocked task can be spawned.
   - An **external blocker** is a real-world dependency outside the orchestration's scope (an upstream package not yet published, a third-party API not yet provisioned, a hardware delivery). It does **not** gate scaffolding: a sub-task can proceed against a pinned placeholder (e.g. a chart version pinned to the eventual `v0.1.0` tag, a stub endpoint) and ship a clean PR. Only the **end-to-end validation** of that work waits for the external dependency to materialise. Mark external blockers distinctly so they are not mistaken for task blockers that stall the spawn — a sub-task with only an external blocker is still a root task.
3. **Sketch the dependency graph in the concept ticket.** A checkbox list with grouping headers is enough — no fancy tooling needed. Surface three things:
   - **Critical path** — the longest chain of sequential dependencies; this is the project floor on duration.
   - **Parallel streams** — groups of deliverables that share no dependencies and can run simultaneously.
   - **Integration points** — deliverables that consume the outputs of multiple parallel streams.
4. **Use component boundaries as natural seams.** Code that lives in different repos (or different sub-modules with low coupling) can almost always proceed by independent contributors at the same time. The integration is whatever ties them at the seam — typically one consuming PR after both upstream PRs merge. Component-boundary parallelisation is the default, not the exception.
5. **Identify the root tasks explicitly.** A *root task* has no upstream dependencies — every prerequisite is either already done or doesn't exist. Mark these in the roadmap.
6. **First spawn batch is wide and includes every root task.** The orchestrator's opening round of sub-agents covers **every** root task at once, up to the WIP cap (§ 5.6). There is no good reason to hold a root task back; if it could start, it must start. Sequential spawning when parallel was possible is a planning failure — and a signal that step 3 was skipped.
7. **Roadmap goes in the concept ticket — in the concept body, at concept-write time.** Add an "Implementation roadmap" or "Streams" section to the concept ticket. Each sub-agent brief references the relevant stream so contributors see how their work composes with others'. **When a concept document exists, the roadmap is part of the concept's body, written during concept authoring — not bolted on as a separate comment at orchestrator-activation time.** The stakeholder then reviews the dependency graph and the WIP plan as part of the normal concept-review pass, and the orchestrator does not need to re-surface it later. A roadmap that appears only after the concept was approved means the stakeholder approved the *what* without seeing the *how it parallelises*.

### Why this is a hard rule

Without a roadmap, the orchestrator effectively executes the project depth-first: spawn one task, wait, spawn the next. This converts a project that could finish in days of parallel work into a project that takes weeks of serial work, and the cost is invisible to the stakeholder until it is too late to recover.

A roadmap step costs minutes; getting it wrong costs days. The cost-of-pause is always lower than the cost-of-not-pausing.

---

## 5. Mechanics: how the orchestrator runs the project

### 5.1 Concept ticket is the single source of truth

Every contributor reads the concept ticket — not the original conversation that produced it. If a contributor has a question the ticket cannot answer, that is a **concept-ticket defect**, not a contributor knowledge gap. Fix the ticket, then re-brief the contributor against the updated ticket.

The orchestrator is the only person who edits the concept ticket while work is in flight. Contributors append observations as ticket comments (or comments on sub-tickets), the orchestrator integrates those into the main body if they affect future contributors.

### 5.2 One branch per contributor — and a dedicated working tree per contributor

- Each contributor commits to their own feature branch (`feat/<scope>-<short-handle>`).
- Never two contributors on one branch.
- Never a contributor committing directly on the trunk branch.
- When two or more contributors operate against the same repo at the same time on the same workstation, **the orchestrator creates a dedicated `git worktree` per contributor** *before spawning the sub-agent*, and points the brief at that worktree as the contributor's working directory. Two AI sub-agents sharing one working tree silently corrupt each other's index — `git checkout` + `git add` cross-talk on `.git/index` is invisible until commits land on the wrong branch.

#### Workspace path: the orchestrator's first operator question

The orchestrator does **not** hard-code where the worktrees live. The location depends entirely on the workstation the orchestrator runs on (operator's laptop vs. CI runner vs. cloud sandbox). **First question of every orchestrator session that will spawn parallel sub-agents:**

> *"Where may I create sub-agent worktrees on this machine? A sibling directory next to the repo, the OS temp dir, a dedicated workspace path — your call."*

The operator's answer becomes `<WORKSPACE_TEMP_ROOT>` for the session. PMP does not pin it; `PROJECT_SPECIFICS.md` may optionally default it for a given workstation.

#### Per-contributor path convention

Inside `<WORKSPACE_TEMP_ROOT>`, every parallel sub-agent gets:

```text
<WORKSPACE_TEMP_ROOT>/<agent-slug>-<UTC-timestamp>/<repo>
```

- `<agent-slug>` — short kebab-case derived from the sub-task (e.g. `phase4-renderer`, `ciat-cleanup`).
- `<UTC-timestamp>` — `YYYYMMDD-HHMMSS`. Disambiguates retries; visible at a glance.
- Created via `git -C <main-checkout> worktree add <full-path> -b <feature-branch>` — share the parent's object DB, do not `git clone`.

The brief names the full path explicitly. A brief that says "work in `~/git/xmv/<repo>/`" while another sub-agent is also active in that repo is a § 5.2 violation by the orchestrator, even when both happen to finish cleanly that round.

#### Self-cleanup contract (mandatory on success and failure)

The hot-desking analogy: every agent gets a clean desk, leaves it clean, never operates on another agent's open desk. On completion, the agent runs:

```bash
git -C <main-checkout> worktree remove --force <full-path>
rm -rf <WORKSPACE_TEMP_ROOT>/<agent-slug>-<UTC-timestamp>
git -C <main-checkout> worktree prune
```

The brief restates the cleanup obligation near the top *and* near the bottom — long briefs tend to lose it otherwise. After every sub-agent completion event, the orchestrator confirms the temp dir is gone before marking the task done.

#### Detection signal and recovery

If `git status` in the main checkout shows uncommitted changes belonging to more than one feature-branch's scope, the isolation rule was violated and one of the in-flight agents is going to lose its work. The orchestrator stops, salvages, and re-spawns under the proper protocol.

For crash recovery (sub-agent died before cleanup), the template ships `scripts/orchestrator/recover-worktrees.sh` — it walks `<WORKSPACE_TEMP_ROOT>` + `git worktree list` and reports orphans + their last commit + uncommitted-file list, ready for orchestrator triage. Periodic orphan-sweep (`find <WORKSPACE_TEMP_ROOT> -maxdepth 1 -type d -mtime +1`) catches what the in-task cleanup missed.

#### Sub-agents inherit the orchestrator's working directory — this is a feature

A spawned sub-agent inherits the **orchestrator's** current working directory, not the target worktree's. So the principle files auto-loaded into the sub-agent's context (`AGENTS.md`, `PROJECT_MANAGEMENT_PRINCIPLES.md`, `ENGINEERING_PRINCIPLES.md`, `PROJECT_SPECIFICS.md`) are the ones at the orchestrator's location — which on a workspace-root orchestrator are the **canonical, freshest** copies.

This is the desired behaviour, not a bug to work around: it guarantees every sub-agent reads the current canonical principles and sidesteps any stale per-repo `AGENTS.md` drift. The reflex to `cd` into the target worktree before spawning would actually *hurt* — the sub-agent would then load that repo's possibly-older `AGENTS.md` instead of the canonical one.

The consequence for briefs: when a sub-task genuinely needs **project-specific** docs that live in the target repo (a repo-local `docs/`, a project's `.claude/skills/`, an `AGENT_LEARNINGS.md`), the brief must say so with an explicit `Read <path-in-target-repo>` instruction. Do not assume the sub-agent has loaded the target repo's docs just because its worktree lives there — it has not.

### 5.3 Contributor brief format

When the orchestrator hands a sub-task to a contributor, the brief contains three named parts and nothing else load-bearing:

1. **Mission** — one or two sentences, "what + why". Reference the concept ticket section that defines the deliverable.
2. **Constraints** — the rules that must be honoured: relevant principles from this file and `ENGINEERING_PRINCIPLES.md`, project-specific conventions from `AGENTS.md`, hard "do not touch" areas.
3. **Output specification** — what the contributor reports back, in what format, with what length cap. For AI contributors, also: open-questions limit (typically 2–3 max).

Briefs missing any of these three produce contributors who drift off-mission. The most common defect is a missing Output spec — the orchestrator can't integrate a report that has no agreed shape.

**Use the brief skeletons.** Hand-written briefs drift in shape across a session — fields get forgotten, the cleanup obligation from § 5.2 sometimes goes missing, the visibility rules from § 5.7 sometimes get paraphrased into uselessness. The repo ships two skeletons that the orchestrator fills in:

- [`templates/contributor-brief.md`](templates/contributor-brief.md) — the standard sub-task brief.
- [`templates/recovery-brief.md`](templates/recovery-brief.md) — for recovering an existing diff after a crash (trust-existing-diff + verify + push the open work; no fresh implementation).

If a brief has to deviate from the skeleton, that deviation is a deliberate orchestrator decision, not a forgotten field.

### 5.4 Contributors do not merge their own PRs

The orchestrator merges. This serialises convergence into trunk:

- When several contributors report a PR as ready at roughly the same time, the orchestrator decides the merge order.
- The orchestrator handles any rebases needed between branches (a later branch built on an earlier one's old base, two branches touching the same file).
- The orchestrator runs the merge themselves (`gh pr merge` for automated workflows; merge button in the web UI for humans), only after **a fresh CI run on the branch's head commit is green** at the moment of merge.

Letting contributors merge their own PRs in parallel produces merge-hell on trunk: conflicting commits land out of order, half-merges, broken trunk, rollback PRs. Orchestrator-serialised merges prevent that failure mode by design.

**Bundle-merge discipline.** When the orchestrator ends a phase with several PRs that need to land together (a "bundle"), the local validation comes *before* the first push of the merged tip — not after each individual PR. Concretely: rebase the bundle onto trunk locally, run the full local ladder (lint, unit, integration, harness — see [`ENGINEERING_PRINCIPLES.md` § 5](ENGINEERING_PRINCIPLES.md)) on the combined tip, fix everything that surfaces *locally*, then push and merge. Iterating "fix the first failure, push, watch CI fail on the second, push again" is the most expensive recovery shape: it converts one local round into N CI rounds at N× the wall-clock and N× the metered cost. The orchestrator owns this — contributors deliver branches; the orchestrator integrates and validates before push.

### 5.5 PR-readiness is the contributor's responsibility

The contributor delivers a branch that meets the project's PR discipline (see `ENGINEERING_PRINCIPLES.md` § 13): CI green, tests green, docs updated, conventional-commit messages. The orchestrator's role is to **verify** this is true at the moment of merge — not to fix the branch up afterwards. A branch that arrives not-ready is sent back with a specific list of what's missing.

### 5.6 WIP limit on parallel contributors

Even with parallelisation as the default (§ 4), the orchestrator caps how many sub-tasks are in flight at once. Each in-flight contributor needs a slice of the orchestrator's attention to integrate when ready, to escalate when blocked, and to stop when drifting. Too many at once and the orchestrator becomes the bottleneck, with contributors finishing into a queue.

**Practical default: 5 parallel sub-agents.** Tighter than that risks under-utilising the parallelisation surface; looser invites coordination overload. Adjust by gut-feel for the project shape — heavily independent sub-tasks tolerate higher WIP; heavily-converging sub-tasks (lots of integration PRs) need lower WIP.

When more than 5 deliverables are parallelisable, the orchestrator picks the next 5 by dependency-graph distance (deliverables closer to the critical path go first) and queues the rest. A finished sub-task triggers the next one off the queue.

This is the Kanban WIP-limit principle adapted: in-flight count is bounded, the queue is explicit, and throughput is paced by the integration capacity rather than the spawn capacity.

### 5.7 Sub-task budget and progress visibility

AI contributor sub-agents are not architecturally able to send mid-task heartbeats the way a human developer joins a daily stand-up. They run uninterruptibly until they decide they are done, and they can disappear into rabbit holes silently. The orchestrator's defence against this is **structural**, baked into the brief itself:

- **Hard wall-clock budget per sub-task.** State it in the brief (typically 30 minutes for a focused task, up to 60 minutes for setup-heavy work). If the contributor cannot deliver within the budget, the brief explicitly instructs it to STOP and report current progress + blockers + next-step options. The orchestrator then decides whether to extend, hand off, or replan.
- **Early-PR rule.** The contributor opens a *draft* PR after its first commit, even if the work is far from complete. The draft PR is the orchestrator's visibility window — without an open PR the orchestrator cannot tell whether the contributor is making progress, stuck, or lost. Late PR-opening hides rabbit-hole risk for hours.
- **3-iteration rule.** If the contributor hits the same tool failure or test failure three times without progress, it STOPs and reports. No looping on the same problem.
- **Mandatory Output-specification fields.** § 5.3's Output spec is not optional padding. Every field listed is required — the contributor delivers all of them or its report counts as the rabbit-hole signal in itself. (A one-line "still working on it" report is a brief-format violation, not an acceptable check-in.) A common contributor mistake: treating "CI is still running" as a reason to defer the report. **CI status is one of the Output fields, not a reason to skip the others.** Always report all fields *now* with CI marked as `in_progress` if that's the truth — never defer the whole report waiting for CI to finish, because the runtime may reap the contributor before CI completes and the report is then lost.
- **Optional orchestrator-side polling.** When the budget is long or external (waiting on CI, on a deployment, on a remote queue), the orchestrator can run a `/loop` poll every 15–30 minutes that checks for observable progress (new PR opened, new commits on a known branch, new ticket comments). This is the *orchestrator's* concern, separate from the contributor's heartbeats.
- **Phase the brief around blocking commands; commit between phases.** Sub-agent runtimes have stream-idle timeouts (~6 minutes on common agent harnesses). Any single command that can block longer than that — `npm ci`, a Docker build, a slow test suite — is the boundary of its own phase. Each phase ends with `git add + commit + push` so the next agent (after a timeout-kill or any other crash) inherits a complete checkpoint of what was already done. The brief states phases explicitly; the contributor commits + pushes between them. The guiding heuristic: **what's on disk after I die is what the next agent inherits** — leave it in a useful state.

Together these four rules — budget, early PR, 3-iteration cap, mandatory output fields — give the orchestrator visibility-by-design without needing an architectural feature that the AI sub-agent runtime does not provide.

#### The contributor's "Open questions" field is the orchestrator's cross-task radar — scan it before every merge

§ 5.3's Output spec mandates an "Open questions" field (typically 2–3 max). That field is not a courtesy — it is the single channel through which a scope-limited sub-agent surfaces something that touches **another** stream the orchestrator is coordinating. A contributor sees only its own slice; the orchestrator sees the whole graph. A path the contributor flags as "is this where the secret lives?" may be exactly the file a *parallel* sub-task just changed.

Therefore: **the orchestrator MUST read every sub-agent report's "Open questions" section before merging that contributor's PR**, and treat any cross-task implication as a blocking pre-merge action item — resolved in the worktree and re-pushed, not deferred. Skipping this scan converts a cheap pre-merge fix into a defect that only surfaces when the integrated system runs the affected path, possibly weeks later. (Observed: a sub-agent's open-question flagged a path mismatch with the orchestrator's own in-flight work; caught and patched pre-merge precisely because the early-draft-PR + open-questions discipline surfaced it in time.)

See § 11 for the full mapping between this file's rules and the Scrum / Kanban patterns they adapt.

### 5.8 Harness validation is the orchestrator's job, not the contributor's

Sub-agents implement and unit-test their own work but do **not** run the project's harness-stage tests themselves. Reasoning:

- The harness is a shared resource. Multiple concurrent contributors hitting it produce false positives and false negatives that nobody owns.
- Harness validation needs a coherent system state. Typically one half of a multi-repo change is merged and the other is not — only the orchestrator knows which combinations are already integrated.
- Harness testing is integration-level work. The contributor's brief was scope-limited to its own component; widening it to integration responsibilities invites scope creep.

The orchestrator runs harness validation:

1. After a self-contained sub-task lands — does the system still bootstrap?
2. After multiple parallel sub-tasks merge and form a coherent slice — does the slice work end-to-end?
3. Before proposing a higher-stage deployment (see § 5.9).

### 5.9 Stage deployment authority

| Stage | Authority |
|---|---|
| Harness | **Orchestrator owns.** Spin up / tear down / smoke at will. No operator confirmation needed. |
| Dev | **Operator approval required.** When a coherent integrated slice is ready, the orchestrator pings the operator: *"I'd like to deploy this to Dev for review — OK?"* Operator decides. |
| Pre | Same as Dev. |
| Prod | Same as Dev — plus the operator typically runs customer-facing cutovers personally (DNS flips, release announcements), per project-specific convention. |

The orchestrator does **not** push to a non-Harness stage on its own initiative, even when CI is green and the harness is happy. The operator is the customer-facing release authority; the orchestrator is the integration coordinator.

#### Merging to `main` is not a stage deployment — do not gate it on operator approval

The table above governs **stage deployments** (shipping a built artefact to Dev / Pre / Prod), not **merges to trunk**. These are different acts, and conflating them is a real failure mode: an orchestrator that reads "Dev needs approval" as "every merge needs approval" stalls the whole project asking permission to click the merge button.

Merging an in-scope, CI-green, PR-disciplined branch into `main` is routine integration work — the operator's approval at orchestration *activation* (§ 3) already covers it. This is especially clear for **pre-MVP repositories** (no `v0.1.0` released, no customer-deployed instance): there, `main` is dev-equivalent — a merge has no customer-facing consequence, so there is nothing to gate. The orchestrator merges and keeps moving.

The Pre / Prod stage authority in the table above starts to bite once a **tagged release has shipped to customers** — from that point a merge to `main` can flow toward a customer-visible artefact, and the deployment of that artefact (not the merge itself) is what needs operator approval. Until then: merge freely within the approved scope. (This is the integration-side companion to § 6's rule that pure ordering is the orchestrator's call — both exist to stop the orchestrator idling on a decision that was already delegated.)

### 5.10 Increment presentation cadence

When parallel sub-tasks land and form a **coherent slice** that a stakeholder could meaningfully review (e.g. a CMS schema change + the matching website rendering — both merged, harness-validated), the orchestrator proactively pings the operator:

*"Increment N is ready: [one-line summary of what it covers]. Suggest a Dev deployment for review."*

This matches the human-team practice of presenting increments at a Sprint review cadence. AI projects benefit from the same rhythm — without it, the operator sees only individual PRs and never the integrated whole. The orchestrator's judgement on *when a slice is coherent enough to present* is part of the project-management responsibility, alongside the roadmap (§ 4) and the WIP cap (§ 5.6).

A slice is **not** coherent when one half of a paired change has landed and the other is still in flight (e.g. CMS schema renamed but website code still using old names). The orchestrator delays the increment-presentation ping until the pair closes.

### 5.11 Continuously re-evaluate the dependency graph after every event

Every completion event — a sub-agent reporting back, a PR merging, a CI job turning green, a stakeholder unblocking an escalation — must immediately trigger the orchestrator's default question:

> *"Which previously-blocked tasks are now unblocked, and which root tasks have I not yet started?"*

The default action after a notification is **not** "wait for the next stakeholder prompt" — it is "scan the task list, find the newly-startable work, spawn it up to the WIP cap". A task whose `blockedBy` is now satisfied but that is still sitting in pending state is a planning gap.

Operationally:

- After every sub-agent report: scan `TaskList`, identify newly-unblocked tasks, spawn them up to the WIP cap (§ 5.6).
- After every PR merge: same scan — merges often unblock downstream content-type refactors, follow-up website-code PRs, integration phases.
- After every stakeholder answer to an escalation: re-spawn the blocked sub-agent immediately with the answer baked into its brief.

The WIP cap bounds how many *spawn at once*. It does **not** bound which tasks are *eligible* — those are determined purely by the dependency graph. Hold-back of eligible work without an explicit reason is the failure mode this principle exists to prevent.

**Session-start stale-sweep.** Before producing any new work in a fresh orchestrator session, validate every task currently marked `in_progress` (or its equivalent on whatever tracker the project uses) that is older than 24 hours. For each: is the underlying issue still relevant, is the owner still active, has it silently completed elsewhere? Flip the status to match reality, then start producing. Skipping this step lets stale entries pollute the orchestrator's worldview for the rest of the session — a parallel-graph re-evaluation against a wrong baseline.

### 5.12 Heartbeat to the stakeholder

The orchestrator pings the stakeholder every **15 minutes** while a project is active, with one of three short status lines, **in whichever language the stakeholder uses with the orchestrator** (the orchestrator picks the language up from the conversation; it is not pinned in this document):

1. **"Still working"** — short note on what's currently in flight and what just merged, no decisions needed.
2. **"At a standstill"** — nothing is in flight and nothing can usefully be spawned without input; the orchestrator is idle.
3. **"Open question blocking stream X — please answer:"** — the orchestrator has hit an escalation that must reach the stakeholder before that stream can continue.

One sentence per status line — § 12 (communication brevity) applies. The heartbeat exists so the stakeholder does not have to ask "what's the status?" — they get a regular passive check-in and only have to engage when the orchestrator surfaces case 3.

**Lifecycle.** The orchestrator starts the heartbeat loop when the project enters active orchestration mode (after the § 3 stakeholder approval) and stops it when the project ships or the stakeholder explicitly pauses the project. On `/loop`-capable runtimes the heartbeat is a 15-minute self-triggered prompt that reads ticket / PR / sub-agent state and posts the one-liner. On runtimes without `/loop`, the orchestrator structures its main-thread cadence around the same 15-minute beat manually.

The heartbeat is **not** a substitute for § 5.7 sub-agent visibility rules — it is the orchestrator's own stand-up to the stakeholder, complementing the contributor-side budget+early-PR+iteration mechanics.

**Stop repeating an unchanged beat — propose pausing instead.** A heartbeat that fires the *same* status with the *same* content several times running is noise, not information: it trains the stakeholder to ignore the channel. When the status has been **"Still working" or "At a standstill" with unchanged content for 3+ consecutive fires**, the orchestrator proposes pausing the heartbeat ("nothing has changed in 45 min; I'll pause the beat and resume it when state changes — say the word to keep it running"). When the status has been **"Open question" with no stakeholder response for 3+ fires**, re-pinging the same question does not raise the odds of an answer — propose pausing rather than repeating, and rely on the structured-question notification (§ 6) to have already pushed the ask. On `/loop`/cron runtimes this means editing the loop prompt to auto-propose the pause after the third same-state fire, not silently continuing.

#### STATUS block: the searchable surface alongside the heartbeat ping

The heartbeat ping is ephemeral chat. The orchestrator additionally maintains a **persistent STATUS block** in the concept ticket (a dedicated `### Status` section, or a stable comment that gets edited in place — whichever the tracker supports cleanly). The stakeholder ctrl-Fs the concept ticket; the chat heartbeat is the prod, the STATUS block is the surface.

The STATUS block carries **two clearly separated lists**:

- **Ours — in flight.** Each in-flight sub-agent: slug, branch, expected PR title, current phase. These count toward the WIP cap (§ 5.6).
- **Waiting on downstream / external.** Each item: what we are waiting on, link to the upstream artefact (PR, ticket, deployment, vendor case), expected trigger or date. These are **explicitly out of the WIP count** — they consume no orchestrator attention until the trigger fires.

Conflating the two — "we are blocked, we are working" mashed together — is exactly the failure mode this principle exists to prevent. The stakeholder must be able to tell, at a glance, what we are doing vs. what we are waiting on.

The STATUS block is updated after every § 5.10-class increment (and at minimum once per heartbeat tick if anything changed). Stale STATUS is a § 5.11 stale-sweep target.

---

## 6. Escalation: contributor → orchestrator → stakeholder

Contributors do not talk to the stakeholder while work is in flight. They talk to the orchestrator. The orchestrator decides whether the question can be answered from the concept ticket / existing project context, or whether it needs to escalate to the stakeholder.

When escalating:

- Frame the question with full context (the contributor doesn't have to see it).
- Offer the stakeholder a small number of concrete options (A/B/C) where possible, with a clear recommendation.
- Once answered, update the concept ticket if the answer has implications beyond the immediate question.

This protects the stakeholder from being flooded with low-level technical detail, and protects contributors from interpreting stakeholder responses out of context.

### Ordering questions are not stakeholder decisions

Serialising work is the orchestrator's own job (§ 2). If the only thing unclear is *"which of these N already-approved tasks do I do first?"*, the orchestrator decides — by any reasonable heuristic (smallest first, blocker-unblocking first, most-likely-to-fail first, or an arbitrary tiebreak) — and **never blocks on the stakeholder for it**.

The arithmetic is one-sided: the expected wait on a synchronous stakeholder reply is typically hours (they are offline, in a meeting, asleep), while the regret cost of a sub-optimal order is typically minutes (a task lands in position 3 instead of 1). Whenever the wait dominates the regret — which is almost always for pure ordering — the orchestrator absorbs the regret and keeps moving. A project that idles for two hours waiting for "which first?" has already paid more than every possible wrong-order penalty combined.

The orchestrator **must** still escalate (and therefore may block) when the question is *not* pure ordering:

- **Architectural decisions** — Option A vs Option B with real, hard-to-reverse trade-offs.
- **Scope changes** — adding, cutting, or reshaping a deliverable.
- **Customer-visible cutover timing** — anything the stakeholder runs personally or announces externally.
- **Anything irreversible** without an obvious, cheap undo.

The test: *"if I guess and I'm wrong, what does it cost to correct?"* Cheap-to-correct (reordering, a redo of minutes of work) → decide yourself. Expensive-or-impossible-to-correct → escalate.

### When you do ask, ask through the notification path

A question that must reach the stakeholder is raised with the `AskUserQuestion` tool (or whatever the runtime's push-notification-backed question mechanism is) — **not** as plain prose buried in a status update. Plain-text questions disappear into the conversation log; the stakeholder only sees them on their next manual check, which reintroduces the very hours-long stall the ordering rule exists to kill. The structured-question path pushes a notification, so the stakeholder is actually prompted. State the options (A/B/C) and the recommendation per § 12.

---

## 7. Stopping a sub-task that drifts

The orchestrator owns the decision to stop a contributor that is not delivering — a sub-task that has expanded scope beyond the brief, a contributor that keeps hitting the same tool failure, an AI sub-agent caught in a rabbit hole.

The mechanic depends on the contributor type:

- **Human contributor** — a one-on-one conversation: "this sub-task isn't converging; let's reset what we're trying to deliver".
- **AI sub-agent** — `TaskStop` the agent, revise the brief or the concept ticket, re-spawn with the corrected brief.

The cost of letting a drifting contributor continue is always higher than the cost of stopping them early. The orchestrator should err on the side of stopping sooner.

---

## 8. Lessons-learned capture

The orchestrator pattern improves with use. Every project that runs it leaves observations that the next project should benefit from.

The capture format (append to the project's lessons-learned issue or the trial-tracking ticket, see § 10):

- **Sub-task brief that produced a clean outcome** — what made it work, what to copy next time.
- **Sub-task brief that needed re-issuing** — what was missing in the first version.
- **Merge-conflict between parallel branches** — how it was resolved, whether the brief could have prevented it.
- **Stakeholder escalation** — what was asked, how long the orchestrator was blocked waiting, whether the question could have been pre-empted by a clearer concept ticket.
- **Contributor stopped early** — what signals triggered the stop, in retrospect was it the right call.

A retrospective at the end of the project consolidates these into improvements to this file (back-ported per § 0).

The roadmap from § 4 is also a lessons-learned target — when the initial roadmap turns out to have missed a parallelisation opportunity or invented a spurious dependency, that's a learning that improves future roadmaps. Capture those alongside the contributor-level observations above.

**Status-tracking of PMP-affecting learnings.** Once a learning is identified, file it as a *sub-issue* under the project's trial-tracking ticket (§ 10 "Trial-and-rollout convention") with the label `pmp-feedback`. The sub-issue body lists the observation + the proposed canonical § that should encode it. When the rule actually lands in this document, close the sub-issue with a closing-comment that names the canonical PMP version + § + gist commit. This turns the lessons-learned audit trail into a clean open-vs-closed status surface — the stakeholder sees at a glance which learnings have been absorbed and which still float as chat comments.

---

## 9. Anti-patterns

These have been observed in practice. They are the failure modes this file exists to prevent.

- **Skipping the parallelisation roadmap (§ 4).** Spawning the first sub-task that comes to mind without first listing deliverables, dependencies, and the dependency graph. Converts a parallelisable multi-stream project into a serial one, costing days of wall-clock time invisibly. The most common orchestrator failure; always do § 4 first.
- **Leaving root tasks unstarted (§ 4 step 6).** A task with no upstream dependencies sits in pending state while the orchestrator works on something else. There is no orchestration reason to hold a root task back; if it could start, it must start. The opening spawn batch covers *every* root task.
- **Waiting between events instead of re-evaluating (§ 5.12).** A sub-agent reports done, a PR merges — and the orchestrator does nothing until the next stakeholder prompt. The default action after every notification is "scan the graph, spawn newly-unblocked work", not "idle until poked".
- **Sub-task brief without time budget, early-PR rule, or output spec (§ 5.7).** The contributor disappears silently for hours and the orchestrator only notices when the runtime returns the agent terminated with no output. By the time you see it, the project's wall-clock has lost the duration of the wasted run. Bake the four visibility rules into every brief.
- **No WIP limit on parallel contributors (§ 5.6).** The orchestrator spawns more sub-agents than it can integrate; finished branches queue waiting for merge attention while the orchestrator is still briefing new ones; coordination latency drowns the parallelisation gain. Pick the WIP cap before the wide spawn batch (§ 4.5), not during.
- **Contributor running harness tests (§ 5.8).** A sub-agent runs the project's harness suite mid-task; the harness's shared state corrupts; concurrent contributors get false signals. Harness validation is the orchestrator's responsibility, always.
- **Orchestrator deploying to Dev / Pre / Prod without operator approval (§ 5.9).** The release authority is the operator. Even with CI green and harness happy, the orchestrator pings and waits.
- **Gating a routine merge on operator approval (§ 5.9).** The mirror image of the above: the orchestrator reads "Dev needs approval" as "every merge to `main` needs approval" and stalls the project asking permission to click the merge button — especially wrong on a pre-MVP repo where `main` is dev-equivalent and a merge has no customer-facing consequence. Merging an in-scope, CI-green, PR-disciplined branch is routine integration the activation approval already covers. Stage deployment ≠ trunk merge.
- **Silent integration without presentation (§ 5.10).** A coherent integrated slice lands, the orchestrator merges it and moves on to the next phase without showing the operator. The operator never sees the integrated whole, only the individual PRs — and only notices regressions at the final ship gate. Always proactively offer a Dev deployment when the slice becomes presentable.
- **Skipping the stakeholder-confirmation step.** Activating orchestrator mode without asking. The stakeholder may have wanted direct main-thread control; assuming wrong costs hours of misaligned work.
- **Implementing a project-sized task with no concept (§ 3.1).** A handed task quietly grows past the § 3 bar and the orchestrator keeps coding inline — no concept, no plan, no operator visibility. By the time it surfaces, days of unreviewed work have to be reverse-engineered into a plan. Assess size on every task and reassess mid-task; the moment the bar is crossed, stop and escalate a concept-first.
- **Operator review before the concept was gap-checked (§ 3.1).** The orchestrator sends the operator a raw concept, so the operator's scarce attention is spent finding holes a sub-agent should have caught. Always run the one independent adversarial review and apply corrections *before* the operator sees it; the operator reviews judgement, not typos.
- **Contributor merges its own PR.** Race condition with the next contributor's PR touching the same files; merge-conflict storm; trunk broken; concept ticket falls out of sync. Always orchestrator-merges.
- **Spawning contributors without a concept ticket.** Each contributor reinvents the goal slightly differently. Results don't compose. Fix the concept ticket first; spawn second.
- **Two contributors on the same working tree without an orchestrator-prepared worktree split (§ 5.2).** They overwrite each other's uncommitted state silently. The orchestrator must run `git worktree add` *before* spawning parallel sub-agents that touch the same repo, and bake the worktree path into the brief — not leave the contributor to discover the conflict and fix it mid-task.
- **Sub-agent worktree without self-cleanup (§ 5.2).** The agent ships its PR but the temp directory lingers; the orchestrator's next session inherits an orphan tree and misreads it as in-flight work. Self-cleanup on success *and* failure is mandatory; the orchestrator confirms the dir is gone before marking the sub-task complete.
- **Phase-less brief on long blocking commands (§ 5.7).** The brief tells the sub-agent to "implement feature X and ship a PR" without breaking the `npm ci` / build / long-test boundary into its own phase. The runtime's stream-idle timeout kills the agent mid-install; nothing is committed; the next agent inherits an empty branch and re-does the same install, hitting the same timeout. Always phase the brief and require checkpoint commits between phases.
- **Hand-written briefs across a session (§ 5.3).** Each new sub-task gets a freshly-typed brief; fields silently drift; the cleanup obligation or the visibility rules go missing in one of them, and that one sub-agent disappears into a rabbit hole the others were protected from. Use the [`templates/contributor-brief.md`](templates/contributor-brief.md) skeleton; deviations are deliberate, not accidental.
- **CI-iteration spiral on bundle-merge failures (§ 5.4).** A merged tip fails CI; orchestrator fixes the first error, pushes, watches CI fail on the second; pushes again, fails on the third. Each round burns a metered CI minute and several minutes of wall-clock the orchestrator could have spent producing. Run the full ladder locally on the combined tip *before* the push; fix all failures together; push once.
- **Stale `in_progress` tasks ignored at session start (§ 5.11).** The orchestrator resumes a project after a break, sees several `in_progress` entries from the prior session that are no longer accurate, and produces new work against that wrong baseline. Always stale-sweep before producing.
- **Conflated STATUS surface (§ 5.12).** "We are blocked on X and also working on Y" is one bullet in the heartbeat; the stakeholder cannot tell whether they need to do something. Maintain the two-list STATUS block with `Ours — in flight` and `Waiting on downstream / external` strictly separated; downstream blockers do not consume WIP.
- **Long-running external polling inside a sub-agent.** AI sub-agents have lifetime limits; they time out on hour-long polls. Use event-driven waits (`Monitor`-style tools) and reserve sub-agents for bounded work that produces a concrete output within their lifetime.
- **Vague brief.** Mission stated, constraints implicit, output spec missing. Contributor produces something plausible but unintegrable. Always include all three named parts.
- **Sub-agent talking to the stakeholder directly.** The stakeholder sees a low-level technical question without project context; answers it out of context; the answer makes it into the contributor's work; later it turns out to mean something different in the bigger picture. Always route through the orchestrator.
- **Pausing on a pure ordering question (§ 6).** The orchestrator has N already-approved, independently-doable tasks and stalls the whole project asking the stakeholder "which one first?" The stakeholder is offline for hours; the wrong-order penalty would have been minutes. Ordering is the orchestrator's own job — decide by any reasonable heuristic and keep moving; only escalate questions that are expensive or impossible to undo.
- **Merging without scanning the contributor's "Open questions" (§ 5.7).** The orchestrator merges a sub-agent's PR without reading its open-questions field, where the contributor flagged something touching a parallel stream. The cross-task implication only surfaces when the integrated system runs the affected path — weeks later, far more expensively than the pre-merge fix would have cost. Always scan open-questions before merging; treat cross-task flags as blocking pre-merge action items.
- **Treating an external blocker as a task blocker (§ 4 step 2).** A sub-task depends on a real-world dependency outside the orchestration (an unpublished upstream package, an un-provisioned API) and the orchestrator holds the *whole* sub-task back, idle, until it materialises. Scaffolding can proceed against a pinned placeholder and ship a clean PR; only end-to-end validation waits. A sub-task with only an external blocker is still a root task.
- **Repeating an unchanged heartbeat (§ 5.12).** The beat fires the same "still working" / "at a standstill" / unanswered-open-question content several times running. It trains the stakeholder to ignore the channel. After 3+ identical fires, propose pausing the beat and resuming on state change — do not keep emitting noise.
- **Burying a real question in prose instead of the notification path (§ 6).** When the orchestrator *does* need a stakeholder decision, it writes the question as a sentence in a status update rather than via `AskUserQuestion`. No notification fires; the stakeholder sees it only on their next manual check — which is the same hours-long stall the ordering rule exists to prevent. Genuine questions go through the structured push-notification path, with options and a recommendation.
- **Letting a drifting contributor continue.** "It might still work." It won't. Stop, revise, re-issue.

---

## 10. Document layout: principles, specifics, entry points

The same five files exist in the same places across every repo, so a contributor jumping between projects sees an identical surface and learns the layout once.

| File | Project-agnostic? | Purpose |
|---|---|---|
| `ENGINEERING_PRINCIPLES.md` | **Yes — identical in every repo** | How the work itself is done: test layers, source-control hygiene, PR discipline, SPDX headers, licensing, documentation baseline |
| `PROJECT_MANAGEMENT_PRINCIPLES.md` (this file) | **Yes — identical in every repo** | How the work is coordinated: orchestrator role, contributor briefs, serialised merges, escalation, lessons-learned, communication brevity |
| `AGENTS.md` | **Yes — identical in every repo** | Tool-agnostic AI-agent brief: reading order, behaviour rules, references to the other files, the pointer toward optional `PROJECT_SPECIFICS.md` |
| `PROJECT_SPECIFICS.md` | No — different per repo, **optional** | Tech stack, repo or subproject map, environment URLs, cluster hostnames, mailbox addresses, project glossary, project-specific overrides of the engineering baseline |
| Tool-specific pointers (`CLAUDE.md`, `.cursor/rules/*.mdc`, `.github/copilot-instructions.md`, `CONVENTIONS.md`) | **Redirect identical in every repo; an optional repo-local tool-specific section below it is permitted** | A redirect to `AGENTS.md` so each tool's auto-load convention reaches the same canonical brief, plus — where needed — a genuinely tool-specific convention captured below the redirect |

### Why AGENTS.md is project-agnostic

A maintainer running several projects benefits when AGENTS.md improvements propagate by file replacement, not by careful per-project merging. Anything project-specific that used to live in AGENTS.md (project facts, tracker URL, tech stack, override list, environment-specific test commands) moves into `PROJECT_SPECIFICS.md`.

`AGENTS.md` references `PROJECT_SPECIFICS.md` in its reading order with explicit *"optional, if present"* wording — projects that need nothing beyond the three principle files simply omit `PROJECT_SPECIFICS.md`.

### Reading order for a new contributor

1. `ENGINEERING_PRINCIPLES.md` — how we work (project-agnostic)
2. `PROJECT_MANAGEMENT_PRINCIPLES.md` — how we coordinate (project-agnostic)
3. `AGENTS.md` — entry point for AI agents (project-agnostic)
4. `PROJECT_SPECIFICS.md` if present — project-specific facts and overrides
5. Project-specific documentation (`README.md`, `docs/app-concept.md`, …) — referenced from `PROJECT_SPECIFICS.md` when it exists, or read directly when it doesn't

### Tool-specific entry pointers

Some AI tools auto-load a tool-specific file from the working directory; others auto-load `AGENTS.md`. For maximum tool-portability, every repo gets minimal tool-specific pointer files whose primary content is a redirect to `AGENTS.md`:

- `CLAUDE.md` — Claude Code auto-loads this reliably; without it, `AGENTS.md` is not guaranteed to be picked up on session start (auto-discovery exists in newer Claude Code versions but is not yet a fleet-wide guarantee)
- `.cursor/rules/agents.mdc` (or `.cursorrules` for older Cursor) — Cursor's equivalent
- `.github/copilot-instructions.md` — Copilot's equivalent
- `CONVENTIONS.md` — Aider's equivalent

The redirect is the same in every repo, so the pointers propagate by file copy. The real content lives in `AGENTS.md` (and from there in the principle files and optional `PROJECT_SPECIFICS.md`); the pointers exist so each tool reads the same canonical brief regardless of its auto-load convention.

**Optional repo-local exception.** A pointer file *may* carry a genuinely tool-specific convention **below** the redirect — something that exists in one tool and no other (e.g. a Claude-Code-only slash-command pattern). This is the one permitted deviation from "identical in every repo": the redirect stays uniform, the tool-specific addition is repo-local. Anything that is *not* tool-specific (project facts, general agent behaviour) does not belong here — it goes in `PROJECT_SPECIFICS.md` or `AGENTS.md`. Keep such additions rare; a pointer that grows its own briefing has stopped being a pointer.

### Trial-and-rollout convention

When this file (or any change to it) is being trialled on a real project before being rolled out workspace-wide, the trial is tracked by a dedicated issue in whichever repo carries the most cross-cutting weight (typically the workspace's central infrastructure repo). The trial issue captures lessons-learned per § 8, and the back-port to all repos happens only after the trial validates the new shape.

**Lessons-learned tracking on the trial issue.** Comments on the trial issue grow quickly and become hard to scan as "what is still open vs already integrated". The convention is:

- **One sub-issue per distinct learning**, labelled `pmp-feedback`. Title: `PMP feedback: <one-line description>`. Body contains `Parent: #<trial-issue>` plus two sections — *Observed* and *Captured in PMP* (which §).
- **Issue state is the integration status.** Open = observed, not yet integrated into this file. Closed = integrated; the closing-comment references the canonical PMP version + § + gist commit.
- **Comments on the trial issue remain the discussion surface**; sub-issues are the audit trail of which observations actually closed the loop into the principles document.

A retrospective at project end consolidates open `pmp-feedback` issues into a final PMP revision; closed issues remain as historical record of how the rules evolved.

---

## 11. Inspirations from Scrum and Kanban (what adapts, what drops)

The rules above borrow heavily from human-team project management. Explicit mapping so a contributor familiar with those frameworks recognises the shape:

- **Sprint planning** → § 4 (parallelisation roadmap before any sub-agent spawns).
- **Sprint goal** → the concept ticket. The orchestrator does not reshape the goal mid-project without escalating.
- **Daily stand-up** → § 5.7 (budget + early-PR + 3-iteration rule as a structural substitute, because AI sub-agents cannot literally stand up mid-task and report).
- **Definition of Ready** → § 5.3 brief format. A sub-task is ready to spawn only when Mission + Constraints + Output-specification are all written down.
- **Definition of Done** → § 5.5 + `ENGINEERING_PRINCIPLES.md` § 13 (CI green, tests green, docs updated, conventional commits, no `(TBD)` markers without a follow-up issue).
- **WIP limit** → § 5.6. Cap on in-flight parallel contributors so the orchestrator does not become the integration bottleneck.
- **Integration testing ownership** → § 5.8. The orchestrator owns harness validation; contributors own only their own component's unit/integration coverage.
- **Sprint review / increment demo** → § 5.10. When a coherent slice is integrated, the orchestrator pings the operator and proposes a Dev-stage deployment for review. Stakeholder authority over Dev / Pre / Prod stages per § 5.9.
- **Retrospective** → § 8 lessons-learned, both per-task (continuous) and end-of-project (consolidated).
- **Burndown** → the project's TaskList (or equivalent ticket grouping). Each phase completing closes its tracked task. The orchestrator does not draw burndown charts; it reads task status.

What drops:

- **Velocity points / story-pointing** — sub-tasks are too heterogeneous to estimate uniformly. The budget + iteration cap from § 5.7 replaces the need for a points-based forecast.
- **Pair programming** — AI sub-agents cannot meaningfully pair (they cannot mid-task converse). Use one sub-agent per task and let the orchestrator review the output.
- **Team-building / career-development rituals** — no team morale axis, no growth axis. Drop entirely.

This list is intentionally short and stays so. The Scrum framework as a whole assumes a human team; only the rituals that survive the "what is this ritual *for*" test in an AI-contributor context are kept above.

---

## 12. Communication brevity

When the orchestrator asks the stakeholder a question (the heuristic confirmation in § 3, an escalation per § 6, a layout choice, anything else), keep it short.

- One or two sentences for the question itself.
- Name the option set if there is one (A/B/C).
- State the recommendation if there is a defensible one.
- **Do not pre-emptively explain the reasoning** unless explicitly asked. The stakeholder can ask "why?" if they want it; in practice they will more often want to answer and move on.

Verbose justifications dominate the stakeholder's attention. They convert what should be a one-line confirmation into a paragraph of reading, and they tend to signal that the orchestrator is not confident in the recommendation. A short question + a short recommendation + an opt-in expansion ("can elaborate if needed") is the right shape.

The same brevity applies symmetrically to contributor briefs (§ 5.3): keep the brief itself tight — mission, constraints, output spec in one sentence each where possible. Verbosity in briefs makes contributors drift toward what they think the orchestrator wants to read, not what they need to deliver.

### 12.1 Link artefacts; do not paraphrase them

When the orchestrator surfaces an artefact (a PR, an issue, a gist, a CI run, a deployment URL, a generated file), the chat message links to it as a clickable markdown reference and stops there. The orchestrator does not paraphrase the artefact's content into chat — the stakeholder opens the link if they want the detail, and the artefact remains the canonical source of truth.

Paraphrasing artefacts into chat duplicates content, lets paraphrase + artefact drift apart, and pollutes the stakeholder's attention with information already available at a click. A link is one line; the paraphrase is many.

### 12.2 Open questions: one line in chat, detail in the linked concept

When the orchestrator escalates an open question (§ 6), the chat message contains: the one-sentence question + the recommended option + a markdown link to the concept ticket / PR / file where the full detail lives. The stakeholder reads the one line, opens the link if they want the why, and answers.

Long-form context inlined into the chat is the wrong shape: it makes the stakeholder scroll, hides the actual question, and the context inevitably differs from what the concept document says — the concept then becomes a stale duplicate. The concept document is the authoritative context; chat is the conversation about it.
