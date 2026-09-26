"""The Stickle window: what the tray menu offers, in a window of its own.

It opens when Stickle starts with only hidden notes, when it is started
again while already running, and, where there is no tray, when the last
note is hidden: then it says so, and closing it ends Stickle. It will grow
into the list of all notes.
"""

from collections.abc import Callable
from typing import override

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from stickle.app.i18n import LANGUAGES, Translations
from stickle.app.notes import HIDDEN_LISTED, NoteManager
from stickle.app.tray import switch_autostart
from stickle.core.markdown import note_title
from stickle.platform.autostart import Autostart

NOTE_ID = Qt.ItemDataRole.UserRole


class StickleWindow(QWidget):
    closed = Signal()  # the user closed the window

    def __init__(
        self,
        notes: NoteManager,
        translations: Translations,
        on_quit: Callable[[], object],
        autostart: Autostart | None = None,
    ) -> None:
        super().__init__()
        self._notes = notes
        self._translations = translations
        self._autostart = autostart
        self.setMinimumWidth(320)

        self.autostart_box = QCheckBox(self)
        self.autostart_box.setVisible(autostart is not None)
        self.autostart_box.clicked.connect(self._switch_autostart)

        # Shown only when there is no tray and every note was hidden.
        self.notice = QLabel(self)
        self.notice.setWordWrap(True)
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
        layout.addWidget(self.quit_button)

        notes.changed.connect(self.refresh)
        translations.changed.connect(self.retranslate)
        self.retranslate()

    def retranslate(self) -> None:
        self.setWindowTitle("Stickle")
        self.notice.setText(
            self.tr(
                "All notes are hidden. Closing this window quits Stickle; the hidden "
                "notes are listed below, and here again the next time you start it."
            )
        )
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

    def _switch_autostart(self, on: bool) -> None:
        if self._autostart is not None:
            switch_autostart(self._autostart, on)
            self.autostart_box.setChecked(self._autostart.enabled)

    def open(self, notice: bool = False) -> None:
        """Show the window in front, with the "all notes are hidden" notice or not."""
        self.notice.setVisible(notice)
        self.refresh()
        self.showNormal()
        self.raise_()
        self.activateWindow()

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
