"""Application start-up."""

import logging
import os
import sys
import time

from PySide6.QtCore import (
    QLocale,
    QMessageLogContext,
    QTimer,
    QtMsgType,
    qInstallMessageHandler,
)
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from stickle.app.fonts import ensure_korean_font
from stickle.app.i18n import Translations
from stickle.app.notes import NoteManager
from stickle.app.perf import PerfMode, open_storage_like_startup
from stickle.app.signals import SignalWatcher
from stickle.app.startup import open_notes
from stickle.app.tray import Tray
from stickle.data.notes import NoteRepository
from stickle.platform.linux.display import preferred_qt_platform
from stickle.platform.power import watch_sleep
from stickle.unlock import Unlock

APP_ID = "co.linkro.stickle"


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
        log.info("interface language: %s", QLocale().name())
        mark("translations")
        if perf is not None:
            open_storage_like_startup(perf)
        if unlock is not None:
            qInstallMessageHandler(log_qt_message)
            connection = open_notes(unlock)
            if connection is None:
                return 0
            mark("notes-database")

        manager = NoteManager(NoteRepository(connection) if connection else None)
        manager.watch_quit(app)
        app.aboutToQuit.connect(manager.save_all)

        # Logging out or shutting down: save first. No quitting yet, since another
        # program may still cancel the logout.
        def before_session_end(*_: object) -> None:
            log.info("saving before the session ends")
            manager.save_all()

        def before_sleep() -> None:
            log.info("saving before sleep")
            manager.save_all()

        app.commitDataRequest.connect(before_session_end)
        sleep_watch = watch_sleep(before_sleep)
        log.info("sleep %s", "watched" if sleep_watch is not None else "not watched")
        tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        # Without a tray there would be no way back to a hidden app, so quit with the last note.
        if not tray_available:
            manager.last_note_closed.connect(app.quit)
        tray = Tray(manager.new_note, app.quit, translations, manager)
        tray.show()
        if perf is not None:
            for _ in range(max(1, perf.notes)):
                manager.new_note()
        else:
            manager.open_stored(tray_available)
        mark("notes")
        if perf is not None:
            # Runs once the queued show and paint events have been handled.
            QTimer.singleShot(0, lambda: report_ready(perf, manager))
        elif started is not None:
            # Includes any time spent at the password prompt.
            QTimer.singleShot(0, lambda: log.info("started: %s", ", ".join(timings)))
        main_loop_running = True
        try:
            return app.exec()
        finally:
            del sleep_watch
    finally:
        watcher.close()
        if connection is not None:
            connection.close()
        log.info("quit")
