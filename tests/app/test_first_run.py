"""The first start: a sample note, a few choices, and the recovery key."""

import secrets
from collections.abc import Callable, Iterator
from pathlib import Path

import apsw
import pytest
from pytestqt.qtbot import QtBot

from stickle.app.first_run import FirstRunDialog, sample_note, welcome
from stickle.app.i18n import Translations
from stickle.crypto.recovery import generate, read_recovery, unwrap, write_recovery
from stickle.data.notes import NoteRepository
from stickle.data.schema import open_store
from stickle.data.settings import (
    APP_MENU_ASKED,
    RECOVERY_KEY_KEPT,
    SEVERAL_DEVICES,
    THIS_DEVICE,
    USAGE,
    Settings,
)
from stickle.platform.autostart import Autostart, Places
from stickle.platform.linux.appimage import AppMenuEntry
from stickle.unlock import Unlock

KEY = secrets.token_bytes(32)


class Place:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.connection: apsw.Connection = open_store(folder / "notes.db", KEY)
        self.notes = NoteRepository(self.connection)
        self.settings = Settings(self.connection)
        self.autostart = Autostart(
            Places(home=folder, config=folder / "config", appdata=folder), "linux", ["/x"]
        )
        self.app_list = AppMenuEntry(folder / "Stickle.AppImage", b"png", folder / "share")
        self.shown: list[str] = []

    def make_recovery_key(self) -> str:
        recovery_key = generate()
        write_recovery(self.folder, KEY, recovery_key)
        return recovery_key

    def welcome(self, ask: Callable[[FirstRunDialog], object], offers: bool = True) -> None:
        def record(dialog: FirstRunDialog) -> object:
            self.shown.append(dialog.recovery.recovery_key)
            return ask(dialog)

        welcome(
            self.notes,
            self.settings,
            self.make_recovery_key,
            self.autostart if offers else None,
            self.app_list if offers else None,
            record,
        )


@pytest.fixture
def place(qtbot: QtBot, tmp_path: Path) -> Iterator[Place]:
    place = Place(tmp_path)
    yield place
    place.connection.close()


def go_through(kept: bool, several: bool = False) -> Callable[[FirstRunDialog], object]:
    def answer(dialog: FirstRunDialog) -> object:
        if several:
            dialog.several_devices.setChecked(True)
        dialog.next_button.click()
        assert dialog.pages.currentIndex() == 1
        assert not dialog.done_button.isEnabled()  # not before it is kept
        if kept:
            dialog.recovery.kept.setChecked(True)
            dialog.done_button.click()
        else:
            dialog.later_button.click()
        return None

    return answer


def test_going_through_sets_everything_up(place: Place) -> None:
    place.welcome(go_through(kept=True))

    assert [note.body for note in place.notes.all()] == [sample_note()]
    assert place.settings.get(USAGE) == THIS_DEVICE
    assert place.autostart.enabled
    assert place.app_list.added
    assert place.settings.get(APP_MENU_ASKED)
    assert place.settings.get(RECOVERY_KEY_KEPT)
    # The key shown is the one that opens the notes.
    slot = read_recovery(place.folder)
    assert slot is not None
    assert unwrap(slot, place.shown[0]) == KEY


def test_later_leaves_the_recovery_key_to_be_offered_again(place: Place) -> None:
    place.welcome(go_through(kept=False, several=True))

    assert place.settings.get(USAGE) == SEVERAL_DEVICES
    assert not place.settings.get(RECOVERY_KEY_KEPT)
    assert place.autostart.enabled


def test_closing_it_at_once_chooses_nothing_for_the_user(place: Place) -> None:
    place.welcome(lambda dialog: dialog.reject())

    assert len(place.notes.all()) == 1  # the sample note is there anyway
    assert place.settings.get(USAGE) is None
    assert not place.autostart.enabled
    assert not place.app_list.added
    assert not place.settings.get(APP_MENU_ASKED)
    assert not place.settings.get(RECOVERY_KEY_KEPT)


