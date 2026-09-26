"""Find the key that opens the notes database.

The key is random and lives either in the OS credential store or, where there
is none, in keys.json wrapped with the user's password. Which one is decided
from files alone, so the credential store (and its unlock prompt) is never
touched in password mode.

A new key is created only while no database exists. With a database present,
a key that cannot be found or read is reported, never replaced: a new key
could not open the existing notes.
"""

import logging
import secrets
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from stickle.crypto.keyfile import (
    MEMLIMIT,
    OPSLIMIT,
    KeyFile,
    KeyFileError,
    read_key_file,
    unwrap_with_password,
    wrap_with_password,
    write_key_file,
)
from stickle.crypto.recovery import (
    WrongRecoveryKeyError,
    read_recovery,
    write_recovery,
)
from stickle.crypto.recovery import generate as generate_recovery_key
from stickle.crypto.recovery import unwrap as unwrap_recovery
from stickle.platform.credentials import (
    DATABASE_KEY,
    KEY_BYTES,
    CredentialStore,
    CredentialStoreUnavailableError,
    KeyMissingError,
    KeyRequest,
)

DATABASE = "notes.db"
KEY_FILE = "keys.json"
MIN_PASSWORD_LENGTH = 8

log = logging.getLogger(__name__)

type Blocker = Literal["store_unavailable", "key_missing", "key_file_unreadable"]


@dataclass(frozen=True)
class Unlocked:
    key: bytes
    source: Literal["credential store", "password"]


@dataclass(frozen=True)
class NeedPassword:
    create: bool  # True: first start without a credential store


@dataclass(frozen=True)
class Blocked:
    problem: Blocker


type Outcome = Unlocked | NeedPassword | Blocked


def password_length(password: str) -> int:
    return len(unicodedata.normalize("NFC", password))


class Unlock:
    """Started before Qt loads, so a credential store lookup overlaps it."""

    def __init__(
        self,
        folder: Path,
        store: Callable[[], CredentialStore] = CredentialStore,
        strength: tuple[int, int] = (OPSLIMIT, MEMLIMIT),  # lowered in tests
    ) -> None:
        self.folder = folder
        self._store = store
        self._strength = strength
        # The key that opened the notes, once they are open (to make a recovery key).
        self.opened_key: bytes | None = None
        # No notes existed when Stickle started: this is its first start here.
        self.first_start = not self.database.exists()
        self.start()

    @property
    def database(self) -> Path:
        return self.folder / DATABASE

    @property
    def key_file(self) -> Path:
        return self.folder / KEY_FILE

    def start(self) -> None:
        """(Re)read the files and, unless in password mode, ask the store for the key."""
        self._request: KeyRequest | None = None
        self._key_file: KeyFile | None = None
        self._unreadable = False
        self._database_existed = self.database.exists()
        try:
            self._key_file = read_key_file(self.key_file)
        except KeyFileError, OSError:
            self._unreadable = True
            return
        if self._key_file is None or not self._key_file.has_password:
            self._request = KeyRequest(store=self._store, create=not self._database_existed)

    def outcome(self) -> Outcome:
        if self._unreadable:
            return Blocked("key_file_unreadable")
        if self._key_file is not None and self._key_file.has_password:
            return NeedPassword(create=False)
        assert self._request is not None
        try:
            return Unlocked(self._request.key(), "credential store")
        except KeyMissingError:
            return Blocked("key_missing")
        except CredentialStoreUnavailableError as error:
            log.info("credential store unavailable: %s", error)
            if self._database_existed:
                return Blocked("store_unavailable")
            return NeedPassword(create=True)

    def enter_password(self, password: str) -> bytes:
        """The key, or WrongPasswordError."""
        assert self._key_file is not None and self._key_file.password is not None
        return unwrap_with_password(self._key_file.password, password)

    def create_password(self, password: str) -> bytes:
        """Make a new key protected by this password, before any database exists."""
        if self.database.exists() or (self._key_file is not None and self._key_file.has_password):
            raise RuntimeError("a key already exists; creating one would lock the notes out")
        if password_length(password) < MIN_PASSWORD_LENGTH:
            raise ValueError("password too short")
        key = secrets.token_bytes(KEY_BYTES)
        others = self._key_file.other_slots if self._key_file is not None else {}
        # Written before the database, so a database never exists without its key.
        write_key_file(
            self.key_file, KeyFile(wrap_with_password(key, password, *self._strength), others)
        )
        self._key_file = read_key_file(self.key_file)
        return key

    # The recovery key (stickle.crypto.recovery)

    @property
    def has_recovery_key(self) -> bool:
        try:
            return read_recovery(self.folder) is not None
        except KeyFileError, OSError:
            return False

    def open_with_recovery_key(self, typed: str) -> bytes:
        """The key, or RecoveryKeyTypoError / WrongRecoveryKeyError.

        Nothing is written here: the key is kept (keep_recovered_key or
        set_password) only once it has opened the database.
        """
        slot = read_recovery(self.folder)
        if slot is None:
            raise WrongRecoveryKeyError("no recovery key was made for these notes")
        return unwrap_recovery(slot, typed)

    @property
    def recovered_key_needs_password(self) -> bool:
        """Whether a key opened with the recovery key needs a new password to be kept:
        in password mode (the password was forgotten) or with keys.json damaged."""
        if self._unreadable:
            return True
        return self._key_file is not None and self._key_file.has_password

    def keep_recovered_key(self, key: bytes) -> None:
        """Put the key back in the credential store (or CredentialStoreUnavailableError)."""
        store = self._store()
        store.write(DATABASE_KEY, key)
        if store.read(DATABASE_KEY) != key:
            raise CredentialStoreUnavailableError("the store did not keep the key")

    def set_password(self, key: bytes, password: str) -> None:
        """Protect an existing key (known to open the database) with a new password.

        A damaged keys.json is set aside, never deleted: it may hold something
        a newer version understands.
        """
        if password_length(password) < MIN_PASSWORD_LENGTH:
            raise ValueError("password too short")
        others: dict[str, object] = {}
        if self._unreadable and self.key_file.exists():
            self.key_file.replace(self.key_file.with_name(f"{KEY_FILE}.damaged"))
        elif self._key_file is not None:
            others = self._key_file.other_slots
        write_key_file(
            self.key_file, KeyFile(wrap_with_password(key, password, *self._strength), others)
        )
        self._unreadable = False
        self._key_file = read_key_file(self.key_file)

    def make_recovery_key(self, key: bytes) -> str:
        """A new recovery key for key (known to open the database); the old one stops working."""
        recovery_key = generate_recovery_key()
        write_recovery(self.folder, key, recovery_key)
        return recovery_key
