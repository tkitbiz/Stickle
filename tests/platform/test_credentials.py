import secrets

import pytest

from stickle.platform.credentials import (
    DATABASE_KEY,
    KEY_BYTES,
    SERVICE,
    CredentialStore,
    CredentialStoreUnavailableError,
    platform_backend,
)


class FakeBackend:
    """In-memory store that can be told to fail like a locked keyring."""

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], str] = {}
        self.fail_reads = False
        self.writes = 0

    def get_password(self, service: str, username: str) -> str | None:
        if self.fail_reads:
            raise RuntimeError("keyring is locked")
        return self.items.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.writes += 1
        self.items[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        del self.items[(service, username)]


def test_creates_a_key_when_there_is_none() -> None:
    backend = FakeBackend()

    key = CredentialStore(backend).get_or_create_key()

    assert len(key) == KEY_BYTES
    assert (SERVICE, DATABASE_KEY) in backend.items


def test_returns_the_same_key_every_time() -> None:
    store = CredentialStore(FakeBackend())

    assert store.get_or_create_key() == store.get_or_create_key()


def test_never_overwrites_a_key_it_could_not_read() -> None:
    # A locked keyring or a dismissed unlock prompt must not look like "no key yet":
    # a new key would make the existing database unreadable for good.
    backend = FakeBackend()
    original = CredentialStore(backend).get_or_create_key()
    backend.fail_reads = True
    writes_before = backend.writes

    with pytest.raises(CredentialStoreUnavailableError):
        CredentialStore(backend).get_or_create_key()

    assert backend.writes == writes_before
    backend.fail_reads = False
    assert CredentialStore(backend).get_or_create_key() == original


def test_foreign_value_is_not_replaced() -> None:
    backend = FakeBackend()
    backend.items[(SERVICE, DATABASE_KEY)] = "not base64 !"

    with pytest.raises(CredentialStoreUnavailableError):
        CredentialStore(backend).get_or_create_key()
    assert backend.items[(SERVICE, DATABASE_KEY)] == "not base64 !"


def real_store() -> CredentialStore:
    try:
        return CredentialStore(platform_backend())
    except CredentialStoreUnavailableError as error:
        pytest.skip(f"no credential store here ({error})")


def test_real_store_round_trip() -> None:
    store = real_store()
    name = f"test-{secrets.token_hex(8)}"
    secret = secrets.token_bytes(KEY_BYTES)
    try:
        assert store.read(name) is None
        store.write(name, secret)
        assert store.read(name) == secret
    finally:
        store.delete(name)
    assert store.read(name) is None
