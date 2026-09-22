"""Application start-up and the set of open note windows."""

from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QObject, QPoint, QTranslator
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from stickle.app.note_window import NoteWindow
from stickle.app.tray import Tray

APP_ID = "co.linkro.stickle"
TRANSLATIONS_DIR = Path(__file__).resolve().parent.parent / "translations"

# New notes cascade from the top-left of the screen so they never land exactly on top of each other.
CASCADE_ORIGIN = 80
CASCADE_STEP = 32
CASCADE_LENGTH = 10


class NoteManager(QObject):
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
        window.closed.connect(lambda: self._windows.remove(window))
        self._windows.append(window)

        offset = CASCADE_ORIGIN + CASCADE_STEP * (self._created % CASCADE_LENGTH)
        self._created += 1
        area = QGuiApplication.primaryScreen().availableGeometry()
        window.move(area.topLeft() + QPoint(offset, offset))

        window.show()
        window.activateWindow()
        window.setFocus()
        return window


def install_translators(app: QApplication, locale: QLocale) -> None:
    """Load Qt's own strings (context menus, dialogs) and ours; English is the fallback."""
    sources = [
        ("qtbase", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)),
        ("stickle", str(TRANSLATIONS_DIR)),
    ]
    for name, directory in sources:
        translator = QTranslator(app)
        if translator.load(locale, name, "_", directory):
            app.installTranslator(translator)


def run(argv: list[str]) -> int:
    app = QApplication(argv)
    app.setApplicationName("Stickle")
    app.setDesktopFileName(APP_ID)
    # Without a tray there would be no way back to a hidden app, so quit with the last note.
    app.setQuitOnLastWindowClosed(not QSystemTrayIcon.isSystemTrayAvailable())
    install_translators(app, QLocale.system())

    manager = NoteManager()
    tray = Tray(manager.new_note, app.quit)
    tray.show()
    manager.new_note()
    return app.exec()
