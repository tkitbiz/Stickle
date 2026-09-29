"""Portable notes (a stickle-data folder next to the program) that cannot be
written: said plainly, and Stickle ends rather than keep the notes elsewhere."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from stickle.app.i18n import Translations
from stickle.data.startup import StartupSettings


def _show(parent: QWidget | None, title: str, text: str) -> None:
    QMessageBox.critical(parent, title, text)


show: Callable[[QWidget | None, str, str], None] = _show  # replaced in tests


def not_writable_text(folder: Path) -> str:
    return QCoreApplication.translate(
        "Portable",
        "Stickle cannot save notes in the folder next to it:\n%1\n\n"
        "It may be on a stick that is locked or read-only, or in a folder only an "
        "administrator can change. Move Stickle and its stickle-data folder "
        "somewhere you can save, then start it again.",
    ).replace("%1", str(folder))


def tell_not_writable(argv: list[str], folder: Path) -> int:
    """Say that the portable folder cannot be written, and end (exit code 1)."""
    app = QApplication.instance() or QApplication(argv)
    translations = Translations()
    try:
        language = StartupSettings(folder).language  # read only: the folder may be locked
    except OSError:
        language = None
    translations.apply(language)
    show(None, "Stickle", not_writable_text(folder))
    app.processEvents()  # the application is kept until the process ends
    return 1
