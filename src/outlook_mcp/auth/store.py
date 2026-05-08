# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Token persistence backends.

Three implementations behind a `TokenStore` Protocol, in preference
order:

- `KeyringTokenStore`: uses python-keyring, which delegates to the
  active OS keyring (Secret Service / Keychain / Credential Locker).
  Available when the OS provides one of those — this is what most
  desktop installs (macOS, Windows, Linux with gnome-keyring) hit.
- `PlainFileTokenStore`: JSON at `~/.cache/outlook-mcp/<profile>
  /token.json` with mode 0600. Default fallback when keyring isn't
  available. Same security model as `gh auth`, `aws configure`,
  `npm login`, `~/.ssh/id_rsa`: trust the local user account.
- `EncryptedFileTokenStore`: cryptography.fernet ciphertext on disk
  with a Scrypt-derived key from `OUTLOOK_TOKEN_PASSPHRASE`. Opt-in
  for CI (passphrase + ciphertext as separate secrets) or paranoid
  users.

Auto-detection: keyring (if real backend) → plain file (default
fallback) → encrypted file (only if passphrase set). No env vars
needed for the typical install. `OUTLOOK_TOKEN_STORE=keyring|file|
encrypted-file` forces a specific backend.
"""

from __future__ import annotations

import os
import secrets
from base64 import urlsafe_b64encode
from pathlib import Path
from typing import Protocol

import keyring
import keyring.backend
import keyring.backends.fail
import keyring.errors
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

KEYRING_SERVICE = "outlook-mcp"
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "outlook-mcp"
PASSPHRASE_ENV = "OUTLOOK_TOKEN_PASSPHRASE"
STORE_OVERRIDE_ENV = "OUTLOOK_TOKEN_STORE"

# Scrypt parameters chosen for ~50ms KDF on a typical laptop —
# memory-hard enough to defeat GPU brute force on a leaked file
# while keeping CLI startup snappy.
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16


class NoUsableTokenStoreError(RuntimeError):
    """Raised when no token-store backend can be activated.

    Realistically only fires when the user gave an invalid
    `OUTLOOK_TOKEN_STORE` override or `OUTLOOK_TOKEN_STORE=encrypted-file`
    without a passphrase. The default auto-pick always finds a
    backend (plain file is the universal fallback).
    """


class TokenStore(Protocol):
    """Persistence interface for OAuth tokens, namespaced by profile.

    Implementations must be safe to instantiate multiple times against
    the same underlying storage; concurrent access is not required for
    v0.1 (one MCP process per profile).
    """

    def get(self, profile: str) -> bytes | None:
        """Return stored bytes for `profile`, or None if not stored."""
        ...

    def set(self, profile: str, value: bytes) -> None:
        """Store `value` under `profile`. Overwrites if it exists."""
        ...

    def delete(self, profile: str) -> None:
        """Remove stored value for `profile`. No-op if not present."""
        ...


class KeyringTokenStore:
    """python-keyring-backed token store.

    Stores tokens as the password value under a `(service, profile)`
    key pair in the active OS keyring. Requires a real backend; calls
    raise `keyring.errors.NoKeyringError` on `fail.Keyring`.
    """

    def __init__(self, service: str = KEYRING_SERVICE) -> None:
        self._service = service

    def get(self, profile: str) -> bytes | None:
        value = keyring.get_password(self._service, profile)
        return value.encode() if value is not None else None

    def set(self, profile: str, value: bytes) -> None:
        keyring.set_password(self._service, profile, value.decode())

    def delete(self, profile: str) -> None:
        try:
            keyring.delete_password(self._service, profile)
        except keyring.errors.PasswordDeleteError:
            # Already absent — match Protocol's "no-op if not present" contract.
            pass


class EncryptedFileTokenStore:
    """Fernet-encrypted-file token store.

    Layout per profile under `base_dir`:

        <base_dir>/<profile>/token.enc    Fernet ciphertext
        <base_dir>/<profile>/token.salt   16 random bytes (Scrypt salt)

    Both files are mode 0o600 (owner-only) on POSIX.

    Passphrase is read from the env var named by `passphrase_env` at
    every call — it is never cached in memory beyond the duration of
    the call. A wrong passphrase produces `cryptography.fernet.InvalidToken`
    on `get()`.
    """

    def __init__(
        self,
        base_dir: Path | None = None,
        passphrase_env: str = PASSPHRASE_ENV,
    ) -> None:
        self._base_dir = base_dir if base_dir is not None else DEFAULT_CACHE_DIR
        self._passphrase_env = passphrase_env

    def _passphrase(self) -> bytes:
        pp = os.environ.get(self._passphrase_env, "").encode()
        if not pp:
            raise NoUsableTokenStoreError(
                f"Encrypted-file token store requires the {self._passphrase_env} "
                "environment variable to be set and non-empty.",
            )
        return pp

    def _profile_dir(self, profile: str) -> Path:
        d = self._base_dir / profile
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _derive_key(self, salt: bytes) -> bytes:
        kdf = Scrypt(salt=salt, length=32, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
        return urlsafe_b64encode(kdf.derive(self._passphrase()))

    def get(self, profile: str) -> bytes | None:
        d = self._profile_dir(profile)
        token_file = d / "token.enc"
        salt_file = d / "token.salt"
        if not token_file.exists() or not salt_file.exists():
            return None
        salt = salt_file.read_bytes()
        ciphertext = token_file.read_bytes()
        return Fernet(self._derive_key(salt)).decrypt(ciphertext)

    def set(self, profile: str, value: bytes) -> None:
        d = self._profile_dir(profile)
        salt_file = d / "token.salt"
        if salt_file.exists():
            salt = salt_file.read_bytes()
        else:
            salt = secrets.token_bytes(_SALT_BYTES)
            salt_file.write_bytes(salt)
            salt_file.chmod(0o600)
        ciphertext = Fernet(self._derive_key(salt)).encrypt(value)
        token_file = d / "token.enc"
        token_file.write_bytes(ciphertext)
        token_file.chmod(0o600)

    def delete(self, profile: str) -> None:
        d = self._profile_dir(profile)
        for name in ("token.enc", "token.salt"):
            try:
                (d / name).unlink()
            except FileNotFoundError:
                pass


class PlainFileTokenStore:
    """Plain JSON file token store, mode 0600.

    Universal fallback used when no OS keyring is available and the
    user hasn't opted into encrypted-file mode. Same security model
    as `gh auth login`, `aws configure`, `npm login`,
    `~/.ssh/id_rsa`: trust the local user account.

    Layout per profile:

        <base_dir>/<profile>/token.json   JSON of the CachedToken dict

    File mode is 0o600 (owner-only) on POSIX. Directory is created
    on demand. No env vars required.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir if base_dir is not None else DEFAULT_CACHE_DIR

    def _profile_dir(self, profile: str) -> Path:
        d = self._base_dir / profile
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get(self, profile: str) -> bytes | None:
        token_file = self._profile_dir(profile) / "token.json"
        if not token_file.exists():
            return None
        return token_file.read_bytes()

    def set(self, profile: str, value: bytes) -> None:
        token_file = self._profile_dir(profile) / "token.json"
        token_file.write_bytes(value)
        token_file.chmod(0o600)

    def delete(self, profile: str) -> None:
        try:
            (self._profile_dir(profile) / "token.json").unlink()
        except FileNotFoundError:
            pass


def _is_real_keyring_backend(kr: keyring.backend.KeyringBackend) -> bool:
    """Return True if `kr` is a real OS keychain integration.

    Excludes `fail.Keyring` (placeholder when no backend is available)
    and any backend whose class name suggests plaintext storage
    (`keyrings.alt.file.PlaintextKeyring` and friends).
    """
    if isinstance(kr, keyring.backends.fail.Keyring):
        return False
    if "Plaintext" in type(kr).__name__:
        return False
    return True


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
       token.json` mode 0600). This is the default fallback for
       headless Linux and matches what `gh auth login`,
       `aws configure`, etc. do.

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

    if _is_real_keyring_backend(keyring.get_keyring()):
        return KeyringTokenStore()

    if os.environ.get(PASSPHRASE_ENV):
        return EncryptedFileTokenStore()

    return PlainFileTokenStore()
