from collections.abc import Iterator

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot

from stickle.app.application import NoteManager
from stickle.app.note_window import (
    BUTTON_SIZE,
    ICON_SCALES,
    ICON_SIZE,
    TITLE_BAR_HEIGHT,
    NoteWindow,
)
from stickle.app.palette import qcolor
from stickle.core.colors import DEFAULT_COLOR, note_colors

FOREGROUND = qcolor(note_colors(DEFAULT_COLOR).text)


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
    title = window.title_bar.title
    assert title.palette().color(title.foregroundRole()) == FOREGROUND


def test_title_bar_is_slim_and_its_buttons_small(qtbot: QtBot) -> None:
    window = NoteWindow()
    qtbot.addWidget(window)
    window.show()

    bar = window.title_bar
    assert bar.height() == TITLE_BAR_HEIGHT == 22
    for button in (bar.pin_button, bar.menu_button, bar.close_button):
        assert button.size() == QSize(BUTTON_SIZE, BUTTON_SIZE)
        assert button.iconSize() == QSize(ICON_SIZE, ICON_SIZE)


@pytest.mark.parametrize("scale", ICON_SCALES)
def test_icons_are_drawn_for_each_screen_scale(qtbot: QtBot, scale: float) -> None:
    window = NoteWindow()
    qtbot.addWidget(window)
    icon = window.title_bar.close_button.icon()

    pixmap = icon.pixmap(QSize(ICON_SIZE, ICON_SIZE), scale)

    # Drawn at that scale, not stretched from another one.
    assert pixmap.width() == round(ICON_SIZE * scale)
    assert pixmap.devicePixelRatio() == pytest.approx(scale)


def test_icons_are_quiet_until_pointed_at(qtbot: QtBot) -> None:
    window = NoteWindow()
    qtbot.addWidget(window)
    icon = window.title_bar.menu_button.icon()
    size = QSize(ICON_SIZE, ICON_SIZE)

    def darkest(mode: QIcon.Mode) -> int:
        image = icon.pixmap(size, 2.0, mode).toImage()
        return min(
            image.pixelColor(x, y).lightness()
            for x in range(image.width())
            for y in range(image.height())
            if image.pixelColor(x, y).alpha() == 255
        )

    assert darkest(QIcon.Mode.Normal) > darkest(QIcon.Mode.Active)


def test_the_pin_stands_when_on_top_and_lies_when_not(qtbot: QtBot) -> None:
    window = NoteWindow()
    qtbot.addWidget(window)
    size = QSize(ICON_SIZE, ICON_SIZE)
    upright = window.title_bar.pin_button.icon().pixmap(size, 2.0).toImage()

    window.set_always_on_top(False)
    lying = window.title_bar.pin_button.icon().pixmap(size, 2.0).toImage()

    def column_of_point(image: QImage) -> set[int]:
        """Columns inked in the bottom row: the pin's point."""
        y = image.height() - 2
        return {x for x in range(image.width()) if image.pixelColor(x, y).alpha() > 60}

    middle = upright.width() // 2
    assert any(abs(x - middle) <= 1 for x in column_of_point(upright))  # straight down
    assert not any(abs(x - middle) <= 1 for x in column_of_point(lying))  # off to a side
    window.release()


def test_every_control_has_an_accessible_name(qtbot: QtBot) -> None:
    window = NoteWindow()
    qtbot.addWidget(window)

    bar = window.title_bar
    controls: list[QWidget] = [window, window.editor, bar.close_button, bar.menu_button]
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


def test_ctrl_w_hides_the_note(qtbot: QtBot, manager: NoteManager) -> None:
    window = manager.new_note()
    qtbot.waitActive(window)

    with qtbot.waitSignal(window.closed):
        QTest.keyClick(window.windowHandle(), Qt.Key.Key_W, Qt.KeyboardModifier.ControlModifier)

    assert manager.windows == ()


def test_hide_button_hides_the_note(qtbot: QtBot, manager: NoteManager) -> None:
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
