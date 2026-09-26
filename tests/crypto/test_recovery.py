"""The recovery key: its form, typing it, and what it unlocks."""

import re
import secrets
from collections.abc import Callable
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from stickle.crypto.recovery import (
    ALPHABET,
    FILE_NAME,
    RecoveryKeyTypoError,
    WrongRecoveryKeyError,
    canonical,
    generate,
    read_recovery,
    unwrap,
    write_recovery,
)

KEY = secrets.token_bytes(32)


def test_it_reads_as_eight_groups_of_four() -> None:
    key = generate()

    assert re.fullmatch(r"([0-9A-Z]{4}-){7}[0-9A-Z]{4}", key)
    assert not set(key.replace("-", "")) & set("ILOU")


def test_every_key_is_different() -> None:
    assert len({generate() for _ in range(200)}) == 200


@given(st.data())
def test_how_it_is_typed_does_not_matter(data: st.DataObject) -> None:
    key = generate()
    typed = "".join(
        data.draw(st.sampled_from([c, c.lower(), c + " "]))
        if c != "-"
        else data.draw(st.sampled_from(["-", "", " ", " - "]))
        for c in key
    )
    typed = typed.replace("0", data.draw(st.sampled_from(["0", "O", "o"])))
    typed = typed.replace("1", data.draw(st.sampled_from(["1", "I", "l"])))

    assert canonical(typed) == key.replace("-", "")


def missing(key: str) -> str:
    return key[:-1]


def extra(key: str) -> str:
    return key + "A"


def last_mistyped(key: str) -> str:
    return key[:-1] + ALPHABET[(ALPHABET.index(key[-1]) + 1) % 32]


def not_a_key_character(key: str) -> str:
    return "!" + key[1:]


def empty(key: str) -> str:
    return ""


@pytest.mark.parametrize("mangle", [missing, extra, last_mistyped, not_a_key_character, empty])
def test_mistyped_keys_are_told_apart(mangle: Callable[[str], str]) -> None:
    with pytest.raises(RecoveryKeyTypoError):
        canonical(mangle(generate()))


def test_the_right_key_opens_and_another_does_not(tmp_path: Path) -> None:
    recovery_key = generate()
    write_recovery(tmp_path, KEY, recovery_key)
    slot = read_recovery(tmp_path)
    assert slot is not None

    assert unwrap(slot, recovery_key.lower()) == KEY
    with pytest.raises(WrongRecoveryKeyError):
        unwrap(slot, generate())


def test_a_new_key_replaces_the_old_one(tmp_path: Path) -> None:
    old, new = generate(), generate()
    write_recovery(tmp_path, KEY, old)
    write_recovery(tmp_path, KEY, new)
    slot = read_recovery(tmp_path)
    assert slot is not None

    assert unwrap(slot, new) == KEY
    with pytest.raises(WrongRecoveryKeyError):
        unwrap(slot, old)


def test_the_recovery_key_itself_is_never_written(tmp_path: Path) -> None:
    recovery_key = generate()
    write_recovery(tmp_path, KEY, recovery_key)

    written = b"".join(path.read_bytes() for path in tmp_path.iterdir())
    for form in (recovery_key, recovery_key.replace("-", ""), recovery_key.lower()):
        assert form.encode() not in written
    assert KEY not in written
    assert sorted(path.name for path in tmp_path.iterdir()) == [FILE_NAME]


def test_no_file_means_no_recovery_key(tmp_path: Path) -> None:
    assert read_recovery(tmp_path) is None


@settings(max_examples=20, deadline=None)
@given(st.binary(min_size=32, max_size=32))
def test_any_key_comes_back_intact(key: bytes) -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        recovery_key = generate()
        write_recovery(Path(folder), key, recovery_key)
        slot = read_recovery(Path(folder))
        assert slot is not None
        assert unwrap(slot, recovery_key) == key
