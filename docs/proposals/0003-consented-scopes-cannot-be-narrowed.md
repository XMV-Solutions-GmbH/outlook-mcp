<!--
SPDX-License-Identifier: MIT OR Apache-2.0
SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
SPDX-FileContributor: David Koller <david.koller@xmv.de>
-->

# 0003 — The opt-in flags cannot narrow an already-consented token

- **Status:** Accepted — option 1 (reword the promise), decided 2026-09-24.
  Option 2 stays available as a later stage; see § "What was decided".
- **Date:** 2026-09-23 (decided 2026-09-24)

## Context

`README.md` opens with the line the whole compliance story rests on:

> **The default install does not request `Mail.Send`** — the consent prompt does
> NOT include "this app can send mail as you", which is the line tenant admins
> (and your auditor) actually care about.

In production, with `OUTLOOK_ALLOW_DRAFTS=true` and `OUTLOOK_ALLOW_SEND=false`,
the access token's `scp` claim read:

```text
Calendars.Read Calendars.ReadWrite Group-Conversation.Read.All Mail.Read
Mail.ReadWrite Mail.ReadWrite.Shared Mail.Send User.Read email openid profile
```

`Mail.Send` is present with its flag off. So are `Mail.ReadWrite.Shared` and
`Group-Conversation.Read.All`, whose flags were never set at all.

## What the code actually does

The gating code is correct. Every claim below was checked against the source,
not assumed:

- `auth/flow.py:resolve_scopes()` composes the scope list from the flags and
  omits each gated scope when its flag is off.
- `auth/flow.py:request_device_code()` passes that list through to the
  `/devicecode` request, which is what drives the consent screen.
- `auth/flow.py:refresh_access_token()` and `auth/__init__.py:get_token()` pass
  it on the refresh grant too.
- `poll_for_token()` sends no `scope` at all on the device-code `/token` poll,
  which is correct — RFC 8628 binds the scope at `/devicecode`.
- `.default` appears **nowhere** in the delegated path. It is used only by
  `auth/service_principal.py` for the client-credentials flow, which this
  deployment never takes (`OUTLOOK_AUTH_MODE` unset, no `OUTLOOK_CLIENT_SECRET`).
- The installed server was 0.10.0, the same version as the tree, so this was
  not a stale build.

An early hypothesis was that the token is requested with the `.default` scope
and the per-flag gating never reaches the wire. That hypothesis is wrong, and
it is recorded here because it is the natural first guess and someone will make
it again.

## What actually happens

Microsoft Entra issues every scope already **consented** for the app
registration on that resource, regardless of the narrower set the request
named. Confirmed on the wire against the live tenant: a refresh-token grant for
the bundled client id asking for exactly

```text
Mail.Read Calendars.Read Mail.ReadWrite Calendars.ReadWrite User.Read offline_access
```

answered HTTP 200 with

```text
scope: Calendars.Read Calendars.ReadWrite Group-Conversation.Read.All Mail.Read
       Mail.ReadWrite Mail.ReadWrite.Shared Mail.Send User.Read profile openid email
```

and the issued access token's `scp` claim identical to it. Two profiles signed
in independently in the same tenant carry the same full set.

Once any sign-in — the user's own, a colleague's, or a tenant-wide admin
consent — has approved a scope for this app registration, no later request can
take it off the token. Narrowing the request narrows the *consent prompt*, and
only for a principal that has not consented yet.

## What this means for each promise

| Promise | Holds? |
|---|---|
| With `OUTLOOK_ALLOW_SEND=false`, no `ol_email_send_draft` tool exists | **Yes, always.** Registration is local; this is the guarantee that never depends on Entra. |
| The scope request omits the gated scopes | **Yes.** Now pinned by `tests/unit/auth/test_requested_scopes_on_the_wire.py`. |
| A *first* consent prompt does not say "send mail as you" | **Yes**, for a principal with no prior consent to this app. |
| The issued token does not carry `Mail.Send` | **No.** Not controllable by this client once consent exists. |

The never-auto-send rule itself is untouched: the tool is absent, and the
`scp` claim of a token nobody can call a send tool with changes nothing about
what the agent can do. What is affected is the *audit* claim — the sentence an
admin or auditor reads and takes at face value.

## What was decided

**Option 1 — reword the promise — was chosen on 2026-09-24.** The README now
states plainly that the flags govern what this server requests and exposes, not
the scope of a consent already granted, and documents the two remedies that act
on the grant itself.

**Option 2 remains available as a later stage** and is explicitly not being done
now. If an auditor ever needs the literal claim "this credential cannot send
mail", separate app registrations per flag combination is the way to get it, and
nothing in option 1 forecloses that — the wording describes the boundary
honestly, so tightening the boundary later only makes an accurate statement more
generous.

## The options that were weighed

Three options, not mutually exclusive:

1. **Reword the promise to be about the consent prompt and the tool surface**,
   and document the boundary. Cheapest, honest, no code. Costs the strongest
   version of the marketing line.
2. **Separate app registrations per flag combination.** A dedicated client id
   whose registered permission list contains only the ungated scopes makes the
   promise literally true again, because there is nothing broader to consent
   to. Costs: several registrations to publish and maintain, and operators must
   pick the right `OUTLOOK_CLIENT_ID`. This is the only option that makes the
   original sentence true as written.
3. **Incremental consent** — request the narrow set and only widen when a flag
   is turned on. Worth noting that this is what the code already does, and it
   is exactly what Entra ignores here; it does not solve the problem on its own,
   it only keeps a *fresh* registration clean.

**Recommendation, as filed: (1) now, (2) if an auditor ever needs the literal
claim.** Accepted as recommended.

The wording that shipped — the headline sentence gains the tool-surface
guarantee, the "first sign-in" qualifier and a pointer:

> **The default install does not request `Mail.Send`** — at a *first* sign-in
> the consent prompt does NOT include "this app can send mail as you", which is
> the line tenant admins (and your auditor) actually care about. Read *What the
> flags do and do not control* before relying on this: once a sign-in has
> consented to a scope, Microsoft Entra puts it on every later token for that
> app registration whether or not it was requested.

plus a new README section, *What the flags do and do not control*, stating the
four rows of the table above and the two recovery paths: revoke the
application's consent in Entra (Enterprise applications → mcp-server-outlook →
Permissions) and sign in again, or point `OUTLOOK_CLIENT_ID` at an app
registration whose permission list contains only what you want.

## What shipped ahead of the decision

Neither of these presumed an answer, so both landed first:

- `auth/granted.py` reads the issued `scp` and reports what exceeds the
  request. `ol_login_status` surfaces it as `granted_scopes_not_requested` with
  a note, so the gap is visible instead of assumed away.
- `tests/unit/auth/test_requested_scopes_on_the_wire.py` pins the half the code
  genuinely controls: the gated scopes are absent from the `scope` field of the
  device-code request and of the refresh grant when their flags are off, and
  present when they are on.

## Consequences for future maintainers

- Do not read a wide `scp` claim as a gating bug. Check
  `test_requested_scopes_on_the_wire.py` first — it asserts what was *asked
  for*, which is the only part this codebase decides.
- The never-auto-send rule does not rest on the scope request and never did. It
  rests on `ol_email_send_draft` not being registered. Keep those two arguments
  separate when explaining the compliance posture, or the weaker one
  (the scope request, which Entra can widen) ends up carrying the stronger
  one's weight.
- Revoking consent in Entra is the only way to shrink an existing grant.
  Removing a scope from `resolve_scopes()` does not do it.
- If the bundled app registration ever gains a new permission, every existing
  user's tokens can start carrying it after their next consent, without any
  change here.
