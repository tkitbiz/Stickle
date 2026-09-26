"""The key file next to the database: the database key, wrapped.

The database key is random. When there is no credential store to keep it,
it is wrapped with a key derived from the user's password (Argon2id) and
stored here, encrypted and authenticated (XChaCha20-Poly1305). A recovery
key will wrap the same database key in a second slot of the same file.

    {"format": 1, "slots": {"password": {"kdf": "argon2id", "opslimit": 3,
     "memlimit": 268435456, "salt": "<base64>", "box": "<base64>"}}}

Slots this version does not know are kept as they are when the file is
rewritten, so an older app never drops what a newer one added. The file is
replaced atomically: a crash leaves either the old or the new file.
"""

import base64
import binascii
import json
import os
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

FORMAT = 1
PASSWORD = "password"
KEY_BYTES = 32
# libsodium's "moderate" Argon2id limits: about a third of a second and 256 MiB
# on a current PC, once per start. Stored with each slot, so they can be raised.
OPSLIMIT = 3
MEMLIMIT = 256 * 1024 * 1024


class KeyFileError(Exception):
    """The key file exists but cannot be understood; it is never overwritten."""


class WrongPasswordError(Exception):
    """The password does not open the key (or the slot was altered)."""


@dataclass(frozen=True)
class PasswordSlot:
    opslimit: int
    memlimit: int
    salt: bytes
    box: bytes  # nonce + ciphertext + tag


@dataclass(frozen=True)
class KeyFile:
    password: PasswordSlot | None
    other_slots: dict[str, object]  # kept unchanged

    @property
    def has_password(self) -> bool:
        return self.password is not None


def normalized(password: str) -> bytes:
    # The same password typed on macOS (decomposed) and elsewhere must match.
    return unicodedata.normalize("NFC", password).encode("utf-8")


def _aad(slot: str) -> bytes:
    return f"stickle key file {FORMAT} {slot}".encode()


def wrap_with_password(
    key: bytes,
    password: str,
    opslimit: int = OPSLIMIT,
    memlimit: int = MEMLIMIT,
    slot_name: str = PASSWORD,
) -> PasswordSlot:
    """key wrapped with password; slot_name binds it to its slot (a recovery key has its own)."""
    from nacl import pwhash, secret, utils

    if len(key) != KEY_BYTES:
        raise ValueError(f"key must be {KEY_BYTES} bytes")
    salt = utils.random(pwhash.argon2id.SALTBYTES)
    wrapping_key = pwhash.argon2id.kdf(
        secret.Aead.KEY_SIZE, normalized(password), salt, opslimit=opslimit, memlimit=memlimit
    )
    box = bytes(secret.Aead(wrapping_key).encrypt(key, _aad(slot_name)))
    return PasswordSlot(opslimit, memlimit, salt, box)


def unwrap_with_password(slot: PasswordSlot, password: str, slot_name: str = PASSWORD) -> bytes:
    from nacl import exceptions, pwhash, secret

    wrapping_key = pwhash.argon2id.kdf(
        secret.Aead.KEY_SIZE,
        normalized(password),
        slot.salt,
        opslimit=slot.opslimit,
        memlimit=slot.memlimit,
    )
    try:
        key = secret.Aead(wrapping_key).decrypt(slot.box, _aad(slot_name))
    except exceptions.CryptoError as error:
        raise WrongPasswordError from error
    if len(key) != KEY_BYTES:
        raise KeyFileError("wrapped key has the wrong length")
    return key


def _b64(value: object) -> bytes:
    if not isinstance(value, str):
        raise KeyFileError("expected base64 text")
    try:
        return base64.b64decode(value, validate=True)
    except binascii.Error as error:
        raise KeyFileError("invalid base64") from error


def _int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise KeyFileError("expected a positive integer")
    return value


def decode_slot(value: object) -> PasswordSlot:
    if not isinstance(value, dict):
        raise KeyFileError("password slot is not an object")
    fields = cast(dict[str, object], value)
    if fields.get("kdf") != "argon2id":
        raise KeyFileError("unknown key derivation")
    return PasswordSlot(
        opslimit=_int(fields.get("opslimit")),
        memlimit=_int(fields.get("memlimit")),
        salt=_b64(fields.get("salt")),
        box=_b64(fields.get("box")),
    )


def read_key_file(path: Path) -> KeyFile | None:
    """The key file, or None when there is none."""
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    try:
        parsed: object = json.loads(data)
    except (ValueError, UnicodeDecodeError) as error:
        raise KeyFileError("not JSON") from error
    if not isinstance(parsed, dict):
        raise KeyFileError("not an object")
    document = cast(dict[str, object], parsed)
    if document.get("format") != FORMAT:
        raise KeyFileError("unknown format")
    slots = document.get("slots")
    if not isinstance(slots, dict):
        raise KeyFileError("no slots")
    slot_map = cast(dict[str, object], slots)
    password = slot_map.get(PASSWORD)
    return KeyFile(
        password=None if password is None else decode_slot(password),
        other_slots={name: v for name, v in slot_map.items() if name != PASSWORD},
    )


def encode_slot(slot: PasswordSlot) -> dict[str, Any]:
    return {
        "kdf": "argon2id",
        "opslimit": slot.opslimit,
        "memlimit": slot.memlimit,
        "salt": base64.b64encode(slot.salt).decode("ascii"),
        "box": base64.b64encode(slot.box).decode("ascii"),
    }


def write_key_file(path: Path, key_file: KeyFile) -> None:
    """Replace the file atomically, flushed to disk before and after the swap."""
    slots: dict[str, Any] = dict(key_file.other_slots)
    if key_file.password is not None:
        slots[PASSWORD] = encode_slot(key_file.password)
    write_slots(path, slots)


def write_slots(path: Path, slots: dict[str, Any]) -> None:
    """A key file with these slots, replacing any atomically and durably."""
    data = json.dumps({"format": FORMAT, "slots": slots}, indent=2).encode("utf-8")
    temporary = path.with_name(path.name + ".new")
    try:
        with temporary.open("wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    if sys.platform != "win32":
        # Make the rename itself durable.
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
