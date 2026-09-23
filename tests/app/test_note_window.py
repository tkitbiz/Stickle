from collections.abc import Iterator

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

from stickle.app.application import NoteManager
from stickle.app.note_window import FOREGROUND, NoteWindow


@pytest.fixture
def manager(qtbot: QtBot) -> Iterator[NoteManager]:
    manager = NoteManager()
    yield manager
    for window in manager.windows:
        window.close()


def test_note_window_floats_above_other_windows_without_a_taskbar_entry(qtbot: QtBot) -> None:
    window = NoteWindow()
    qtbot.addWidget(window)

    flags = window.windowFlags()
    assert flags & Qt.WindowType.WindowStaysOnTopHint
    assert flags & Qt.WindowType.FramelessWindowHint
    assert window.windowType() == Qt.WindowType.Tool
    assert window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


def test_text_stays_dark_on_the_light_note(qtbot: QtBot) -> None:
    window = NoteWindow()
    qtbot.addWidget(window)
    window.show()

    assert window.editor.palette().color(QPalette.ColorRole.Text) == FOREGROUND
    button = window.title_bar.close_button
    assert button.palette().color(QPalette.ColorRole.ButtonText) == FOREGROUND


def test_every_control_has_an_accessible_name(qtbot: QtBot) -> None:
    window = NoteWindow()
    qtbot.addWidget(window)

    controls: list[QWidget] = [window, window.editor, window.title_bar.close_button]
    assert all(control.accessibleName() for control in controls)


def test_new_notes_cascade_instead_of_stacking(manager: NoteManager) -> None:
    first = manager.new_note()
    second = manager.new_note()

    assert len(manager.windows) == 2
    assert second.pos() != first.pos()


def test_new_note_gets_keyboard_focus(qtbot: QtBot, manager: NoteManager) -> None:
    window = manager.new_note()
    qtbot.waitUntil(lambda: window.editor.hasFocus())


def test_ctrl_n_opens_another_note(qtbot: QtBot, manager: NoteManager) -> None:
    window = manager.new_note()
    qtbot.waitActive(window)

    QTest.keyClick(window.windowHandle(), Qt.Key.Key_N, Qt.KeyboardModifier.ControlModifier)

    assert len(manager.windows) == 2


def test_ctrl_w_closes_the_note(qtbot: QtBot, manager: NoteManager) -> None:
    window = manager.new_note()
    qtbot.waitActive(window)

    with qtbot.waitSignal(window.closed):
        QTest.keyClick(window.windowHandle(), Qt.Key.Key_W, Qt.KeyboardModifier.ControlModifier)

    assert manager.windows == ()


def test_close_button_closes_the_note(qtbot: QtBot, manager: NoteManager) -> None:
    window = manager.new_note()

    with qtbot.waitSignal(window.closed):
        QTest.mouseClick(window.title_bar.close_button, Qt.MouseButton.LeftButton)

    assert manager.windows == ()


def test_typed_text_stays_in_the_note(qtbot: QtBot, manager: NoteManager) -> None:
    window = manager.new_note()

    QTest.keyClicks(window.editor, "Buy milk")

    assert window.editor.toPlainText() == "Buy milk"


def test_closing_the_last_note_is_announced(qtbot: QtBot, manager: NoteManager) -> None:
    first = manager.new_note()
    second = manager.new_note()

    with qtbot.assertNotEmitted(manager.last_note_closed):
        first.close()
    with qtbot.waitSignal(manager.last_note_closed):
        second.close()
