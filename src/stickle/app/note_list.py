"""The list of notes in the Stickle window: every note not deleted, shown or hidden.

It only reads the notes; opening, hiding and deleting go through the note
manager, as they do from a note's own window.
"""

from typing import override

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QKeyEvent
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from stickle.app.notes import NoteManager
from stickle.app.palette import swatch_icon
from stickle.core.colors import DEFAULT_COLOR, PALETTE
from stickle.core.markdown import note_title
from stickle.core.note import Note

NOTE_ID = Qt.ItemDataRole.UserRole
ALL, SHOWN, HIDDEN = "all", "shown", "hidden"
# A note's text is stored a second after typing stops; the list follows a moment later.
REFRESH_DELAY_MS = 300


class NoteList(QWidget):
    def __init__(self, notes: NoteManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._notes = notes
        self.label = QLabel(self)
        self.filter_box = QComboBox(self)
        for key in (ALL, SHOWN, HIDDEN):
            self.filter_box.addItem("", key)
        self.filter_box.currentIndexChanged.connect(self.refresh)
        self.list = QListWidget(self)
        self.label.setBuddy(self.list)
        self.list.itemActivated.connect(self._open)  # double-click or Enter
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu_at)
        self.list.installEventFilter(self)

        self._refresh_soon = QTimer(self)
        self._refresh_soon.setSingleShot(True)
        self._refresh_soon.setInterval(REFRESH_DELAY_MS)
        self._refresh_soon.timeout.connect(self.refresh)
        notes.changed.connect(self.refresh)
        notes.note_saved.connect(self._refresh_soon.start)

        top = QHBoxLayout()
        top.addWidget(self.label, 1)
        top.addWidget(self.filter_box)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addWidget(self.list, 1)
        self.retranslate()

    def retranslate(self) -> None:
        self.label.setText(self.tr("&Notes"))
        self.list.setAccessibleName(self.tr("Notes"))
        self.list.setAccessibleDescription(
            self.tr("Enter opens the note, Delete deletes it; more in the context menu.")
        )
        self.filter_box.setAccessibleName(self.tr("Show"))
        self.filter_box.setItemText(0, self.tr("All notes"))
        self.filter_box.setItemText(1, self.tr("Notes on screen"))
        self.filter_box.setItemText(2, self.tr("Hidden notes"))
        self.refresh()

    def _wanted(self, note: Note) -> bool:
        shown = self.filter_box.currentData()
        return shown == ALL or (note.hidden if shown == HIDDEN else not note.hidden)

    def _text(self, note: Note) -> str:
        title = note_title(note.body) or self.tr("(empty note)")
        states: list[str] = []
        if note.hidden:
            states.append(self.tr("hidden"))
        if not note.always_on_top:
            states.append(self.tr("not on top"))
        return " · ".join([title, *states])

    def refresh(self) -> None:
        """Show the notes as they are stored now, keeping the one selected."""
        selected = self.selected_id()
        self.list.clear()
        notes = [note for note in self._notes.listed_notes() if self._wanted(note)]
        for note in notes:
            item = QListWidgetItem(self._text(note))
            item.setIcon(swatch_icon(note.color if note.color in PALETTE else DEFAULT_COLOR))
            item.setData(NOTE_ID, note.id)
            self.list.addItem(item)
            if note.id == selected:
                self.list.setCurrentItem(item)
        if not notes:
            empty = QListWidgetItem(self.tr("No notes here"))
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(empty)
        elif self.list.currentRow() < 0:
            self.list.setCurrentRow(0)

    def selected_id(self) -> str | None:
        row = self.list.currentRow()
        note_id = self.list.item(row).data(NOTE_ID) if row >= 0 else None
        return note_id if isinstance(note_id, str) else None

    def _open(self, item: QListWidgetItem) -> None:
        note_id = item.data(NOTE_ID)
        if isinstance(note_id, str):
            self._notes.open_note(note_id)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self.list
            and event.type() == QEvent.Type.KeyPress
            and isinstance(event, QKeyEvent)
            and event.key() == Qt.Key.Key_Delete
        ):
            note_id = self.selected_id()
            if note_id is not None:
                self._notes.delete_note(note_id)
            return True
        return super().eventFilter(watched, event)

    def _menu_at(self, position: QPoint) -> None:
        item = self.list.itemAt(position)
        if item is None or not isinstance(item.data(NOTE_ID), str):
            return
        self.list.setCurrentItem(item)
        self.menu_for(item).popup(self.list.viewport().mapToGlobal(position))

    def menu_for(self, item: QListWidgetItem) -> QMenu:
        """Open, hide or show, and delete, for the note on this row."""
        note_id = str(item.data(NOTE_ID))
        note = next((n for n in self._notes.listed_notes() if n.id == note_id), None)
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        if note is not None and note.hidden:
            show = QAction(self.tr("Show"), menu)
            show.triggered.connect(lambda: self._notes.open_note(note_id))
            menu.addAction(show)
        else:
            open_action = QAction(self.tr("Open"), menu)
            open_action.triggered.connect(lambda: self._notes.open_note(note_id))
            menu.addAction(open_action)
            hide = QAction(self.tr("Hide"), menu)
            hide.triggered.connect(lambda: self._notes.hide_note(note_id))
            menu.addAction(hide)
        menu.addSeparator()
        delete = QAction(self.tr("Delete"), menu)
        delete.triggered.connect(lambda: self._notes.delete_note(note_id))
        menu.addAction(delete)
        return menu
