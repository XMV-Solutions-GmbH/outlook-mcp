# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Token persistence backends.

Thin shim over `mcp-microsoft-graph-auth`'s `token_store` module:
the backend implementations live in the shared library, this module
keeps Outlook-specific defaults (keyring service name, cache
directory, env-var names) and the env-var-driven auto-pick logic in
`get_token_store()`.

Backwards-compatible: existing imports of `KeyringTokenStore`,
`PlainFileTokenStore`, `EncryptedFileTokenStore`, `TokenStore`,
`NoUsableTokenStoreError`, `get_token_store` keep working from this
module.
"""

from __future__ import annotations

import os
from pathlib import Path

import keyring
from mcp_microsoft_graph_auth.token_store import (
    EncryptedFileTokenStore as _LibEncryptedFileTokenStore,
)
from mcp_microsoft_graph_auth.token_store import (
    KeyringTokenStore as _LibKeyringTokenStore,
)
from mcp_microsoft_graph_auth.token_store import (
    NoUsableTokenStoreError as NoUsableTokenStoreError,
)
from mcp_microsoft_graph_auth.token_store import (
    PlainFileTokenStore as _LibPlainFileTokenStore,
)
from mcp_microsoft_graph_auth.token_store import (
    TokenStore as TokenStore,
)
from mcp_microsoft_graph_auth.token_store import (
    is_real_keyring_backend as is_real_keyring_backend,
)

KEYRING_SERVICE = "outlook-mcp"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "outlook-mcp"
PASSPHRASE_ENV = "OUTLOOK_TOKEN_PASSPHRASE"
STORE_OVERRIDE_ENV = "OUTLOOK_TOKEN_STORE"

__all__ = [
    "DEFAULT_CACHE_DIR",
    "KEYRING_SERVICE",
    "PASSPHRASE_ENV",
    "STORE_OVERRIDE_ENV",
    "EncryptedFileTokenStore",
    "KeyringTokenStore",
    "NoUsableTokenStoreError",
    "PlainFileTokenStore",
    "TokenStore",
    "get_token_store",
]


class KeyringTokenStore(_LibKeyringTokenStore):
    """Outlook-flavoured keyring backend (default service: 'outlook-mcp')."""

    def __init__(self, service: str = KEYRING_SERVICE) -> None:
        super().__init__(service_name=service)


class PlainFileTokenStore(_LibPlainFileTokenStore):
    """Outlook-flavoured plain-file backend (default base_dir: ~/.cache/outlook-mcp)."""

    def __init__(self, base_dir: Path | None = None) -> None:
        super().__init__(base_dir=base_dir if base_dir is not None else DEFAULT_CACHE_DIR)


class EncryptedFileTokenStore(_LibEncryptedFileTokenStore):
    """Outlook-flavoured encrypted-file backend.

    Reads the passphrase from `OUTLOOK_TOKEN_PASSPHRASE` (or the
    override `passphrase_env`) at construction time. Construction
    raises `NoUsableTokenStoreError` when the env var is unset or
    empty — this is earlier than the predecessor's lazy raise-on-use,
    but catches misconfigured CI faster.
    """

    def __init__(
        self,
        base_dir: Path | None = None,
        passphrase_env: str = PASSPHRASE_ENV,
    ) -> None:
        passphrase = os.environ.get(passphrase_env, "")
        if not passphrase:
            raise NoUsableTokenStoreError(
                f"Encrypted-file token store requires the {passphrase_env} "
                "environment variable to be set and non-empty.",
            )
        super().__init__(
            base_dir=base_dir if base_dir is not None else DEFAULT_CACHE_DIR,
            passphrase=passphrase,
        )


def get_token_store() -> TokenStore:
    """Pick a token-store backend for the current environment.

    Resolution order (no env vars needed for the typical install):

    1. `OUTLOOK_TOKEN_STORE=keyring|file|encrypted-file` — explicit override.
    2. Auto: OS keyring if a real backend is detected (macOS Keychain,
       Windows Credential Locker, Linux Secret Service).
    3. Auto: encrypted-file backend if `OUTLOOK_TOKEN_PASSPHRASE` is set
       (opt-in, useful for CI where the passphrase + ciphertext are
       separate secrets).
    4. Auto: plain-file backend (`~/.cache/outlook-mcp/<profile>/
       token.json` mode 0600).

    Returns a backend; some backends may still raise at `set()` /
    `get()` time (e.g. a forced keyring choice with no real backend).
    """
    forced = os.environ.get(STORE_OVERRIDE_ENV, "").strip().lower()
    if forced == "keyring":
        return KeyringTokenStore()
    if forced in ("encrypted-file", "encrypted_file", "encrypted"):
        return EncryptedFileTokenStore()
    if forced == "file":
        return PlainFileTokenStore()
    if forced:
        raise NoUsableTokenStoreError(
            f"{STORE_OVERRIDE_ENV} must be 'keyring', 'file', or 'encrypted-file'; got {forced!r}",
        )

    if is_real_keyring_backend(keyring.get_keyring()):
        return KeyringTokenStore()

    if os.environ.get(PASSPHRASE_ENV):
        return EncryptedFileTokenStore()

    return PlainFileTokenStore()
