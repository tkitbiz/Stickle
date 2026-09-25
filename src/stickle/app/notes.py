"""The open note windows, and keeping them in step with the stored notes.

A new note is stored once it has text: an untouched note that is closed
leaves nothing behind. Text is saved when it loses focus, when the note is
hidden or deleted, and when the app quits. Hiding keeps the note for later;
hiding a note whose text was all erased deletes it instead (it can still be
restored), so the hidden list never fills up with empty notes. Deleting only
marks the note.

Without a repository (measurement mode, some tests) the windows are simply
not stored.
"""

import logging
from typing import override

from PySide6.QtCore import QEvent, QObject, QPoint, Signal
from PySide6.QtGui import QGuiApplication

from stickle.app.note_window import NoteWindow
from stickle.core.note import Note
from stickle.data.notes import NoteRepository

# New notes cascade from the top-left of the screen so they never land exactly on top of each other.
CASCADE_ORIGIN = 80
CASCADE_STEP = 32
CASCADE_LENGTH = 10
HIDDEN_LISTED = 15

log = logging.getLogger(__name__)


class NoteManager(QObject):
    # Qt's own "quit on last window closed" ignores tool windows, which notes are.
    last_note_closed = Signal()
    # Hidden or deleted notes changed: menus listing them should refresh.
    changed = Signal()

    def __init__(self, repository: NoteRepository | None = None) -> None:
        super().__init__()
        self._repository = repository
        self._windows: list[NoteWindow] = []
        self._created = 0
        self._quitting = False

    @property
    def windows(self) -> tuple[NoteWindow, ...]:
        return tuple(self._windows)

    def watch_quit(self, app: QObject) -> None:
        """Save everything when the app is asked to quit, before Qt closes the windows.

        Qt closes every window on quit; without this, each note would take that
        as a request to hide, and none would come back on the next start.
        """
        app.installEventFilter(self)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Quit:
            self.prepare_to_quit()
        return super().eventFilter(watched, event)

    def prepare_to_quit(self) -> None:
        self._quitting = True
        self.save_all()
        for window in self._windows:
            window.allow_close()

    # Opening

    def open_stored(self, tray_available: bool = True) -> None:
        """Open every note that is neither hidden nor deleted.

        With no notes at all, an empty note is opened to start with. Hidden notes
        alone open nothing, unless there is no tray to bring them back from.
        """
        if self._repository is None:
            self.new_note()
            return
        visible = self._repository.visible()
        for note in visible:
            self._open(note)
        if not visible and (not self._repository.all() or not tray_available):
            self.new_note()
        log.info("opened %d notes", len(visible))

    def new_note(self) -> NoteWindow:
        return self._open(None)

    def _open(self, note: Note | None) -> NoteWindow:
        window = NoteWindow(note.id if note else None, note.body if note else "")
        window.new_note_requested.connect(self.new_note)
        window.hide_requested.connect(lambda: self.hide(window))
        window.delete_requested.connect(lambda: self.delete(window))
        window.editing_finished.connect(lambda: self.save(window))
        window.closed.connect(lambda: self._forget(window))
        self._windows.append(window)

        offset = CASCADE_ORIGIN + CASCADE_STEP * (self._created % CASCADE_LENGTH)
        self._created += 1
        area = QGuiApplication.primaryScreen().availableGeometry()
        window.move(area.topLeft() + QPoint(offset, offset))

        window.show()
        window.activateWindow()
        window.setFocus()
        return window

    def _forget(self, window: NoteWindow) -> None:
        self._windows.remove(window)
        if not self._windows and not self._quitting:
            self.last_note_closed.emit()

    # Saving

    def save(self, window: NoteWindow) -> None:
        if self._repository is None:
            return
        text = window.text
        if window.note_id is None:
            if text:
                window.note_id = self._repository.create(text).id
        else:
            self._repository.update_body(window.note_id, text)

    def save_all(self) -> None:
        for window in self._windows:
            self.save(window)

    # Hiding, deleting, bringing back

    def hide(self, window: NoteWindow) -> None:
        if self._quitting:
            window.release()
            return
        self.save(window)
        if self._repository is not None and window.note_id is not None:
            if window.text.strip():
                self._repository.set_hidden(window.note_id, True)
            else:
                self._repository.delete(window.note_id)
            self.changed.emit()
        window.release()

    def delete(self, window: NoteWindow) -> None:
        self.save(window)
        if self._repository is not None and window.note_id is not None:
            self._repository.delete(window.note_id)
            self.changed.emit()
        window.release()

    def hidden_notes(self) -> list[Note]:
        """Most recently hidden first."""
        return self._repository.hidden() if self._repository else []

    def last_deleted(self) -> Note | None:
        return self._repository.last_deleted() if self._repository else None

    def show_hidden(self, note_id: str) -> None:
        if self._repository is None:
            return
        note = self._repository.set_hidden(note_id, False)
        self._open(note)
        self.changed.emit()

    def show_all_hidden(self) -> None:
        for note in reversed(self.hidden_notes()):
            self.show_hidden(note.id)

    def restore_last_deleted(self) -> None:
        note = self.last_deleted()
        if self._repository is None or note is None:
            return
        self._repository.restore(note.id)
        # Brought back to be seen, even if it was hidden when deleted.
        note = self._repository.set_hidden(note.id, False)
        self._open(note)
        self.changed.emit()
