"""Asking where to save a file or which folder to use, in the system's own dialog.

Windows and macOS: Qt shows the system's dialog. Linux: Qt, as bundled in an
AppImage, would show its own; the desktop's is asked for through its portal
(stickle.platform.linux.portal_files) and Qt's shown only where there is none.
"""

import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog, QWidget

log = logging.getLogger(__name__)

type Kind = Literal["save", "folder"]


def _from_the_desktop(
    parent: QWidget, kind: Kind, title: str, suggested: Path | None
) -> Path | Literal["unavailable"] | None:
    if not sys.platform.startswith("linux"):
        return "unavailable"
    from stickle.platform.linux.portal_files import PortalUnavailableError, choose

    window = parent.window()
    x11 = QGuiApplication.platformName() == "xcb"
    handle = f"x11:{int(window.winId()):x}" if x11 and window.isVisible() else ""
    try:
        return choose(kind, title, handle, suggested)
    except PortalUnavailableError as error:
        log.info("the desktop's file dialog is not available: %s", error)
        return "unavailable"


# The desktop's dialog: a chosen path, None if cancelled, or "unavailable".
from_the_desktop: Callable[
    [QWidget, Kind, str, Path | None], Path | Literal["unavailable"] | None
] = _from_the_desktop  # replaced in tests


def save_file_name(parent: QWidget, title: str, suggested: Path, filters: str) -> Path | None:
    """Where to save a file, suggested as its folder and name; None if cancelled."""
    chosen = from_the_desktop(parent, "save", title, suggested)
    if chosen != "unavailable":
        return chosen
    name, _ = QFileDialog.getSaveFileName(parent, title, str(suggested), filters)
    return Path(name) if name else None


def existing_folder(parent: QWidget, title: str) -> Path | None:
    """A folder to use; None if cancelled."""
    chosen = from_the_desktop(parent, "folder", title, None)
    if chosen != "unavailable":
        return chosen
    name = QFileDialog.getExistingDirectory(parent, title)
    return Path(name) if name else None
