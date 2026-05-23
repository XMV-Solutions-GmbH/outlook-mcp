# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Detect whether an access token came from a personal Microsoft account.

Two empirical token shapes from Microsoft Graph:

- **Work/school accounts** (Azure AD tenants, incl. B2B guests) get a
  standard JWT — three base64url segments, payload contains `tid` etc.
- **Personal Microsoft accounts** (outlook.com / hotmail.com /
  live.com / msn.com) get a Microsoft-Account compact token, which
  starts with `Ew...` and is NOT a JWT — it's an opaque server-side
  reference. There is no `tid` claim to read.

Detection therefore has two paths: parse the JWT and check `tid`
against the documented consumer-tenant GUID, OR treat any non-empty
non-JWT-shaped access token as personal. The second path is needed
because pre-v0.7 the detector returned `work_or_school` for opaque
tokens (the conservative default), which broke the personal-account
guards on real personal sign-ins.

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

    Two-path detection (see module docstring):

    - **JWT shape with consumer tid** → personal. This is the textbook
      case and works for v1.0/v2.0 tokens with `aud=graph` for personal
      accounts that Microsoft happens to issue as a JWT.
    - **Non-empty, non-JWT shape (opaque token starting with `Ew...`)**
      → personal. Microsoft Graph issues this format for personal MSAs
      delegated to first-party apps including ours; there is no `tid`
      claim to read because the token isn't a JWT.

    Empty strings and 3-segment-but-unparseable JWTs return False —
    those are malformed inputs (genuine work/school tokens always
    decode), and defaulting to work/school is the less-disruptive
    choice when the input is broken.
    """
    if not access_token:
        return False
    parts = access_token.split(".")
    if len(parts) != 3:
        # Opaque (non-JWT) token — Microsoft Graph only issues this
        # shape for personal Microsoft accounts.
        return True
    claims = _decode_jwt_claims(access_token)
    if not claims:
        # 3-segment string but the payload didn't decode — treat as
        # work/school to preserve pre-v0.7 behaviour for genuinely
        # malformed input. Real Microsoft tokens never hit this path.
        return False
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
