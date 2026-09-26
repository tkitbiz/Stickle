"""The recovery key: a way back to the notes when the usual key is lost.

The notes database key is wrapped a second time, with a recovery key shown
to the user once, in recovery.json next to the database. The recovery key
itself is never stored or logged: whoever has it can open the notes, and
only the user keeps it.

It reads like K7QM-2HXP-…: 32 characters in groups of four, from an
alphabet without look-alikes (Crockford's base 32: no I, L, O or U).
Typing O for 0 or I and L for 1 is read as meant, letter case, spaces and
dashes do not matter, and the last character checks the others, so a
mistyped key is told apart from a wrong one. 31 characters carry 155
random bits.

Making a new recovery key replaces the file, so the old key stops working.
"""

import hashlib
import secrets
from pathlib import Path

from stickle.crypto.keyfile import (
    KeyFileError,
    PasswordSlot,
    WrongPasswordError,
    decode_slot,
    encode_slot,
    read_key_file,
    unwrap_with_password,
    wrap_with_password,
    write_slots,
)

FILE_NAME = "recovery.json"
SLOT = "recovery"
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
DATA_CHARS = 31
GROUP = 4
# The key is long and random, so light key stretching is enough (libsodium's
# "interactive" limits); it still costs anyone guessing, and opens quickly.
OPSLIMIT = 2
MEMLIMIT = 64 * 1024 * 1024
LOOK_ALIKES = str.maketrans({"O": "0", "I": "1", "L": "1"})


class RecoveryKeyTypoError(ValueError):
    """Not a recovery key as written: a character is missing, extra or mistyped."""


class WrongRecoveryKeyError(Exception):
    """A well-formed key, but not the one that goes with these notes."""


def _check(data: str) -> str:
    return ALPHABET[hashlib.blake2b(data.encode("ascii"), digest_size=1).digest()[0] % 32]


def generate() -> str:
    data = "".join(secrets.choice(ALPHABET) for _ in range(DATA_CHARS))
    return format_key(data + _check(data))


def format_key(canonical: str) -> str:
    return "-".join(canonical[i : i + GROUP] for i in range(0, len(canonical), GROUP))


def canonical(typed: str) -> str:
    """The key as its 32 characters, or RecoveryKeyTypoError."""
    text = "".join(typed.split()).replace("-", "").upper().translate(LOOK_ALIKES)
    if len(text) != DATA_CHARS + 1 or any(c not in ALPHABET for c in text):
        raise RecoveryKeyTypoError("not 32 characters of a recovery key")
    if _check(text[:DATA_CHARS]) != text[DATA_CHARS]:
        raise RecoveryKeyTypoError("the check character does not match")
    return text


def write_recovery(folder: Path, database_key: bytes, recovery_key: str) -> None:
    """Wrap database_key with recovery_key into recovery.json, replacing any earlier one."""
    slot = wrap_with_password(
        database_key, canonical(recovery_key), OPSLIMIT, MEMLIMIT, slot_name=SLOT
    )
    write_slots(folder / FILE_NAME, {SLOT: encode_slot(slot)})


def read_recovery(folder: Path) -> PasswordSlot | None:
    """The wrapped key, or None without a recovery key (KeyFileError if damaged)."""
    key_file = read_key_file(folder / FILE_NAME)
    if key_file is None or SLOT not in key_file.other_slots:
        return None
    return decode_slot(key_file.other_slots[SLOT])


def unwrap(slot: PasswordSlot, typed: str) -> bytes:
    """The database key; RecoveryKeyTypoError or WrongRecoveryKeyError otherwise."""
    try:
        return unwrap_with_password(slot, canonical(typed), slot_name=SLOT)
    except WrongPasswordError as error:
        raise WrongRecoveryKeyError from error
    except KeyFileError as error:
        raise WrongRecoveryKeyError from error
