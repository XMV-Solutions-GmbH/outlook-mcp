# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Who does *this* access token belong to?

Two primitives that let every caller answer that question from the
token it is about to use, instead of from remembered state:

- `upn_from_access_token()` — reads the identity claim out of a JWT
  access token. No network, no cache, no ambiguity: the answer is a
  property of the bearer token itself.
- `token_fingerprint()` — a stable, non-reversible id for an access
  token, so an identity cache can be keyed to the exact token that
  produced it and misses as soon as the token changes.

Work/school (AzureAD) tokens are JWTs and carry `upn` /
`unique_name`. Personal Microsoft accounts get an opaque token that
is *not* a JWT, so `upn_from_access_token()` returns None for them
and the caller falls back to a `/me` round-trip. Returning None is
the point: a wrong identity is worse than an unknown one (issue #83).
"""

from __future__ import annotations

import hashlib
from typing import Any

import jwt

# Order matters. `upn` is the work/school account's user principal
# name. `unique_name` is the v1.0-issuer spelling of the same thing.
# `preferred_username` is what v2.0-issued tokens use. We take the
# first one present so the answer is the most authoritative spelling
# available, not whichever the JSON happened to order first.
_UPN_CLAIMS: tuple[str, ...] = ("upn", "unique_name", "preferred_username")


def token_fingerprint(access_token: str) -> str:
    """Return a stable, non-reversible fingerprint of `access_token`.

    Used as a cache key so cached identity is bound to the exact
    token it was derived from. Never log or surface the token itself;
    this hex digest is safe to keep in memory and compare.
    """
    return hashlib.sha256(access_token.encode("utf-8")).hexdigest()


def decode_claims(access_token: str) -> dict[str, Any] | None:
    """Decode the claims of a JWT access token, or None if it is not one.

    The single JWT-reading primitive in this package — `account_type`
    and `granted` both call it, so there is one answer to "what does
    this token say" rather than three hand-rolled base64 decoders that
    can disagree at the edges.

    Signature verification is deliberately off. The token came out of
    our own token store, Microsoft Identity issued it, and we never
    authorise anything on the strength of these claims — we only read
    them to describe the token to its owner. Verifying would require
    fetching and rotating Microsoft's signing keys to answer a question
    that does not turn on authenticity.

    Returns None for anything that is not a JWT with a JSON-object
    payload — notably personal-Microsoft-account tokens, which are
    opaque by design. None means "unknown", never "empty".
    """
    try:
        claims = jwt.decode(
            access_token,
            options={"verify_signature": False},
            algorithms=["RS256"],
        )
    except jwt.DecodeError:
        return None
    return claims if isinstance(claims, dict) else None


def upn_from_access_token(access_token: str) -> str | None:
    """Return the UPN this access token was issued for, or None.

    None means "cannot be determined from the token" — an opaque
    personal-account token, a malformed one, or a JWT without any of
    the identity claims. Callers fall back to `/me`; none of them may
    substitute a remembered value.
    """
    claims = decode_claims(access_token)
    if claims is None:
        return None
    for name in _UPN_CLAIMS:
        value = claims.get(name)
        if isinstance(value, str) and value.strip():
            return value
    return None
