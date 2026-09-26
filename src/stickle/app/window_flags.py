"""Changing whether a window stays above others, while it is on screen."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget


def stays_on_top(widget: QWidget) -> bool:
    return bool(widget.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)


def set_stays_on_top(widget: QWidget, on_top: bool) -> None:
    """Keep a window above others, or not, without it blinking."""
    if on_top == stays_on_top(widget):
        return
    if not widget.testAttribute(Qt.WidgetAttribute.WA_WState_Created):  # never shown yet
        widget.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on_top)
        return
    # Changed on the window as it is: setWindowFlag would destroy and recreate
    # it, which hides it for a moment.
    flags = widget.windowFlags()
    if on_top:
        flags |= Qt.WindowType.WindowStaysOnTopHint
    else:
        flags &= ~Qt.WindowType.WindowStaysOnTopHint
    widget.overrideWindowFlags(flags)
    widget.windowHandle().setFlags(flags)
