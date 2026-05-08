# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 XMV Solutions GmbH
# SPDX-FileContributor: David Koller <david.koller@xmv.de>
"""Unit tests for the token-store abstraction.

All tests run offline. The KeyringTokenStore tests use an in-memory
fake; the EncryptedFileTokenStore tests use pytest's `tmp_path`. Both
backends' selection logic is tested by patching `keyring.get_keyring`.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import keyring
import keyring.backend
import keyring.backends.fail
import keyring.errors
import pytest
from cryptography.fernet import InvalidToken

from outlook_mcp.auth.store import (
    EncryptedFileTokenStore,
    KeyringTokenStore,
    NoUsableTokenStoreError,
    PlainFileTokenStore,
    get_token_store,
    is_real_keyring_backend,
)

# ---------------------------------------------------------------------
# KeyringTokenStore — exercised against an in-memory fake backend
# ---------------------------------------------------------------------


class _FakeKeyringBackend:
    """In-memory keyring substitute. Mimics the three module-level functions."""

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, key: str) -> str | None:
        return self.store.get((service, key))

    def set_password(self, service: str, key: str, value: str) -> None:
        self.store[(service, key)] = value

    def delete_password(self, service: str, key: str) -> None:
        try:
            del self.store[(service, key)]
        except KeyError as exc:
            raise keyring.errors.PasswordDeleteError(str(exc)) from exc


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> Iterator[_FakeKeyringBackend]:
    fake = _FakeKeyringBackend()
    monkeypatch.setattr(keyring, "get_password", fake.get_password)
    monkeypatch.setattr(keyring, "set_password", fake.set_password)
    monkeypatch.setattr(keyring, "delete_password", fake.delete_password)
    yield fake


def test_keyring_set_get_roundtrip(fake_keyring: _FakeKeyringBackend) -> None:
    del fake_keyring  # patched into module-level keyring; instance not used directly
    store = KeyringTokenStore()
    store.set("profile-a", b"secret-bytes-1")
    assert store.get("profile-a") == b"secret-bytes-1"


def test_keyring_get_unknown_profile(fake_keyring: _FakeKeyringBackend) -> None:
    del fake_keyring
    store = KeyringTokenStore()
    assert store.get("never-stored") is None


def test_keyring_delete(fake_keyring: _FakeKeyringBackend) -> None:
    del fake_keyring
    store = KeyringTokenStore()
    store.set("profile-a", b"x")
    store.delete("profile-a")
    assert store.get("profile-a") is None


def test_keyring_delete_no_op_on_missing(fake_keyring: _FakeKeyringBackend) -> None:
    del fake_keyring
    store = KeyringTokenStore()
    # Must not raise even if the profile was never stored.
    store.delete("never-stored")


def test_keyring_per_profile_isolation(fake_keyring: _FakeKeyringBackend) -> None:
    del fake_keyring
    store = KeyringTokenStore()
    store.set("profile-a", b"value-a")
    store.set("profile-b", b"value-b")
    assert store.get("profile-a") == b"value-a"
    assert store.get("profile-b") == b"value-b"


# ---------------------------------------------------------------------
# EncryptedFileTokenStore — tmp_path + OUTLOOK_TOKEN_PASSPHRASE env
# ---------------------------------------------------------------------


@pytest.fixture
def file_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> EncryptedFileTokenStore:
    monkeypatch.setenv("OUTLOOK_TOKEN_PASSPHRASE", "test-passphrase-correct")
    return EncryptedFileTokenStore(base_dir=tmp_path)


def test_file_set_get_roundtrip(file_store: EncryptedFileTokenStore) -> None:
    file_store.set("profile-a", b"refresh-token-payload")
    assert file_store.get("profile-a") == b"refresh-token-payload"


def test_file_get_unknown_profile(file_store: EncryptedFileTokenStore) -> None:
    assert file_store.get("never-stored") is None


def test_file_delete(file_store: EncryptedFileTokenStore) -> None:
    file_store.set("profile-a", b"x")
    file_store.delete("profile-a")
    assert file_store.get("profile-a") is None


def test_file_delete_no_op_on_missing(file_store: EncryptedFileTokenStore) -> None:
    file_store.delete("never-stored")


def test_file_per_profile_isolation(file_store: EncryptedFileTokenStore) -> None:
    file_store.set("profile-a", b"value-a")
    file_store.set("profile-b", b"value-b")
    assert file_store.get("profile-a") == b"value-a"
    assert file_store.get("profile-b") == b"value-b"


def test_file_wrong_passphrase_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OUTLOOK_TOKEN_PASSPHRASE", "right-pass")
    EncryptedFileTokenStore(base_dir=tmp_path).set("profile-a", b"secret")

    monkeypatch.setenv("OUTLOOK_TOKEN_PASSPHRASE", "wrong-pass")
    with pytest.raises(InvalidToken):
        EncryptedFileTokenStore(base_dir=tmp_path).get("profile-a")


def test_file_no_passphrase_raises_on_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Behaviour change after switching to mcp-microsoft-graph-auth: empty
    passphrase raises at construction time (eager validation), not on
    first use. Catches misconfigured CI faster — the error fires when
    `get_token_store()` picks the encrypted backend, not on the first
    later token write."""
    monkeypatch.delenv("OUTLOOK_TOKEN_PASSPHRASE", raising=False)
    with pytest.raises(NoUsableTokenStoreError, match="OUTLOOK_TOKEN_PASSPHRASE"):
        EncryptedFileTokenStore(base_dir=tmp_path)


