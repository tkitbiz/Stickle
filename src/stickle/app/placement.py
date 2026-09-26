"""The connected monitors as stickle.core.layout sees them, and noticing when they change."""

from PySide6.QtCore import QObject, QRect, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QScreen

from stickle.core.layout import Monitor, Rect

SETTLE_MS = 500  # monitors come and go in several steps: wait for the last


def rect(value: QRect) -> Rect:
    return Rect(value.x(), value.y(), value.width(), value.height())


def qrect(value: Rect) -> QRect:
    return QRect(value.x, value.y, value.width, value.height)


def _name(screen: QScreen) -> str:
    # Windows gives the model here, Linux the connector (HDMI-1); both help to
    # find the same monitor again. Serial numbers are never used.
    return " ".join(part for part in (screen.name(), screen.model()) if part).strip()


def monitors() -> list[Monitor]:
    primary = QGuiApplication.primaryScreen()
    return [
        Monitor(
            name=_name(screen),
            geometry=rect(screen.geometry()),
            available=rect(screen.availableGeometry()),
            primary=screen == primary,
        )
        for screen in QGuiApplication.screens()
    ]


def can_place_windows() -> bool:
    """Wayland lets no application know or choose where its windows are."""
    return QGuiApplication.platformName() != "wayland"


class MonitorWatch(QObject):
    """Says once, after things settle, that monitors were connected, removed or changed."""

    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(SETTLE_MS)
        self._settle.timeout.connect(self.changed)
        app = QGuiApplication.instance()
        assert isinstance(app, QGuiApplication)
        app.screenAdded.connect(self._screen_added)
        app.screenRemoved.connect(self._settle.start)
        app.primaryScreenChanged.connect(self._settle.start)
        for screen in QGuiApplication.screens():
            self._watch(screen)

    def _screen_added(self, screen: QScreen) -> None:
        self._watch(screen)
        self._settle.start()

    def _watch(self, screen: QScreen) -> None:
        screen.geometryChanged.connect(self._settle.start)
        screen.availableGeometryChanged.connect(self._settle.start)
