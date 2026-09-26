"""Application start-up."""

import logging
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import (
    QLocale,
    QMessageLogContext,
    QTimer,
    QtMsgType,
    qInstallMessageHandler,
)
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from stickle.app.app_list import icon_png, offer_app_list
from stickle.app.first_run import welcome
from stickle.app.fonts import ensure_korean_font
from stickle.app.i18n import Translations
from stickle.app.instance_server import InstanceServer
from stickle.app.notes import NoteManager
from stickle.app.perf import SAMPLE_NOTE, PerfMode, open_storage_like_startup
from stickle.app.signals import SignalWatcher
from stickle.app.startup import open_notes
from stickle.app.stickle_window import RecoveryKeys, StickleWindow
from stickle.app.tray import Tray
from stickle.data.layouts import LayoutRepository
from stickle.data.notes import NoteRepository
from stickle.data.settings import Settings
from stickle.data.startup import StartupSettings
from stickle.platform.autostart import Autostart
from stickle.platform.linux.appimage import AppMenuEntry, running_appimage
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


def connect_stickle_window(
    window: StickleWindow,
    manager: NoteManager,
    tray: Tray | None,
    quit_app: Callable[[], object],
) -> None:
    """When the Stickle window opens, and when closing it ends the app.

    With a tray, the app stays in it when every note is hidden, and clicking
    the tray icon opens the window. Without one there would be no way back,
    so the window opens saying all notes are hidden, and closing it quits.
    """
    if tray is not None:

        def tray_clicked(reason: QSystemTrayIcon.ActivationReason) -> None:
            if reason == QSystemTrayIcon.ActivationReason.Trigger:
                window.open()

        tray.activated.connect(tray_clicked)
        return

    manager.last_note_closed.connect(lambda: window.open(notice=True))

    def window_closed() -> None:
        if not manager.windows:
            quit_app()

    window.closed.connect(window_closed)

    def notes_changed() -> None:
        if manager.windows:
            window.notice.hide()  # a note is back: the notice no longer holds

    manager.changed.connect(notes_changed)


def recovery_keys(unlock: Unlock | None) -> RecoveryKeys | None:
    """Making recovery keys for the key that opened the notes (none in measurement mode)."""
    if unlock is None or unlock.opened_key is None:
        return None
    key = unlock.opened_key
    return RecoveryKeys(
        exists=lambda: unlock.has_recovery_key, make=lambda: unlock.make_recovery_key(key)
    )


def app_list_entry() -> AppMenuEntry | None:
    """For an AppImage, its entry in the application list (followed if it moved)."""
    appimage = running_appimage()
    if appimage is None:
        return None
    entry = AppMenuEntry(appimage, icon_png())
    try:
        if entry.refresh():
            log.info("the application list now points at this AppImage")
    except OSError as error:
        log.warning("could not update the application list: %s", type(error).__name__)
    return entry


def open_at_start(
    manager: NoteManager, window: StickleWindow, tray_available: bool, at_login: bool = False
) -> None:
    """Open the stored notes; with only hidden ones, the Stickle window that lists
    them, unless Stickle was started at login (it then waits in the tray)."""
    manager.open_stored()
    if not manager.windows and not (at_login and tray_available):
        window.open(notice=not tray_available)


def use_language(translations: Translations, startup: StartupSettings | None) -> None:
    """Apply the language chosen on this computer, and keep any new choice."""
    translations.apply(startup.language if startup else None)
    if startup is None:
        return

    def remember() -> None:
        try:
            startup.set_language(translations.language)
        except OSError as error:
            # The choice still applies now; it is only not kept for next time.
            log.error("could not keep the interface language: %s", type(error).__name__)

    translations.changed.connect(remember)


def run(
    argv: list[str],
    perf: PerfMode | None = None,
    unlock: Unlock | None = None,
    started: float | None = None,
    startup: StartupSettings | None = None,
    instance: Path | None = None,
    at_login: bool = False,
) -> int:
    """Run the app. In measurement mode, open perf.notes notes and print READY.

    at_login: started at login (--autostart), so no Stickle window at start.

    With unlock, the notes database is opened first (asking for a password or
    showing the recovery dialog when needed); quitting there ends the app.
    With startup, the language chosen before applies from the first window
    on, the password prompt and recovery screen included, and a new choice
    is kept there. With instance (the data folder, whose instance lock this
    process holds), a second start of Stickle brings up the Stickle window.
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
    # Listening at once: a second start may come while a password is being asked for.
    instance_server = InstanceServer(instance) if instance is not None else None
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
        use_language(translations, startup)
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

        manager = NoteManager(
            NoteRepository(connection) if connection else None,
            settings=Settings(connection) if connection else None,
            layouts=LayoutRepository(connection) if connection else None,
        )
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
        # Measuring must not touch the real login items.
        autostart = Autostart() if perf is None else None
        if autostart is not None:
            try:
                if autostart.refresh():
                    log.info("start at login now points at this Stickle")
            except OSError as error:
                log.warning("could not update start at login: %s", type(error).__name__)
        app_list = app_list_entry() if perf is None else None
        tray = Tray(manager.new_note, app.quit, translations, manager, autostart, app_list)
        tray.show()
        recovery = recovery_keys(unlock)
        stickle_window = StickleWindow(
            manager, translations, app.quit, autostart, app_list, recovery
        )
        connect_stickle_window(stickle_window, manager, tray if tray_available else None, app.quit)
        if instance_server is not None:
            instance_server.show_requested.connect(stickle_window.open)
        if perf is not None:
            for _ in range(max(1, perf.notes)):
                manager.open_unstored(SAMPLE_NOTE)
        else:
            first_start = unlock is not None and unlock.first_start and connection is not None
            if first_start and unlock is not None and connection is not None:
                opened = unlock
                key = opened.opened_key
                assert key is not None
                welcome(
                    NoteRepository(connection),
                    Settings(connection),
                    lambda: opened.make_recovery_key(key),
                    autostart,
                    app_list,
                )
            open_at_start(manager, stickle_window, tray_available, at_login)
            if instance_server is not None and instance_server.requested:
                stickle_window.open()  # started again while this one was still starting
            # At first start the welcome asked already.
            if app_list is not None and connection is not None and not (at_login or first_start):
                entry, settings = app_list, Settings(connection)
                # Once the notes are up: the first run of this AppImage.
                QTimer.singleShot(0, lambda: offer_app_list(entry, settings))
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
