"""System tray icon and its menu."""

from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

ICON_SIZE = 64


def make_icon() -> QIcon:
    """Placeholder icon drawn in code until the real artwork exists."""
    pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(150, 120, 20), 4))
    painter.setBrush(QColor(255, 220, 90))
    painter.drawRoundedRect(QRectF(6, 6, ICON_SIZE - 12, ICON_SIZE - 12), 8, 8)
    painter.end()
    return QIcon(pixmap)


class Tray(QSystemTrayIcon):
    def __init__(self, on_new_note: Callable[[], object], on_quit: Callable[[], object]) -> None:
        super().__init__(make_icon())
        self.setToolTip("Stickle")

        # QSystemTrayIcon does not own its menu, so keep a reference.
        self._menu = QMenu()
        self.new_note_action = self._menu.addAction(self.tr("New note"))
        self.new_note_action.triggered.connect(on_new_note)
        self._menu.addSeparator()
        self.quit_action = self._menu.addAction(self.tr("Quit Stickle"))
        self.quit_action.triggered.connect(on_quit)
        self.setContextMenu(self._menu)
