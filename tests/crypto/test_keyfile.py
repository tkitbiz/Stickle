import json
import secrets
import unicodedata
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from stickle.crypto import keyfile
from stickle.crypto.keyfile import (
    KeyFile,
    KeyFileError,
    PasswordSlot,
    WrongPasswordError,
    read_key_file,
    unwrap_with_password,
    wrap_with_password,
    write_key_file,
)

KEY = secrets.token_bytes(32)
# The smallest limits libsodium accepts keep the tests fast; the real ones are checked below.
FAST = {"opslimit": 1, "memlimit": 8192}


def fast_wrap(key: bytes, password: str) -> PasswordSlot:
    return wrap_with_password(key, password, **FAST)


def test_the_default_strength_is_libsodiums_moderate_level() -> None:
    from nacl import pwhash

    assert keyfile.OPSLIMIT == pwhash.argon2id.OPSLIMIT_MODERATE
    assert keyfile.MEMLIMIT == pwhash.argon2id.MEMLIMIT_MODERATE


def test_the_right_password_unwraps_the_key() -> None:
    assert unwrap_with_password(fast_wrap(KEY, "correct horse"), "correct horse") == KEY


def test_a_wrong_password_is_refused() -> None:
    with pytest.raises(WrongPasswordError):
        unwrap_with_password(fast_wrap(KEY, "correct horse"), "correct hors")


def test_an_altered_slot_is_refused() -> None:
    slot = fast_wrap(KEY, "pw")
    box = bytearray(slot.box)
    box[-1] ^= 1
    with pytest.raises(WrongPasswordError):
        unwrap_with_password(
            PasswordSlot(slot.opslimit, slot.memlimit, slot.salt, bytes(box)), "pw"
        )


def test_composed_and_decomposed_hangul_are_the_same_password() -> None:
    password = "비밀번호암호"
    decomposed = unicodedata.normalize("NFD", password)
    assert decomposed != password

    assert unwrap_with_password(fast_wrap(KEY, password), decomposed) == KEY


def test_each_wrap_uses_a_new_salt_and_nonce() -> None:
    a, b = fast_wrap(KEY, "pw"), fast_wrap(KEY, "pw")
    assert a.salt != b.salt
    assert a.box != b.box


def test_file_round_trip_and_nothing_readable_inside(tmp_path: Path) -> None:
    path = tmp_path / "keys.json"
    slot = fast_wrap(KEY, "correct horse")
    write_key_file(path, KeyFile(password=slot, other_slots={}))

    loaded = read_key_file(path)
    assert loaded is not None and loaded.password == slot
    data = path.read_bytes()
    assert KEY not in data and b"correct horse" not in data
    assert unwrap_with_password(slot, "correct horse") == KEY


def test_missing_file_reads_as_none(tmp_path: Path) -> None:
    assert read_key_file(tmp_path / "keys.json") is None


def test_slots_from_a_newer_version_are_kept(tmp_path: Path) -> None:
    path = tmp_path / "keys.json"
    future = {"kind": "something new", "data": [1, 2, 3]}
    path.write_text(json.dumps({"format": 1, "slots": {"recovery-v9": future}}))

    loaded = read_key_file(path)
    assert loaded is not None and not loaded.has_password
    write_key_file(path, KeyFile(fast_wrap(KEY, "pw"), loaded.other_slots))

    again = read_key_file(path)
    assert again is not None and again.has_password
    assert again.other_slots == {"recovery-v9": future}


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"not json",
        b"\xff\xfe",
        b"[]",
        b'{"format": 2, "slots": {}}',
        b'{"format": 1}',
        b'{"format": 1, "slots": {"password": "x"}}',
        b'{"format": 1, "slots": {"password": {"kdf": "scrypt"}}}',
        b'{"format": 1, "slots": {"password": {"kdf": "argon2id", "opslimit": true,'
        b' "memlimit": 8192, "salt": "", "box": ""}}}',
        b'{"format": 1, "slots": {"password": {"kdf": "argon2id", "opslimit": 1,'
        b' "memlimit": 8192, "salt": "***", "box": ""}}}',
    ],
)
def test_a_damaged_file_is_reported_not_guessed(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "keys.json"
    path.write_bytes(content)
    with pytest.raises(KeyFileError):
        read_key_file(path)


def test_a_failed_write_leaves_the_old_file_and_no_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "keys.json"
    write_key_file(path, KeyFile(fast_wrap(KEY, "old"), {}))
    before = path.read_bytes()

    def fail(self: Path, target: Path) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError, match="disk full"):
        write_key_file(path, KeyFile(fast_wrap(KEY, "new"), {}))

    assert path.read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["keys.json"]


@settings(max_examples=25, deadline=None)
@given(st.text(min_size=1, max_size=40), st.binary(min_size=32, max_size=32))
def test_any_password_round_trips(password: str, key: bytes) -> None:
    assert unwrap_with_password(fast_wrap(key, password), password) == key