def test_unchecked_choices_are_respected(place: Place) -> None:
    def answer(dialog: FirstRunDialog) -> object:
        dialog.start_at_login.setChecked(False)
        dialog.app_list.setChecked(False)
        return go_through(kept=True)(dialog)

    place.welcome(answer)

    assert not place.autostart.enabled
    assert not place.app_list.added
    assert place.settings.get(APP_MENU_ASKED)  # asked, and the answer was no


def test_choices_that_do_not_apply_are_not_shown(place: Place) -> None:
    def answer(dialog: FirstRunDialog) -> object:
        assert dialog.start_at_login.isHidden()
        assert dialog.app_list.isHidden()
        return go_through(kept=True)(dialog)

    place.welcome(answer, offers=False)


def test_without_a_recovery_key_the_welcome_ends_after_the_first_page(
    qtbot: QtBot, tmp_path: Path
) -> None:
    place = Place(tmp_path)

    def fail() -> str:
        raise PermissionError("read-only")

    def answer(dialog: FirstRunDialog) -> object:
        dialog.next_button.click()
        assert dialog.result() == FirstRunDialog.DialogCode.Rejected
        return None

    welcome(place.notes, place.settings, fail, place.autostart, None, answer)
    assert place.autostart.enabled
    assert not place.settings.get(RECOVERY_KEY_KEPT)
    place.connection.close()


def test_the_language_is_chosen_first_and_the_sample_note_follows(
    place: Place, translations: Translations
) -> None:
    # An English system for someone who reads Korean: chosen on the first page.
    seen: list[str] = []

    def answer(dialog: FirstRunDialog) -> object:
        assert dialog.language_box.isVisibleTo(dialog)
        assert dialog.language_box.currentData() == "en"
        korean = dialog.language_box.findData("ko")
        dialog.language_box.setCurrentIndex(korean)
        dialog.language_box.activated.emit(korean)
        seen.append(dialog.heading.text())
        return go_through(kept=True)(dialog)

    welcome(
        place.notes,
        place.settings,
        place.make_recovery_key,
        place.autostart,
        place.app_list,
        answer,
        translations=translations,
    )

    assert seen == ["Stickle에 오신 것을 환영합니다"]
    assert translations.language == "ko"
    assert [note.body for note in place.notes.all()] == [sample_note()]
    assert place.notes.all()[0].body.startswith("# Stickle에 오신 것을 환영합니다")


def test_without_translations_to_switch_no_language_is_offered(qtbot: QtBot) -> None:
    dialog = FirstRunDialog(generate(), True, True)
    qtbot.addWidget(dialog)

    assert not dialog.language_box.isVisibleTo(dialog)


def test_the_sample_note_speaks_the_interface_language(translations: Translations) -> None:
    translations.apply("ko")

    note = sample_note()

    assert note.startswith("# Stickle에 오신 것을 환영합니다")
    assert "- [ ] " in note


def test_first_start_is_only_the_start_that_made_the_notes(tmp_path: Path) -> None:
    unlock = Unlock(tmp_path, lambda: pytest.fail("no store needed"), (1, 8192))
    assert unlock.first_start
    open_store(tmp_path / "notes.db", KEY).close()

    assert not Unlock(tmp_path, lambda: pytest.fail("no store needed"), (1, 8192)).first_start


def test_everything_has_a_name_and_a_key(qtbot: QtBot) -> None:
    dialog = FirstRunDialog(generate(), True, True)
    qtbot.addWidget(dialog)

    for check in (dialog.this_device, dialog.several_devices, dialog.start_at_login):
        assert "&" in check.text()
    assert dialog.recovery.key.accessibleName()
    assert "&" in dialog.language_label.text()
    assert dialog.language_label.buddy() is dialog.language_box
    assert dialog.language_box.accessibleName()
