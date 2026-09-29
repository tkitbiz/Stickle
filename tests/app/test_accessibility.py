"""Every control the keyboard can reach has a name a screen reader can say.

A name is the control's accessible name, the text on it (a button, a
checkbox) or a label naming it (a label's buddy). Parts of a composite
control (the line edit inside a key sequence edit) are named by the control.
"""

import secrets
from collections.abc import Iterator
from pathlib import Path

import apsw
import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractScrollArea,
    QAbstractSpinBox,
    QComboBox,
    QKeySequenceEdit,
    QLabel,
    QWidget,
)
from pytestqt.qtbot import QtBot
from test_shortcuts import System

from stickle.app.first_run import FirstRunDialog
from stickle.app.i18n import Translations
from stickle.app.note_window import NoteWindow
from stickle.app.notes import NoteManager
from stickle.app.password_dialog import PasswordDialog
from stickle.app.recovery_dialog import KINDS, Problem, RecoveryDialog
from stickle.app.recovery_key_dialog import EnterRecoveryKeyDialog, RecoveryKeyDialog
from stickle.app.shortcuts import GlobalShortcuts
from stickle.app.stickle_window import StickleWindow
from stickle.data.notes import NoteRepository
from stickle.data.schema import NotesDiff, open_store
from stickle.data.settings import Settings

KEY = secrets.token_bytes(32)
RECOVERY_KEY = "ABCD-EFGH-JKMN-PQRS-TVWX-YZ01-2345-6789"
COMPOSITE = (QKeySequenceEdit, QComboBox, QAbstractSpinBox)


def part_of_another(widget: QWidget, top: QWidget) -> bool:
    """Inside a composite control, or a scroll area's own viewport."""
    parent = widget.parentWidget()
    while parent is not None and parent is not top.parentWidget():
        if isinstance(parent, COMPOSITE):
            return True
        if isinstance(parent, QAbstractScrollArea) and widget is parent.viewport():
            return True
        parent = parent.parentWidget()
    return False


def unnamed(top: QWidget) -> list[str]:
    """The controls under top that the keyboard reaches but no one names."""
    named_by_label = {id(label.buddy()) for label in top.findChildren(QLabel) if label.buddy()}
    missing: list[str] = []
    for widget in [top, *top.findChildren(QWidget)]:
        if widget.focusPolicy() == Qt.FocusPolicy.NoFocus or part_of_another(widget, top):
            continue
        # A button, a checkbox or a label (text that can be selected) says its own text.
        text = widget.text() if isinstance(widget, QAbstractButton | QLabel) else ""
        if widget.accessibleName() or text.strip() or id(widget) in named_by_label:
            continue
        missing.append(f"{type(widget).__name__} {widget.objectName()!r}")
    return missing


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[apsw.Connection]:
    connection = open_store(tmp_path / "notes.db", KEY)
    yield connection
    connection.close()


def close(*windows: QWidget) -> None:
    for window in windows:
        if isinstance(window, NoteWindow):
            window.release()
        else:
            window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_a_note_names_all_it_offers(qtbot: QtBot) -> None:
    for window in (NoteWindow(text=""), NoteWindow(text="- [ ] 우유\n[문서](https://x.org)")):
        window.set_collapsed(True)  # the folded title bar takes the keyboard
        assert unnamed(window) == []
        window.set_collapsed(False)
        assert unnamed(window) == []
        close(window)


@pytest.mark.parametrize("hotkeys", [True, False])
def test_the_stickle_window_names_all_it_offers(
    qtbot: QtBot, connection: apsw.Connection, hotkeys: bool
) -> None:
    manager = NoteManager(NoteRepository(connection))
    shortcuts = GlobalShortcuts(Settings(connection), System(available=hotkeys))
    window = StickleWindow(
        manager, Translations(), lambda: None, settings=Settings(connection), shortcuts=shortcuts
    )

    assert unnamed(window) == []
    close(window)


def test_the_dialogs_name_all_they_offer(qtbot: QtBot, tmp_path: Path) -> None:
    diff = NotesDiff(missing=["회의록"], changed=[""], added=["새 메모"])
    dialogs: list[QWidget] = [
        PasswordDialog(True, lambda _: None),
        PasswordDialog(False, lambda _: None, can_recover=True),
        EnterRecoveryKeyDialog(lambda _: None),
        RecoveryKeyDialog(RECOVERY_KEY),
        FirstRunDialog(RECOVERY_KEY, True, True),
    ]
    dialogs += [
        RecoveryDialog(Problem(kind, diff=diff), tmp_path, export=lambda _: None)  # pyright: ignore[reportArgumentType]
        for kind in KINDS
    ]
    found = {type(dialog).__name__: unnamed(dialog) for dialog in dialogs}

    assert {name: missing for name, missing in found.items() if missing} == {}
    close(*dialogs)


def test_a_folded_note_is_read_by_its_title(qtbot: QtBot, translations: Translations) -> None:
    window = NoteWindow(text="# 장보기\n우유")
    window.set_collapsed(True)

    assert window.title_bar.accessibleName() == "Folded note: 장보기"
    translations.apply("ko")
    assert window.title_bar.accessibleName() == "접힌 메모: 장보기"
    assert window.title_bar.accessibleDescription() == "Enter를 누르면 펼칩니다."
    close(window)
