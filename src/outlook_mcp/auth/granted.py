# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""What the issued token actually grants, versus what was asked for.

`resolve_scopes()` decides what this server *requests*. Microsoft
Entra decides what the token *carries*, and the two are not the same
thing: Entra returns every scope already consented for the app
registration on that resource, regardless of the narrower set the
request named. Verified against a live tenant — a refresh asking for
exactly the six base scopes came back with `Mail.Send`,
`Mail.ReadWrite.Shared` and `Group-Conversation.Read.All` in `scp`,
because an earlier sign-in had consented to them.

So the opt-in flags gate three things the server controls — which
tools are registered, which scopes the consent screen shows at a
*first* sign-in, and which scopes are requested — and one thing it
does not: the privileges on the bearer token once consent has been
recorded. That gap is invisible unless someone looks, which is what
this module is for. Recovery is on the Entra side (revoke the app's
consent, or point `OUTLOOK_CLIENT_ID` at a dedicated registration),
not something the client can do.
"""

from __future__ import annotations

from outlook_mcp.auth.identity import decode_claims

# Scopes every token carries as a matter of protocol, not of consent.
# Listing them as "granted but not requested" would be noise.
_PROTOCOL_SCOPES = frozenset({"openid", "profile", "email", "offline_access"})


def granted_scopes(access_token: str) -> tuple[str, ...]:
    """Return the scopes carried by `access_token`, sorted.

    Empty for an opaque (personal-account) token, which carries no
    readable `scp` claim — unknown, not "none".
    """
    claims = decode_claims(access_token)
    if claims is None:
        return ()
    scp = claims.get("scp")
    if not isinstance(scp, str):
        return ()
    return tuple(sorted(scp.split()))


def excess_scopes(access_token: str, requested: tuple[str, ...]) -> tuple[str, ...]:
    """Scopes the token grants that `requested` did not ask for.

    These are the ones an operator who set a flag to `false` would be
    surprised to find on the wire. Protocol scopes are excluded.
    Empty when the token is opaque or carries nothing extra.
    """
    extra = set(granted_scopes(access_token)) - set(requested) - _PROTOCOL_SCOPES
    return tuple(sorted(extra))
