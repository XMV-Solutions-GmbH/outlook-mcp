# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Detect whether an access token came from a personal Microsoft account.

Personal MSAs (outlook.com / hotmail.com / live.com / msn.com / …) all
live in Microsoft's global *consumer tenant* with the fixed GUID below.
Tokens issued for work/school accounts carry the home-org's tenant GUID
in the `tid` claim.

Used by tool wrappers that need to refuse a personal-account caller for
Microsoft-side reasons — e.g. the `mailbox` parameter on email tools,
which routes via `/users/{upn}/...` (the FullAccess-Delegate path
exposed by Exchange Online); personal Microsoft accounts have no
equivalent construct, so any such call would 403 at Graph. We refuse
client-side with a clearer message instead.

Decoding is JWT-claims-only — we don't re-verify the signature because
the token was already validated by whatever issued it; we just need to
read the `tid` claim to route business logic.
"""

from __future__ import annotations

import base64
import json
from typing import Any

# Microsoft's global consumer-tenant GUID. Documented at
# https://learn.microsoft.com/en-us/azure/active-directory/develop/v2-protocols-oidc#fetch-the-openid-connect-metadata-document
# Any token whose `tid` claim equals this value comes from a personal
# Microsoft account (MSA) rather than an Azure AD tenant.
CONSUMER_TENANT_ID = "9188040d-6c67-4c5b-b112-36a304b66dad"


def _decode_jwt_claims(access_token: str) -> dict[str, Any]:
    """Decode the payload of a JWT without verifying the signature.

    We don't need verification here — the caller already trusts the
    token (it came from `get_token()` after Microsoft Identity issued
    it). We just need to read claims to route logic.

    Microsoft Identity v2.0 access tokens are always JWTs with three
    dot-separated base64url segments: header, payload, signature.
    Returns the decoded payload as a dict, or `{}` if the token can't
    be parsed (e.g. opaque tokens, malformed strings) so callers can
    default to "treat as work/school" — the more restrictive bucket.
    """
    parts = access_token.split(".")
    if len(parts) != 3:
        return {}
    payload_segment = parts[1]
    # base64url pad-correction: the segment may be missing trailing `=`
    padding = "=" * (-len(payload_segment) % 4)
    try:
        raw = base64.urlsafe_b64decode(payload_segment + padding)
        decoded = json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(decoded, dict):
        return {}
    return decoded


def is_personal_account(access_token: str) -> bool:
    """True iff the token was issued for a personal Microsoft account.

    Returns False on opaque tokens or unparseable JWTs — conservative
    default: when in doubt, assume work/school so that work-only tool
    paths remain available rather than spuriously refused.
    """
    claims = _decode_jwt_claims(access_token)
    return claims.get("tid") == CONSUMER_TENANT_ID


def signed_in_account_type(access_token: str) -> str:
    """Return a stable label for the token's account type.

    Used in user-facing error messages and structured logs:

      "personal" — outlook.com / hotmail.com / live.com / msn.com / …
      "work_or_school" — Azure AD tenant account, including XMV / B2B

    The two strings are stable contract; downstream code matches on
    them in error messages and tests.
    """
    return "personal" if is_personal_account(access_token) else "work_or_school"


__all__ = [
    "CONSUMER_TENANT_ID",
    "is_personal_account",
    "signed_in_account_type",
]
