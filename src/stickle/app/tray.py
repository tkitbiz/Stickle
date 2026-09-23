"""System tray icon and its menu."""

from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from stickle.app.i18n import LANGUAGES, Translations

ICON_SIZE = 64


def make_icon() -> QIcon:
    """Placeholder icon drawn in code until the real artwork exists."""
    pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(150, 120, 20), 4))
    painter.setBrush(QColor(255, 220, 90))
    painter.drawRoundedRect(QRectF(6, 6, ICON_SIZE - 12, ICON_SIZE - 12), 8, 8)
    painter.end()
    return QIcon(pixmap)


class Tray(QSystemTrayIcon):
    def __init__(
        self,
        on_new_note: Callable[[], object],
        on_quit: Callable[[], object],
        translations: Translations,
    ) -> None:
        super().__init__(make_icon())
        self.setToolTip("Stickle")
        self._translations = translations

        # QSystemTrayIcon does not own its menu, so keep a reference.
        self._menu = QMenu()
        self.new_note_action = self._menu.addAction("")
        self.new_note_action.triggered.connect(on_new_note)

        self.language_menu = self._menu.addMenu("")
        self.language_actions: dict[str | None, QAction] = {}
        group = QActionGroup(self.language_menu)
        for code, native_name in LANGUAGES:
            action = self.language_menu.addAction(native_name)
            action.setCheckable(True)
            action.setChecked(code == translations.language)
            action.triggered.connect(lambda _=False, code=code: translations.apply(code))
            group.addAction(action)
            self.language_actions[code] = action

        self._menu.addSeparator()
        self.quit_action = self._menu.addAction("")
        self.quit_action.triggered.connect(on_quit)
        self.setContextMenu(self._menu)

        # Not a widget, so no LanguageChange event: follow the translations instead.
        translations.changed.connect(self.retranslate)
        self.retranslate()

    def retranslate(self) -> None:
        self.new_note_action.setText(self.tr("New note"))
        self.language_menu.setTitle(self.tr("Language"))
        self.language_actions[None].setText(self.tr("System language"))
        if chosen := self.language_actions.get(self._translations.language):
            chosen.setChecked(True)
        self.quit_action.setText(self.tr("Quit Stickle"))
