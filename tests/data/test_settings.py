import secrets
import uuid
from collections.abc import Iterator
from pathlib import Path

import apsw
import pytest

from stickle.data.database import KEY_BYTES
from stickle.data.schema import open_store
from stickle.data.settings import (
    DEFAULT_NOTE_COLOR,
    DEVICE_ID,
    LANGUAGE,
    SETTINGS,
    InvalidSettingError,
    Settings,
)

KEY = secrets.token_bytes(KEY_BYTES)
NOW = "2026-09-26T10:00:00.000Z"


@pytest.fixture
def db(tmp_path: Path) -> Iterator[apsw.Connection]:
    connection = open_store(tmp_path / "notes.db", KEY)
    yield connection
    connection.close()


def test_unset_settings_read_as_their_defaults(db: apsw.Connection) -> None:
    settings = Settings(db)
    assert settings.get(LANGUAGE) is None  # follow the system
    assert settings.get(DEFAULT_NOTE_COLOR) == "yellow"


def test_values_survive_reopening(tmp_path: Path) -> None:
    path = tmp_path / "notes.db"
    connection = open_store(path, KEY)
    Settings(connection).set(LANGUAGE, "ko")
    Settings(connection).set(DEFAULT_NOTE_COLOR, "blue")
    connection.close()

    connection = open_store(path, KEY)
    assert Settings(connection).get(LANGUAGE) == "ko"
    assert Settings(connection).get(DEFAULT_NOTE_COLOR) == "blue"
    connection.close()


def test_device_and_shared_settings_are_kept_apart(db: apsw.Connection) -> None:
    settings = Settings(db, clock=lambda: NOW)
    settings.set(LANGUAGE, "en")
    settings.set(DEFAULT_NOTE_COLOR, "green")

    device = db.execute("SELECT key FROM device_settings ORDER BY key").fetchall()
    shared = db.execute("SELECT key FROM shared_settings").fetchall()
    assert ("language",) in device
    assert shared == [("default_color",)]


def test_shared_settings_record_when_and_where_they_changed(db: apsw.Connection) -> None:
    settings = Settings(db, clock=lambda: NOW)
    settings.set(DEFAULT_NOTE_COLOR, "pink")

    rows = db.execute("SELECT updated_at, updated_by FROM shared_settings").fetchall()
    assert rows == [(NOW, settings.device_id())]


def test_invalid_values_are_refused(db: apsw.Connection) -> None:
    settings = Settings(db)
    with pytest.raises(InvalidSettingError):
        settings.set(LANGUAGE, "fr")
    with pytest.raises(InvalidSettingError):
        settings.set(DEFAULT_NOTE_COLOR, "not a colour")
    assert settings.get(LANGUAGE) is None


def test_stored_value_that_no_longer_fits_falls_back_to_the_default(
    db: apsw.Connection,
) -> None:
    with db:
        db.execute("INSERT INTO device_settings VALUES ('language', '\"xx\"')")
    assert Settings(db).get(LANGUAGE) is None


def test_device_id_is_created_once_and_kept(db: apsw.Connection) -> None:
    settings = Settings(db)
    assert settings.get(DEVICE_ID) is None
    first = settings.device_id()

    assert str(uuid.UUID(first)) == first
    assert settings.device_id() == first
    assert Settings(db).get(DEVICE_ID) == first


def test_the_device_id_is_a_device_setting() -> None:
    # Copying the database to another computer must not make both claim one identity
    # once sync exists; keeping it out of shared settings is the first half of that.
    assert DEVICE_ID.scope == "device"


def test_every_setting_is_registered_under_its_key() -> None:
    assert all(key == setting.key for key, setting in SETTINGS.items())
    assert {LANGUAGE.key, DEVICE_ID.key, DEFAULT_NOTE_COLOR.key} <= SETTINGS.keys()
