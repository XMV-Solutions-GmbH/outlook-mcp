<!--
SPDX-License-Identifier: MIT OR Apache-2.0
SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
SPDX-FileContributor: David Koller <david.koller@xmv.de>
-->

# 0004 — Keep the harness credential alive with a scheduled run, not with secret write-back

- **Status:** Implemented
- **Date:** 2026-09-23

## Context

The `harness` job authenticates with a refresh token stored in the
`OUTLOOK_HARNESS_TOKEN_JSON` repository secret. Microsoft Entra expires a
refresh token after **90 days of inactivity**, and the job only ran on `push`
and `pull_request` — so a long enough quiet period kills the credential
without anybody touching the repo.

### What actually happened, precisely

Two independent failures, close together, and it matters which is which —
this record was first written describing only the second.

1. **The harness account was deleted from the tenant**, some time before
   2026-08-03. CI failed from then on with `AADSTS500341` ("the user account
   … has been deleted from the … directory"), filed as
   [#75](https://github.com/XMV-Solutions-GmbH/outlook-mcp/issues/75).
2. **The orphaned refresh token then reached its 90-day inactivity limit**
   independently. It was issued 2026-05-08 and never redeemed again, so it
   would have expired around 2026-08-06 whatever happened to the account.
   By 2026-09-23 the error Entra returned had changed to `AADSTS700082`
   ("expired due to inactivity"), which is what
   [#89](https://github.com/XMV-Solutions-GmbH/outlook-mcp/issues/89) reported —
   without knowing #75 already existed.

**So the keep-alive would not have saved this particular credential.** No
schedule can redeem a token belonging to a deleted account. What the schedule
prevents is failure mode 2, which was real, was independently sufficient to
kill the credential, and is the one that recurs — an account is deleted once
and somebody notices; a token quietly ages out every ninety days for as long
as the repo is quiet.

The value of the schedule is therefore mostly in *detection*: a weekly run
surfaces a credential that has died for any reason within a week, instead of
letting it sit red until the next person happens to push. #75's own final
acceptance criterion asked for exactly that — "decide whether an
expiring/removed harness account should fail loudly earlier (e.g. a scheduled
canary run) so this does not sit red for days".

A decision record that is subtly wrong about its own trigger is worse than one
that is silent, hence this correction.

## What was decided

**Run the harness job weekly, and do not write the refreshed token back into
the secret.**

### Why a `schedule:` trigger on `ci.yml`, not a separate keep-alive workflow

One definition of the harness job, not two. A separate workflow would have to
duplicate the token-restore steps, the fork-safety guard and the environment,
and the copies would drift — at which point the keep-alive is exercising a
different code path from the one that guards pull requests, which is the one
thing it must not do. The scheduled run also exercises `lint` and `test`,
which catches dependency rot on a quiet repo for free.

`workflow_dispatch` is included so a freshly installed credential can be
verified immediately instead of on the next scheduled Monday.

Weekly, not daily: 90 days of margin against a 7-day cadence survives roughly
twelve consecutive missed runs. Daily would spend runner minutes to buy margin
that is already excessive.

### Why the `if:` guard had to change

The guard read:

```yaml
if: github.event_name == 'push' || github.event.pull_request.head.repo.full_name == github.repository
```

On a scheduled run `github.event.pull_request` is null, so the second half
evaluates false and the job would have been **skipped** — and a skipped job
reports the workflow as green. The keep-alive would have looked like it was
working right up until the credential expired 90 days later. `schedule` and
`workflow_dispatch` are now named explicitly. The fork-safety half is
unchanged: a `pull_request` event still qualifies only when the head repo is
this repo.

`tests/unit/test_ci_workflow.py` pins this, including that no job in the
harness job's `needs:` chain carries its own `if:` — a skipped dependency
would take the harness job down with it, just as silently.

## Why not write the refreshed token back into the secret

The more robust-sounding variant re-encodes the rotated refresh token after a
successful run and updates `OUTLOOK_HARNESS_TOKEN_JSON`. Rejected:

1. **It needs `secrets:write` on a public repository.** The default
   `GITHUB_TOKEN` cannot do it, so it means storing a PAT or GitHub App
   credential that can rewrite repository secrets — a standing, high-value
   target living permanently in the repo, to protect a test credential. The
   risk is strictly worse than the problem.
2. **The benefit is speculative, and the premise it would protect against is
   now known to be false.** Entra rotates the refresh token on redemption, but
   the previous token remains valid — verified directly: a stored refresh
   token was redeemed, the rotated replacement discarded, and the *original*
   redeemed again successfully. Entra tracks the inactivity window against the
   grant, so redeeming the stored copy is what resets the clock, and the
   stored copy is exactly what the scheduled run redeems.

   This is not only inference from a single experiment. The second harness
   credential, `OUTLOOK_HARNESS_PERSONAL_TOKEN_JSON`, was issued on
   2026-05-23 and has never been rewritten — and on 2026-09-24, four months
   later, it was still alive. It survived because every CI run restores it
   and `tests/harness/test_personal_account.py` redeems it; pytest keeps
   running after failures, so it kept being redeemed on every push even
   through the seven weeks when the work/school half of the same job was
   failing and nobody was looking at it.

   That is the write-back hypothesis tested by accident, over four months,
   on a real credential: the *stored* copy was redeemed repeatedly without
   ever being updated, and its inactivity clock reset every time. Write-back
   would have changed nothing about that outcome.
3. **It does not rescue the failure case anyway.** Once a credential is dead —
   expired, revoked, or its mailbox deleted — write-back cannot help; a human
   has to sign in again. Write-back only ever helps in the window where
   scheduling already helps.

**Revisit if** a scheduled run ever fails with `AADSTS700082` despite the
weekly cadence. That would falsify point 2 — against four months of contrary
evidence, so look hard at the run history first — and the trade-off in point 1
would then deserve a second look.

## Failing loudly

A dead credential used to read as `2 failed, 4 passed, 10 skipped`. The
mechanism: the first test to call `get_token()` trips
`RefreshTokenInvalidError`, and `get_token` then deletes the cache entry by
design — which removes the file every later test guards on, so they skip with
"Harness token cache missing", a message about a contributor's laptop rather
than about Entra. One root cause, presented as flakiness.

`scripts/harness_preflight.py` now runs before the test layer and collapses
that into one annotated error naming the credential and how to replace it. The
distinction it draws:

| Situation | Result |
|---|---|
| Secret absent (fork PR, or not configured) | notice, job passes — an external contributor cannot supply it |
| Secret present, credential works | silent, tests run |
| Secret present, credential dead | **job fails** with one `::error::` |

Both harness credentials are covered, not just the work/school one.
The workflow names the profiles it actually restored in
`HARNESS_PROFILES` and the preflight checks each, reporting all
failures in one run rather than stopping at the first — two dead
credentials should cost one trip round the loop, not two. Driving it
off the restored secrets rather than a hardcoded list means a third
harness identity, if one is ever added, is covered by wiring the
restore step alone.

## The limit of this fix

GitHub **automatically disables scheduled workflows in a public repository
after 60 days with no repository activity**, and emails the admins first. So
the keep-alive is not unconditional: a repo that goes completely quiet loses
its schedule at day 60, and the credential then ages out ~90 days after
whatever the last scheduled run was. That is still a large improvement — the
credential survives roughly five months of total silence instead of three —
but it is a delay, not a guarantee.

This is worth knowing rather than worth engineering around: the disable notice
goes to the admins, and a repo that has seen no activity for two months has a
bigger problem than its harness credential. If the schedule is ever reported
as disabled, re-enable it and trigger one `workflow_dispatch` run.

## Consequences for future maintainers

- The scheduled run will fail every Monday while the secret holds a dead
  credential. That is the intended signal, not noise — but if the harness
  identity is going to be absent for a while, **remove the secret** rather
  than leave a dead one in place, and the job will report "not configured"
  and pass.
- Nothing here names a mailbox. Whichever identity ends up behind
  `OUTLOOK_HARNESS_TOKEN_JSON`, the keep-alive is indifferent to it.
- The weekly run is what keeps the credential alive. Disabling the schedule,
  letting the harness job start skipping, or letting GitHub disable the
  schedule for inactivity, all re-arm the same 90-day fuse.
- The schedule cannot rescue a credential whose *account* has gone — deleted,
  disabled, password-reset, MFA re-registered. For those the weekly run is a
  detector, not a preventer: it turns "red since some push three weeks ago"
  into "red since last Monday", which is the difference between noticing and
  not. Provisioning is always a human step.
