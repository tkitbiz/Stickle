"""Application start-up and the set of open note windows."""

import os
import sys

from PySide6.QtCore import QObject, QPoint, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from stickle.app.fonts import ensure_korean_font
from stickle.app.i18n import Translations
from stickle.app.note_window import NoteWindow
from stickle.app.perf import open_storage_like_startup
from stickle.app.signals import SignalWatcher
from stickle.app.tray import Tray
from stickle.platform.linux.display import preferred_qt_platform

APP_ID = "co.linkro.stickle"

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


def run(argv: list[str], perf_notes: int | None = None, perf_blur: bool = False) -> int:
    """Run the app. perf_notes (measurement mode) opens that many notes and prints READY."""
    if sys.platform == "linux" and (platform := preferred_qt_platform(os.environ)):
        # An argument rather than QT_QPA_PLATFORM, so programs we open do not inherit it.
        argv = [argv[0], "-platform", platform, *argv[1:]]
    app = QApplication(argv)
    app.setApplicationName("Stickle")
    app.setDesktopFileName(APP_ID)
    app.setQuitOnLastWindowClosed(False)
    ensure_korean_font()
    translations = Translations()
    translations.apply(None)
    storage = open_storage_like_startup() if perf_notes is not None else ""

    manager = NoteManager()
    # Without a tray there would be no way back to a hidden app, so quit with the last note.
    if not QSystemTrayIcon.isSystemTrayAvailable():
        manager.last_note_closed.connect(app.quit)
    tray = Tray(manager.new_note, app.quit, translations)
    tray.show()
    for _ in range(max(1, perf_notes or 1)):
        manager.new_note()
    if perf_notes is not None:
        # Runs once the queued show and paint events have been handled.
        QTimer.singleShot(0, lambda: print(f"READY {storage}", flush=True))
    if perf_blur:
        # Idle as when the user works elsewhere: no text cursor blinking.
        QTimer.singleShot(0, lambda: [window.editor.clearFocus() for window in manager.windows])
    # Ctrl+C in a terminal, logout and shutdown all end the app through quit().
    watcher = SignalWatcher(app.quit)
    try:
        return app.exec()
    finally:
        watcher.close()