def test_file_permissions_owner_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OUTLOOK_TOKEN_PASSPHRASE", "p")
    EncryptedFileTokenStore(base_dir=tmp_path).set("profile-a", b"v")

    enc = tmp_path / "profile-a" / "token.enc"
    salt = tmp_path / "profile-a" / "token.salt"
    assert (enc.stat().st_mode & 0o777) == 0o600
    assert (salt.stat().st_mode & 0o777) == 0o600


def test_file_salt_persists_across_instances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Subsequent set() calls must reuse the existing salt, not regenerate it."""
    monkeypatch.setenv("OUTLOOK_TOKEN_PASSPHRASE", "p")
    EncryptedFileTokenStore(base_dir=tmp_path).set("profile-a", b"v1")
    salt1 = (tmp_path / "profile-a" / "token.salt").read_bytes()

    EncryptedFileTokenStore(base_dir=tmp_path).set("profile-a", b"v2")
    salt2 = (tmp_path / "profile-a" / "token.salt").read_bytes()
    assert salt1 == salt2


# ---------------------------------------------------------------------
# PlainFileTokenStore — tmp_path, no passphrase
# ---------------------------------------------------------------------


@pytest.fixture
def plain_store(tmp_path: Path) -> PlainFileTokenStore:
    return PlainFileTokenStore(base_dir=tmp_path)


def test_plain_set_get_roundtrip(plain_store: PlainFileTokenStore) -> None:
    plain_store.set("profile-a", b'{"access_token": "AT"}')
    assert plain_store.get("profile-a") == b'{"access_token": "AT"}'


def test_plain_get_unknown_profile(plain_store: PlainFileTokenStore) -> None:
    assert plain_store.get("never-stored") is None


def test_plain_delete(plain_store: PlainFileTokenStore) -> None:
    plain_store.set("profile-a", b"x")
    plain_store.delete("profile-a")
    assert plain_store.get("profile-a") is None


def test_plain_delete_no_op_on_missing(plain_store: PlainFileTokenStore) -> None:
    plain_store.delete("never-stored")


def test_plain_per_profile_isolation(plain_store: PlainFileTokenStore) -> None:
    plain_store.set("profile-a", b"value-a")
    plain_store.set("profile-b", b"value-b")
    assert plain_store.get("profile-a") == b"value-a"
    assert plain_store.get("profile-b") == b"value-b"


def test_plain_file_permissions_owner_only(tmp_path: Path) -> None:
    PlainFileTokenStore(base_dir=tmp_path).set("profile-a", b"v")
    f = tmp_path / "profile-a" / "token.json"
    assert (f.stat().st_mode & 0o777) == 0o600


# ---------------------------------------------------------------------
# is_real_keyring_backend
# ---------------------------------------------------------------------


def test_is_real_keyring_rejects_fail_backend() -> None:
    assert is_real_keyring_backend(keyring.backends.fail.Keyring()) is False


def test_is_real_keyring_rejects_plaintext_name() -> None:
    class PlaintextKeyring(keyring.backend.KeyringBackend):
        priority = -1.0

        def get_password(self, service: str, username: str) -> str | None:
            return None

        def set_password(self, service: str, username: str, password: str) -> None:
            pass

        def delete_password(self, service: str, username: str) -> None:
            pass

    assert is_real_keyring_backend(PlaintextKeyring()) is False


def test_is_real_keyring_accepts_other_backend() -> None:
    class FakeSecretService(keyring.backend.KeyringBackend):
        priority = 5.0

        def get_password(self, service: str, username: str) -> str | None:
            return None

        def set_password(self, service: str, username: str, password: str) -> None:
            pass

        def delete_password(self, service: str, username: str) -> None:
            pass

    assert is_real_keyring_backend(FakeSecretService()) is True


# ---------------------------------------------------------------------
# get_token_store auto-pick logic
# ---------------------------------------------------------------------


def test_get_token_store_explicit_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OUTLOOK_TOKEN_STORE", "keyring")
    monkeypatch.delenv("OUTLOOK_TOKEN_PASSPHRASE", raising=False)
    store = get_token_store()
    assert isinstance(store, KeyringTokenStore)


def test_get_token_store_explicit_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OUTLOOK_TOKEN_STORE", "file")
    monkeypatch.delenv("OUTLOOK_TOKEN_PASSPHRASE", raising=False)
    store = get_token_store()
    assert isinstance(store, PlainFileTokenStore)


def test_get_token_store_explicit_encrypted_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OUTLOOK_TOKEN_STORE", "encrypted-file")
    monkeypatch.setenv("OUTLOOK_TOKEN_PASSPHRASE", "p")
    store = get_token_store()
    assert isinstance(store, EncryptedFileTokenStore)


def test_get_token_store_invalid_explicit_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OUTLOOK_TOKEN_STORE", "garbage")
    with pytest.raises(NoUsableTokenStoreError, match="must be 'keyring', 'file'"):
        get_token_store()


def test_get_token_store_auto_picks_encrypted_when_passphrase_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OUTLOOK_TOKEN_STORE", raising=False)
    monkeypatch.setenv("OUTLOOK_TOKEN_PASSPHRASE", "p")
    monkeypatch.setattr(keyring, "get_keyring", lambda: keyring.backends.fail.Keyring())
    store = get_token_store()
    assert isinstance(store, EncryptedFileTokenStore)


def test_get_token_store_auto_picks_plain_file_when_no_keyring_no_passphrase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Universal fallback — no env vars needed for typical install."""
    monkeypatch.delenv("OUTLOOK_TOKEN_STORE", raising=False)
    monkeypatch.delenv("OUTLOOK_TOKEN_PASSPHRASE", raising=False)
    monkeypatch.setattr(keyring, "get_keyring", lambda: keyring.backends.fail.Keyring())
    store = get_token_store()
    assert isinstance(store, PlainFileTokenStore)


def test_get_token_store_picks_keyring_when_real_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRealBackend(keyring.backend.KeyringBackend):
        priority = 5.0

        def get_password(self, service: str, username: str) -> str | None:
            return None

        def set_password(self, service: str, username: str, password: str) -> None:
            pass

        def delete_password(self, service: str, username: str) -> None:
            pass

    monkeypatch.delenv("OUTLOOK_TOKEN_STORE", raising=False)
    monkeypatch.delenv("OUTLOOK_TOKEN_PASSPHRASE", raising=False)
    monkeypatch.setattr(keyring, "get_keyring", lambda: FakeRealBackend())
    store = get_token_store()
    assert isinstance(store, KeyringTokenStore)
