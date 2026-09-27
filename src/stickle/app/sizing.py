"""Making a window tall enough for text that has just appeared."""

from PySide6.QtWidgets import QLabel, QWidget

ROUNDS = 3  # each round gives the wrapped text what it still lacks


def grow_to_fit(window: QWidget) -> None:
    """Grow a window that is already sized, so wrapped text shown since is not cut off.

    Qt keeps a window's size when a label that wraps appears or changes in it,
    and its own estimate of the height needed can fall short, so the label's
    last lines ended up hidden. The window grows by what the labels lack.
    """
    layout = window.layout()
    if layout is None:
        return
    layout.activate()
    needed = max(window.heightForWidth(window.width()), window.sizeHint().height())
    if needed > window.height():
        window.resize(window.width(), needed)
    for _ in range(ROUNDS):
        layout.activate()
        lacking = max((_lacking(label) for label in window.findChildren(QLabel)), default=0)
        if lacking <= 0:
            return
        window.resize(window.width(), window.height() + lacking)


def _lacking(label: QLabel) -> int:
    if not label.wordWrap() or not label.isVisibleTo(label.window()):
        return 0
    return label.heightForWidth(label.width()) - label.height()
