"""Application start-up and the set of open note windows."""

import os
import sys
from pathlib import Path

from PySide6.QtCore import QLocale, QObject, QPoint, QTranslator, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from stickle.app.note_window import NoteWindow
from stickle.app.signals import SignalWatcher
from stickle.app.tray import Tray
from stickle.platform.linux.display import preferred_qt_platform

APP_ID = "co.linkro.stickle"
TRANSLATIONS_DIR = Path(__file__).resolve().parent.parent / "translations"

# New notes cascade from the top-left of the screen so they never land exactly on top of each other.
CASCADE_ORIGIN = 80
CASCADE_STEP = 32
CASCADE_LENGTH = 10


class NoteManager(QObject):
    # Qt's own "quit on last window closed" ignores tool windows, which notes are.
    last_note_closed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._windows: list[NoteWindow] = []
        self._created = 0

    @property
    def windows(self) -> tuple[NoteWindow, ...]:
        return tuple(self._windows)

    def new_note(self) -> NoteWindow:
        window = NoteWindow()
        window.new_note_requested.connect(self.new_note)
        window.closed.connect(lambda: self._forget(window))
        self._windows.append(window)

        offset = CASCADE_ORIGIN + CASCADE_STEP * (self._created % CASCADE_LENGTH)
        self._created += 1
        area = QGuiApplication.primaryScreen().availableGeometry()
        window.move(area.topLeft() + QPoint(offset, offset))

        window.show()
        window.activateWindow()
        window.setFocus()
        return window

    def _forget(self, window: NoteWindow) -> None:
        self._windows.remove(window)
        if not self._windows:
            self.last_note_closed.emit()


def install_translators(app: QApplication, locale: QLocale) -> None:
    """Load Qt's own strings (context menus, dialogs) and ours; English is the fallback."""
    for name in ("qtbase", "stickle"):
        translator = QTranslator(app)
        if translator.load(locale, name, "_", str(TRANSLATIONS_DIR)):
            app.installTranslator(translator)


def run(argv: list[str]) -> int:
    if sys.platform == "linux" and (platform := preferred_qt_platform(os.environ)):
        # An argument rather than QT_QPA_PLATFORM, so programs we open do not inherit it.
        argv = [argv[0], "-platform", platform, *argv[1:]]
    app = QApplication(argv)
    app.setApplicationName("Stickle")
    app.setDesktopFileName(APP_ID)
    app.setQuitOnLastWindowClosed(False)
    install_translators(app, QLocale.system())

    manager = NoteManager()
    # Without a tray there would be no way back to a hidden app, so quit with the last note.
    if not QSystemTrayIcon.isSystemTrayAvailable():
        manager.last_note_closed.connect(app.quit)
    tray = Tray(manager.new_note, app.quit)
    tray.show()
    manager.new_note()
    # Ctrl+C in a terminal, logout and shutdown all end the app through quit().
    watcher = SignalWatcher(app.quit)
    try:
        return app.exec()
    finally:
        watcher.close()
