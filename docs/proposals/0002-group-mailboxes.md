<!--
SPDX-License-Identifier: MIT OR Apache-2.0
SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
SPDX-FileContributor: David Koller <david.koller@xmv.de>
-->

# 0002 — Read Microsoft 365 group mailboxes

- **Status:** Implemented
- **Date:** 2026-08-08

## Context

The server could read the signed-in mailbox and, since v0.5, shared mailboxes
via `mailbox="<upn>"` → `/users/{upn}/…`. A Microsoft 365 **group** mailbox
looks like the same thing from the outside — it has an SMTP address, it
receives mail, the signed-in user is a member — but every call against it
failed with HTTP 403.

The 403 was not a permissions problem, and reading it as one cost time. Exchange
answers `/users/harness@xmv.de/…` with:

```text
ErrorGroupIsUsedInNonGroupURI — "Group Shard is used in non-Groups URI."
```

That is Exchange saying the address resolves to a group mailbox and the
`/users/` path is the wrong entrance — regardless of scope or delegation. No
amount of `Mail.ReadWrite.Shared`, and no Exchange `Add-MailboxPermission`,
opens that door, because group mailboxes have no FullAccess-delegate concept.

## What was decided

Treat group mailboxes as a **separate surface**, not a wider shared mailbox.

**Addressing.** `mailbox="group:<group-id>"`, taking the group's Entra object
id. An address is deliberately *not* accepted: resolving address → id needs
`/groups?$filter=mail eq …`, which answers 403 without a directory-read scope,
and requesting one purely to look up a name would be a far larger consent ask
than reading the conversations themselves. Verified — with the shipped scopes,
`GET /groups/{id}` is 403 while `GET /groups/{id}/threads` is 200.

**Consent.** A dedicated `OUTLOOK_ALLOW_GROUP_MAILBOXES`, following the
established optional-flag pattern (unset = off, typo raises). Explicitly *not*
folded into `OUTLOOK_ALLOW_SHARED_MAILBOXES`: an operator who enabled a
Sekretariats-Postfach must not thereby also consent to reading conversations
across every group they belong to.

**Scope.** `Group-Conversation.Read.All` — the least-privileged permission that
reads `/groups/{id}/threads`. Deliberately *not* `Group.Read.All`, which would
additionally grant tenant-wide directory reads the server never performs. Group
discovery rides on `/me/memberOf`, which the already-requested `User.Read`
covers.

**Read-only, structurally.** Write paths refuse group mailboxes before reaching
Graph. The scope grants no write, and a group conversation is shared by every
member — a delete is a delete for all of them.

## Two Graph behaviours that shape the surface

**No `$search` over group conversations.** `conversationThread` does not support
it, so `ol_email_search` on a group matches client-side over `topic`, `preview`
and `uniqueSenders`. That is genuinely weaker than the mailbox path — it never
sees message bodies — and the tool description says so rather than implying
equivalence.

**Posts carry no recipient.** A `post` has `from` and `sender`, no
`toRecipients`. This matters more than it first appears: a group mailbox
collecting plus-addressed mail (`box+case@example.com`, one address per test
case) would be unable to say *which* address a message arrived on — destroying
the only thing that scheme exists to provide.

The address survives in the MAPI property **`PidTagDisplayTo`**, which we
`$expand` and surface as `to`, with a `to_address` filter over it. Two traps,
both found only against the live tenant:

1. The `$expand` value must be passed **unencoded** to the HTTP layer. Encoding
   it before handing it to `httpx` double-encodes it and Graph answers 400.
2. Graph does **not** echo the property tag as sent. Request `String 0x0E04`,
   receive `String 0xe04` — lower-cased, leading zero dropped. Comparing the
   strings verbatim finds nothing, silently. Tags are compared numerically.

Trap 2 passed the mocked tests, because the fixtures had been written from the
*request* form. The fixtures now use the response form, and a dedicated test
pins the normalisation.

`PidTagDisplayTo` is a *display* field: for an address that resolves to a
directory object it holds the display name ("XMV Harness Mailbox"), and for one
that does not — every plus address — it holds the raw address. That is exactly
the direction the plus-addressing use case needs, but `to_address` is therefore
a reliable filter for plus addresses and not a general recipient filter.

## Consequences

- A group id in configuration is now a supported thing to have. If a future
  version ever requests a directory-read scope for other reasons, address-based
  addressing becomes possible and should be added then, not before.
- `ol_email_search` results from a group carry `id` = *thread* id.
  `ol_email_read` accepts it with the same `mailbox` value and returns `posts`
  alongside the flattened first-post fields, since a thread may hold several.
- `ConsentConfig` gained a defaulted fifth field rather than a required one, so
  existing four-argument constructions keep working.
