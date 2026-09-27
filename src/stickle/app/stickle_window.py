"""The Stickle window: what the tray menu offers, in a window of its own.

It opens when Stickle starts with only hidden notes, when it is started
again while already running, and, where there is no tray, when the last
note is hidden: then it says so, and closing it ends Stickle. It will grow
into the list of all notes.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QCloseEvent, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from stickle.app.app_list import switch_app_list
from stickle.app.i18n import LANGUAGES, Translations
from stickle.app.notes import HIDDEN_LISTED, NoteManager
from stickle.app.recovery_key_dialog import RecoveryKeyDialog
from stickle.app.tray import switch_autostart
from stickle.app.window_flags import set_stays_on_top, stays_on_top
from stickle.core.markdown import note_title
from stickle.platform.autostart import Autostart
from stickle.platform.linux.appimage import AppMenuEntry
from stickle.platform.linux.x11 import activate

NOTE_ID = Qt.ItemDataRole.UserRole
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecoveryKeys:
    """Making the recovery key, without the window knowing the database key."""

    exists: Callable[[], bool]
    make: Callable[[], str]  # a new one, the old one no longer working
    kept: Callable[[], None]  # the user said the new one is kept somewhere safe


def _exec(dialog: RecoveryKeyDialog) -> bool:
    return dialog.exec() == RecoveryKeyDialog.DialogCode.Accepted


show_recovery_key: Callable[[RecoveryKeyDialog], bool] = _exec  # replaced in tests


class StickleWindow(QWidget):
    closed = Signal()  # the user closed the window

    def __init__(
        self,
        notes: NoteManager,
        translations: Translations,
        on_quit: Callable[[], object],
        autostart: Autostart | None = None,
        app_list: AppMenuEntry | None = None,
        recovery: RecoveryKeys | None = None,
    ) -> None:
        super().__init__()
        self._notes = notes
        self._translations = translations
        self._autostart = autostart
        self._app_list = app_list
        self._recovery = recovery
        self.setMinimumWidth(320)

        self.autostart_box = QCheckBox(self)
        self.autostart_box.setVisible(autostart is not None)
        self.autostart_box.clicked.connect(self._switch_autostart)
        self.app_list_box = QCheckBox(self)
        self.app_list_box.setVisible(app_list is not None)
        self.app_list_box.clicked.connect(self._switch_app_list)
        self.recovery_button = QPushButton(self)
        self.recovery_button.setVisible(recovery is not None)
        self.recovery_button.clicked.connect(self.new_recovery_key)

        # Shown only when there is no tray and every note was hidden: the window
        # then opened by itself, so it says why at the top, where it is seen, and
        # offers the two ways on (a single line was passed over in testing).
        self.notice = QFrame(self)
        self.notice.setObjectName("notice")
        self.notice.setStyleSheet(
            "QFrame#notice { border: 2px solid palette(highlight); border-radius: 6px; }"
        )
        self.notice_heading = QLabel(self.notice)
        heading_font = QFont(self.notice_heading.font())
        heading_font.setBold(True)
        heading_font.setPointSizeF(heading_font.pointSizeF() * 1.2)
        self.notice_heading.setFont(heading_font)
        self.notice_text = QLabel(self.notice)
        self.notice_text.setWordWrap(True)
        self.notice_show_button = QPushButton(self.notice)
        self.notice_show_button.clicked.connect(notes.show_all_hidden)
        self.notice_quit_button = QPushButton(self.notice)
        self.notice_quit_button.clicked.connect(on_quit)
        notice_buttons = QHBoxLayout()
        notice_buttons.addWidget(self.notice_show_button)
        notice_buttons.addWidget(self.notice_quit_button)
        notice_layout = QVBoxLayout(self.notice)
        notice_layout.addWidget(self.notice_heading)
        notice_layout.addWidget(self.notice_text)
        notice_layout.addLayout(notice_buttons)
        self.notice.hide()

        self.new_note_button = QPushButton(self)
        self.new_note_button.clicked.connect(notes.new_note)
        self.raise_button = QPushButton(self)
        self.raise_button.clicked.connect(notes.raise_all)

        self.hidden_label = QLabel(self)
        self.hidden_list = QListWidget(self)
        self.hidden_label.setBuddy(self.hidden_list)
        self.hidden_list.itemActivated.connect(self._show_note)
        self.show_all_button = QPushButton(self)
        self.show_all_button.clicked.connect(notes.show_all_hidden)
        self.restore_button = QPushButton(self)
        self.restore_button.clicked.connect(notes.restore_last_deleted)

        self.language_label = QLabel(self)
        self.language_box = QComboBox(self)
        self.language_label.setBuddy(self.language_box)
        for code, native_name in LANGUAGES:
            self.language_box.addItem(native_name, code)
        self.language_box.activated.connect(self._choose_language)
        self.quit_button = QPushButton(self)
        self.quit_button.clicked.connect(on_quit)

        buttons = QHBoxLayout()
        buttons.addWidget(self.new_note_button)
        buttons.addWidget(self.raise_button)
        language = QHBoxLayout()
        language.addWidget(self.language_label)
        language.addWidget(self.language_box, 1)
        layout = QVBoxLayout(self)
        layout.addWidget(self.notice)
        layout.addLayout(buttons)
        layout.addWidget(self.hidden_label)
        layout.addWidget(self.hidden_list, 1)
        layout.addWidget(self.show_all_button)
        layout.addWidget(self.restore_button)
        layout.addLayout(language)
        layout.addWidget(self.autostart_box)
        layout.addWidget(self.app_list_box)
        layout.addWidget(self.recovery_button)
        layout.addWidget(self.quit_button)

        notes.changed.connect(self.refresh)
        translations.changed.connect(self.retranslate)
        self.retranslate()

    def retranslate(self) -> None:
        self._set_title()
        self.notice_heading.setText(self.tr("All notes are hidden"))
        self.notice_text.setText(
            self.tr(
                "Closing this window quits Stickle. The hidden notes are listed below, "
                "and here again the next time you start it."
            )
        )
        self.notice_show_button.setText(self.tr("Show all hidden notes"))
        self.notice_quit_button.setText(self.tr("Quit Stickle"))
        self.new_note_button.setText(self.tr("New note"))
        self.raise_button.setText(self.tr("Bring all notes to front"))
        self.hidden_label.setText(self.tr("&Hidden notes"))
        self.hidden_list.setAccessibleName(self.tr("Hidden notes"))
        self.show_all_button.setText(self.tr("Show all hidden notes"))
        self.language_label.setText(self.tr("&Language"))
        self.language_box.setAccessibleName(self.tr("Language"))
        self.language_box.setItemText(0, self.tr("System language"))
        self.quit_button.setText(self.tr("Quit Stickle"))
        self.autostart_box.setText(self.tr("&Start Stickle when I log in"))
        self.app_list_box.setText(self.tr("Show Stickle in the &app list"))
        self.recovery_button.setText(self.tr("Make a new &recovery key…"))
        self.refresh()

    @override
    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()
        super().changeEvent(event)

    def refresh(self) -> None:
        """Show the current hidden notes, note just deleted and language."""
        self.hidden_list.clear()
        hidden = self._notes.hidden_notes()
        for note in hidden[:HIDDEN_LISTED]:
            item = QListWidgetItem(note_title(note.body) or self.tr("(empty note)"))
            item.setData(NOTE_ID, note.id)
            self.hidden_list.addItem(item)
        if not hidden:
            self.hidden_list.addItem(self.tr("No hidden notes"))
        self.hidden_list.setEnabled(bool(hidden))
        self.show_all_button.setEnabled(bool(hidden))

        deleted = self._notes.last_deleted()
        self.restore_button.setEnabled(deleted is not None)
        if deleted is None:
            self.restore_button.setText(self.tr("Restore the note just deleted"))
        else:
            title = note_title(deleted.body) or self.tr("(empty note)")
            self.restore_button.setText(
                self.tr("Restore the note just deleted: %1").replace("%1", title)
            )
        self.language_box.setCurrentIndex(
            max(0, self.language_box.findData(self._translations.language))
        )
        if self._autostart is not None:
            self.autostart_box.setChecked(self._autostart.enabled)
        if self._app_list is not None:
            self.app_list_box.setChecked(self._app_list.added)

    def new_recovery_key(self) -> None:
        """Make a new recovery key and show it; the previous one stops working."""
        if self._recovery is None:
            return
        if self._recovery.exists():
            answer = QMessageBox.question(
                self,
                "Stickle",
                self.tr(
                    "Make a new recovery key? The one you have now will no longer open your notes."
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            recovery_key = self._recovery.make()
        except OSError as error:
            log.error("could not make a recovery key: %s", type(error).__name__)
            QMessageBox.warning(self, "Stickle", self.tr("The recovery key could not be saved."))
            return
        if show_recovery_key(RecoveryKeyDialog(recovery_key, self)):
            self._recovery.kept()

    def _switch_app_list(self, on: bool) -> None:
        if self._app_list is not None:
            switch_app_list(self._app_list, on)
            self.app_list_box.setChecked(self._app_list.added)

    def _switch_autostart(self, on: bool) -> None:
        if self._autostart is not None:
            switch_autostart(self._autostart, on)
            self.autostart_box.setChecked(self._autostart.enabled)

    def show_notice(self, shown: bool) -> None:
        """The "all notes are hidden" notice, in the window and its title."""
        self.notice.setVisible(shown)
        self._set_title()

    def _set_title(self) -> None:
        if self.notice.isVisibleTo(self):
            self.setWindowTitle(self.tr("All notes are hidden - Stickle"))
        else:
            self.setWindowTitle("Stickle")

    def open(self, notice: bool = False) -> None:
        """Show the window in front, with the "all notes are hidden" notice or not."""
        self.show_notice(notice)
        self.refresh()
        # Window managers may refuse to hand over the keyboard to a window
        # asked for by another program (a second start): kept above the others
        # until the user moves on from it, it is at least seen.
        set_stays_on_top(self, True)
        self.showNormal()
        self.raise_()
        self.activateWindow()
        if QGuiApplication.platformName() == "xcb":
            # Asked for as a taskbar would; the application's own request above
            # may be refused.
            activate(int(self.winId()))

    @override
    def event(self, event: QEvent) -> bool:
        # Not on activation: that can be reported before the window is in front.
        if (
            event.type() == QEvent.Type.WindowDeactivate or event.type() == QEvent.Type.Hide
        ) and stays_on_top(self):
            set_stays_on_top(self, False)
        return super().event(event)

    def _show_note(self, item: QListWidgetItem) -> None:
        note_id = item.data(NOTE_ID)
        if isinstance(note_id, str):
            self._notes.show_hidden(note_id)

    def _choose_language(self, index: int) -> None:
        code = self.language_box.itemData(index)
        self._translations.apply(code if isinstance(code, str) else None)

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        super().closeEvent(event)
        self.closed.emit()
