"""The app's icon is drawn sharp at every size it is shown at."""

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor
from pytestqt.qtbot import QtBot

from stickle.app.app_icon import NOTE, SIZES, icon_pixmap, make_icon


def test_every_size_is_drawn_rather_than_scaled(qtbot: QtBot) -> None:
    icon = make_icon()
    assert sorted(size.width() for size in icon.availableSizes()) == sorted(SIZES)
    for size in (16, 256, 512):
        assert icon.pixmap(QSize(size, size)).size() == QSize(size, size)


def test_the_note_is_in_the_middle_and_the_corners_are_clear(qtbot: QtBot) -> None:
    for size in (16, 64, 512):
        image = icon_pixmap(size).toImage()
        # Below the lines of text: the note's own colour.
        middle = QColor(image.pixelColor(size // 2, size * 7 // 10))
        assert abs(middle.red() - NOTE.red()) < 30 and abs(middle.blue() - NOTE.blue()) < 40, size
        assert image.pixelColor(0, size - 1).alpha() == 0
        assert image.pixelColor(size - 1, 0).alpha() == 0
