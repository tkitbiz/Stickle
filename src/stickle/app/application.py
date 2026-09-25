"""Application start-up and the set of open note windows."""

import logging
import os
import sys
import time

from PySide6.QtCore import (
    QMessageLogContext,
    QObject,
    QPoint,
    QTimer,
    QtMsgType,
    Signal,
    qInstallMessageHandler,
)
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from stickle.app.fonts import ensure_korean_font
from stickle.app.i18n import Translations
from stickle.app.note_window import NoteWindow
from stickle.app.perf import PerfMode, open_storage_like_startup
from stickle.app.signals import SignalWatcher
from stickle.app.startup import open_notes
from stickle.app.tray import Tray
from stickle.platform.linux.display import preferred_qt_platform
from stickle.unlock import Unlock

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


def report_ready(perf: PerfMode, manager: NoteManager) -> None:
    perf.mark("drawn")
    print(perf.ready_line(), flush=True)
    if perf.blur:
        # Idle as when the user works elsewhere: no text cursor blinking.
        for window in manager.windows:
            window.editor.clearFocus()


log = logging.getLogger(__name__)
QT_LOG_LEVELS = {
    QtMsgType.QtDebugMsg: logging.DEBUG,
    QtMsgType.QtInfoMsg: logging.INFO,
    QtMsgType.QtWarningMsg: logging.WARNING,
    QtMsgType.QtCriticalMsg: logging.ERROR,
    QtMsgType.QtFatalMsg: logging.CRITICAL,
}


def log_qt_message(kind: QtMsgType, _context: QMessageLogContext, message: str) -> None:
    logging.getLogger("qt").log(QT_LOG_LEVELS.get(kind, logging.WARNING), "%s", message)


def run(
    argv: list[str],
    perf: PerfMode | None = None,
    unlock: Unlock | None = None,
    started: float | None = None,
) -> int:
    """Run the app. In measurement mode, open perf.notes notes and print READY.

    With unlock, the notes database is opened first (asking for a password or
    showing the recovery dialog when needed); quitting there ends the app.
    """
    timings: list[str] = []

    def mark(phase: str) -> None:
        if perf is not None:
            perf.mark(phase)
        if started is not None:
            timings.append(f"{phase} {time.perf_counter() - started:.2f}s")

    mark("imports")
    if sys.platform == "linux" and (platform := preferred_qt_platform(os.environ)):
        # An argument rather than QT_QPA_PLATFORM, so programs we open do not inherit it.
        argv = [argv[0], "-platform", platform, *argv[1:]]
    app = QApplication(argv)
    app.setApplicationName("Stickle")
    app.setDesktopFileName(APP_ID)
    app.setQuitOnLastWindowClosed(False)
    mark("qt")
    # Ctrl+C in a terminal, logout and shutdown all end the app, also while a start-up
    # dialog is open. quit() only acts once the main loop runs; until then exit() ends
    # the dialog's loop (and any later one) instead.
    main_loop_running = False

    def on_signal() -> None:
        if main_loop_running:
            app.quit()
        else:
            app.exit(0)

    watcher = SignalWatcher(on_signal)
    connection = None
    try:
        ensure_korean_font()
        mark("fonts")
        translations = Translations()
        translations.apply(None)
        mark("translations")
        if perf is not None:
            open_storage_like_startup(perf)
        if unlock is not None:
            qInstallMessageHandler(log_qt_message)
            connection = open_notes(unlock)
            if connection is None:
                return 0
            mark("notes-database")

        manager = NoteManager()
        # Without a tray there would be no way back to a hidden app, so quit with the last note.
        if not QSystemTrayIcon.isSystemTrayAvailable():
            manager.last_note_closed.connect(app.quit)
        tray = Tray(manager.new_note, app.quit, translations)
        tray.show()
        for _ in range(max(1, perf.notes if perf else 1)):
            manager.new_note()
        mark("notes")
        if perf is not None:
            # Runs once the queued show and paint events have been handled.
            QTimer.singleShot(0, lambda: report_ready(perf, manager))
        elif started is not None:
            # Includes any time spent at the password prompt.
            QTimer.singleShot(0, lambda: log.info("started: %s", ", ".join(timings)))
        main_loop_running = True
        return app.exec()
    finally:
        watcher.close()
        if connection is not None:
            connection.close()
        log.info("quit")
