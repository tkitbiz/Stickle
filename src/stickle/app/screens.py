"""Describe the connected screens as Qt sees them (the hidden --screens option).

Serial numbers are hardware identifiers: they are masked here and must only
ever be stored hashed.
"""

import os
import sys

from PySide6.QtWidgets import QApplication

from stickle.platform.linux.display import preferred_qt_platform


def mask(serial: str) -> str:
    """Enough to tell whether a serial is real (length, ends), not the serial itself."""
    if not serial.strip():
        return "(empty)"
    if set(serial.strip()) <= {"0"}:
        return f"(zeros, {len(serial)} chars)"
    if len(serial) <= 4:
        return f"{'*' * len(serial)} ({len(serial)} chars)"
    return f"{serial[:2]}{'*' * (len(serial) - 4)}{serial[-2:]} ({len(serial)} chars)"


def report(argv: list[str]) -> int:
    # The same display connection as the app itself (XWayland on Wayland sessions).
    if sys.platform == "linux" and (platform := preferred_qt_platform(os.environ)):
        argv = [argv[0], "-platform", platform, *argv[1:]]
    app = QApplication(argv)
    print(f"platform: {app.platformName()}")
    for index, screen in enumerate(app.screens()):
        geometry = screen.geometry()
        print(
            f"screen {index}: name={screen.name()!r} manufacturer={screen.manufacturer()!r}"
            f" model={screen.model()!r} serial={mask(screen.serialNumber())}"
            f" geometry={geometry.x()},{geometry.y()} {geometry.width()}x{geometry.height()}"
            f" scale={screen.devicePixelRatio():g}"
            f"{' primary' if screen == app.primaryScreen() else ''}"
        )
    return 0
