"""System tray icon and its menu."""

import logging
from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from stickle.app.app_list import switch_app_list
from stickle.app.i18n import LANGUAGES, Translations
from stickle.app.notes import HIDDEN_LISTED, NoteManager
from stickle.core.markdown import note_title
from stickle.core.note import Note
from stickle.platform.autostart import Autostart
from stickle.platform.linux.appimage import AppMenuEntry

log = logging.getLogger(__name__)
ICON_SIZE = 64
TITLE_LENGTH = 40


def switch_autostart(autostart: Autostart, on: bool) -> bool:
    """Turn starting at login on or off; False (and logged) if the file could not be changed."""
    try:
        if on:
            autostart.enable()
        else:
            autostart.disable()
    except OSError as error:
        log.error("could not change start at login: %s", type(error).__name__)
        return False
    return True


def menu_title(note: Note) -> str:
    """The note's title, shortened, with & kept literal (Qt reads it as a shortcut mark)."""
    title = note_title(note.body)
    if len(title) > TITLE_LENGTH:
        title = title[: TITLE_LENGTH - 1] + "…"
    return title.replace("&", "&&")


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
        notes: NoteManager | None = None,
        autostart: Autostart | None = None,
        app_list: AppMenuEntry | None = None,
    ) -> None:
        super().__init__(make_icon())
        self.setToolTip("Stickle")
        self._translations = translations
        self._notes = notes
        self._autostart = autostart
        self._app_list = app_list

        # QSystemTrayIcon does not own its menu, so keep a reference.
        self._menu = QMenu()
        self.new_note_action = self._menu.addAction("")
        self.new_note_action.triggered.connect(on_new_note)
        self.hidden_menu = self._menu.addMenu("")
        self.restore_action = self._menu.addAction("")
        self.restore_action.triggered.connect(self._restore)
        self.raise_action = self._menu.addAction("")
        self.raise_action.triggered.connect(self._raise_all)
        self._menu.addSeparator()

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
        self.autostart_action = self._menu.addAction("")
        self.autostart_action.setCheckable(True)
        self.autostart_action.setVisible(autostart is not None)
        self.autostart_action.triggered.connect(self._switch_autostart)
        # Only for an AppImage: packages add themselves to the list.
        self.app_list_action = self._menu.addAction("")
        self.app_list_action.setCheckable(True)
        self.app_list_action.setVisible(app_list is not None)
        self.app_list_action.triggered.connect(self._switch_app_list)
        # The file may have been removed in the system's own settings meanwhile.
        self._menu.aboutToShow.connect(self.refresh_switches)

        self._menu.addSeparator()
        self.quit_action = self._menu.addAction("")
        self.quit_action.triggered.connect(on_quit)
        self.setContextMenu(self._menu)
        self.refresh_switches()

        # Not a widget, so no LanguageChange event: follow the translations instead.
        translations.changed.connect(self.retranslate)
        if notes is not None:
            notes.changed.connect(self.refresh_notes)
        self.retranslate()

    def refresh_notes(self) -> None:
        """Rebuild the lists of hidden and deleted notes (they change only through the app)."""
        self.hidden_menu.clear()
        hidden = self._notes.hidden_notes() if self._notes else []
        for note in hidden[:HIDDEN_LISTED]:
            action = self.hidden_menu.addAction(menu_title(note) or self.tr("(empty note)"))
            action.triggered.connect(lambda _=False, note_id=note.id: self._show(note_id))
        if hidden:
            self.hidden_menu.addSeparator()
        show_all = self.hidden_menu.addAction(self.tr("Show all hidden notes"))
        show_all.triggered.connect(self._show_all)
        self.hidden_menu.setEnabled(bool(hidden))

        deleted = self._notes.last_deleted() if self._notes else None
        self.restore_action.setEnabled(deleted is not None)
        if deleted is None:
            self.restore_action.setText(self.tr("Restore the note just deleted"))
        else:
            title = menu_title(deleted) or self.tr("(empty note)")
            self.restore_action.setText(
                self.tr("Restore the note just deleted: %1").replace("%1", title)
            )

    def _show(self, note_id: str) -> None:
        if self._notes:
            self._notes.show_hidden(note_id)

    def _show_all(self) -> None:
        if self._notes:
            self._notes.show_all_hidden()

    def _restore(self) -> None:
        if self._notes:
            self._notes.restore_last_deleted()

    def refresh_switches(self) -> None:
        """Show what the files say (they may have changed outside Stickle)."""
        if self._autostart is not None:
            self.autostart_action.setChecked(self._autostart.enabled)
        if self._app_list is not None:
            self.app_list_action.setChecked(self._app_list.added)

    def _switch_app_list(self, on: bool) -> None:
        if self._app_list is not None:
            switch_app_list(self._app_list, on)
        self.refresh_switches()

    def _switch_autostart(self, on: bool) -> None:
        if self._autostart is not None:
            switch_autostart(self._autostart, on)
        self.refresh_switches()

    def _raise_all(self) -> None:
        if self._notes:
            self._notes.raise_all()

    def retranslate(self) -> None:
        self.new_note_action.setText(self.tr("New note"))
        self.hidden_menu.setTitle(self.tr("Hidden notes"))
        self.raise_action.setText(self.tr("Bring all notes to front"))
        self.refresh_notes()
        self.language_menu.setTitle(self.tr("Language"))
        self.language_actions[None].setText(self.tr("System language"))
        if chosen := self.language_actions.get(self._translations.language):
            chosen.setChecked(True)
        self.quit_action.setText(self.tr("Quit Stickle"))
        self.autostart_action.setText(self.tr("Start Stickle when I log in"))
        self.app_list_action.setText(self.tr("Show Stickle in the app list"))
