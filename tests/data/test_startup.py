"""Settings needed before the notes database opens: the interface language."""

import json
from pathlib import Path

import pytest

from stickle.data.startup import FILE_NAME, StartupSettings


def test_nothing_chosen_follows_the_system(tmp_path: Path) -> None:
    assert StartupSettings(tmp_path).language is None
    assert not (tmp_path / FILE_NAME).exists()


def test_a_chosen_language_is_kept(tmp_path: Path) -> None:
    StartupSettings(tmp_path).set_language("ko")

    assert StartupSettings(tmp_path).language == "ko"
    assert json.loads((tmp_path / FILE_NAME).read_text("utf-8")) == {"language": "ko"}


def test_following_the_system_again_removes_the_choice(tmp_path: Path) -> None:
    startup = StartupSettings(tmp_path)
    startup.set_language("en")

    startup.set_language(None)

    assert startup.language is None
    assert json.loads((tmp_path / FILE_NAME).read_text("utf-8")) == {}


def test_unknown_languages_are_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="language"):
        StartupSettings(tmp_path).set_language("fr")


@pytest.mark.parametrize(
    "content",
    [b"", b"not json", b"[1, 2]", b'{"language": "xx"}', b'{"language": 3}', b"\xff\xfe"],
)
def test_a_damaged_file_means_the_system_language(tmp_path: Path, content: bytes) -> None:
    (tmp_path / FILE_NAME).write_bytes(content)

    assert StartupSettings(tmp_path).language is None


def test_other_entries_are_kept(tmp_path: Path) -> None:
    (tmp_path / FILE_NAME).write_text('{"from_a_newer_version": 1}', "utf-8")

    StartupSettings(tmp_path).set_language("ko")

    assert json.loads((tmp_path / FILE_NAME).read_text("utf-8")) == {
        "from_a_newer_version": 1,
        "language": "ko",
    }


def test_the_same_choice_writes_nothing(tmp_path: Path) -> None:
    startup = StartupSettings(tmp_path)
    startup.set_language("ko")
    (tmp_path / FILE_NAME).write_text('{"language": "ko", "marker": true}', "utf-8")

    startup.set_language("ko")

    assert "marker" in (tmp_path / FILE_NAME).read_text("utf-8")


def test_no_temporary_file_is_left_behind(tmp_path: Path) -> None:
    StartupSettings(tmp_path).set_language("ko")

    assert sorted(path.name for path in tmp_path.iterdir()) == [FILE_NAME]


def test_the_folder_is_created_if_needed(tmp_path: Path) -> None:
    StartupSettings(tmp_path / "new").set_language("en")

    assert StartupSettings(tmp_path / "new").language == "en"
