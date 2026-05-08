# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Cached-token data model.

Persisted shape of the OAuth tokens we hold on disk (in keyring or
encrypted file). Pure-data dataclass with JSON (de)serialisation; all
clock comparisons are in epoch seconds.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

# Refresh `buffer` seconds before the access token actually expires,
# so we never hand out a token that is about to be rejected by Graph
# in flight.
DEFAULT_REFRESH_BUFFER_SECONDS = 60


@dataclass(frozen=True)
class CachedToken:
    """An OAuth access + refresh token pair, with metadata.

    `expires_at` is the epoch-second moment the access token stops
    being valid (NOT a TTL). `scope` is the space-separated list
    Microsoft confirmed in the response.
    """

    access_token: str
    refresh_token: str | None
    expires_at: float
    scope: str

    def is_expired(self, *, buffer: float = DEFAULT_REFRESH_BUFFER_SECONDS) -> bool:
        """Return True if the access token expires within `buffer` seconds."""
        return self.expires_at - buffer <= time.time()

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> CachedToken:
        return cls(**json.loads(raw))
