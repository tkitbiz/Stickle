"""The open note windows, and keeping them in step with the stored notes.

A new note is stored once it has text: an untouched note that is closed
leaves nothing behind. Text is saved a second after typing stops, at least
every five seconds while typing goes on, when it loses focus, when the note
is hidden or deleted, and before the app quits, the session ends or the
computer sleeps. A character still being composed by an input method is
saved once it is committed; hiding, quitting and sleeping ask the input
method to commit it first. If saving fails, the text stays in the window, a
mark in its title bar says so, and saving is tried again. Hiding keeps the note for later;
hiding a note whose text was all erased deletes it instead (it can still be
restored), so the hidden list never fills up with empty notes. Deleting only
marks the note.

Where each note is, and its size, is kept once moving or resizing stops, and
before it is hidden or the app quits (see stickle.core.layout); a stored note
opens where it was, and notes are put back when monitors come or go.

Without a repository (measurement mode, some tests) the windows are simply
not stored.
"""

import logging
from collections.abc import Callable
from dataclasses import replace
from typing import override

import apsw
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QTimer, Signal
from PySide6.QtGui import QGuiApplication

from stickle.app.note_window import NoteWindow
from stickle.app.placement import MonitorWatch, can_place_windows, monitors, qrect, rect
from stickle.core.layout import MAIN, Place, fit, monitor_at, remember, restore
from stickle.core.note import DEFAULT_COLOR, Note
from stickle.data.layouts import LayoutRepository
from stickle.data.notes import NoteRepository
from stickle.data.settings import DEFAULT_NOTE_COLOR, Settings

# New notes cascade from the top-left of the screen so they never land exactly on top of each other.
CASCADE_ORIGIN = 80
CASCADE_STEP = 32
CASCADE_LENGTH = 10
HIDDEN_LISTED = 15
IDLE_MS = 1000  # save this long after typing stops
MAX_MS = 5000  # and at least this often while typing goes on
RETRY_FIRST_MS = 1000
RETRY_MAX_MS = 30_000

log = logging.getLogger(__name__)


def _single_shot(parent: QObject, interval: int, action: Callable[[], object]) -> QTimer:
    timer = QTimer(parent)
    timer.setSingleShot(True)
    timer.setInterval(interval)
    timer.timeout.connect(action)
    return timer


class AutoSave(QObject):
    """When to save one note. No timer runs while nothing is waiting to be saved."""

    def __init__(
        self, save: Callable[[], bool], idle_ms: int, max_ms: int, parent: QObject
    ) -> None:
        super().__init__(parent)
        self._save = save
        self._idle = _single_shot(self, idle_ms, self.save_now)
        self._max = _single_shot(self, max_ms, self.save_now)
        self._retry = _single_shot(self, RETRY_FIRST_MS, self.save_now)
        self._backoff = RETRY_FIRST_MS

    def changed(self) -> None:
        if not self._max.isActive():
            self._max.start()
        self._idle.start()

    def save_now(self) -> bool:
        self.stop()
        if self._save():
            self._backoff = RETRY_FIRST_MS
            return True
        self._retry.start(self._backoff)
        self._backoff = min(self._backoff * 2, RETRY_MAX_MS)
        return False

    def stop(self) -> None:
        for timer in (self._idle, self._max, self._retry):
            timer.stop()

    @property
    def waiting(self) -> bool:
        return any(timer.isActive() for timer in (self._idle, self._max, self._retry))


class NoteManager(QObject):
    # Qt's own "quit on last window closed" ignores tool windows, which notes are.
    last_note_closed = Signal()
    # Hidden or deleted notes changed: menus listing them should refresh.
    changed = Signal()
    # A new note was stored for the first time.
    note_created = Signal()

    def __init__(
        self,
        repository: NoteRepository | None = None,
        idle_ms: int = IDLE_MS,
        max_ms: int = MAX_MS,
        settings: Settings | None = None,
        layouts: LayoutRepository | None = None,
    ) -> None:
        super().__init__()
        self._repository = repository
        self._settings = settings
        self._layouts = layouts
        self._monitor_watch = MonitorWatch(self)
        self._monitor_watch.changed.connect(self.place_all)
        self._idle_ms = idle_ms
        self._max_ms = max_ms
        self._windows: list[NoteWindow] = []
        self._autosaves: dict[NoteWindow, AutoSave] = {}
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
        for window in self._windows:
            self.flush(window, closing=True)
        for window in self._windows:
            window.allow_close()

    # Opening

    def open_stored(self) -> None:
        """Open every note that is neither hidden nor deleted.

        With no notes at all, an empty note is opened to start with. Hidden notes
        alone open nothing: the app shows the Stickle window, which lists them.
        """
        if self._repository is None:
            self.new_note()
            return
        visible = self._repository.visible()
        for note in visible:
            self._open(note)
        if not visible and not self._repository.all():
            self.new_note()
        log.info("opened %d notes", len(visible))

    def new_note(self) -> NoteWindow:
        return self._open(None)

    def open_unstored(self, text: str) -> NoteWindow:
        """A note with text that is not stored until it changes (measurement mode)."""
        return self._open(None, text)

    def _open(self, note: Note | None, text: str = "") -> NoteWindow:
        if note is not None:
            window = NoteWindow(note.id, note.body, note.color, note.always_on_top)
        else:
            window = NoteWindow(None, text, self._new_note_color())
        window.new_note_requested.connect(self.new_note)

        def color_requested(color: str) -> None:
            self.set_color(window, color)

        window.color_requested.connect(color_requested)

        def collapse_requested(collapsed: bool) -> None:
            self.set_collapsed(window, collapsed)

        window.collapse_requested.connect(collapse_requested)

        def on_top_requested(on_top: bool) -> None:
            self.set_always_on_top(window, on_top)

        window.on_top_requested.connect(on_top_requested)
        window.hide_requested.connect(lambda: self.hide(window))
        window.delete_requested.connect(lambda: self.delete(window))
        autosave = AutoSave(lambda: self.save(window), self._idle_ms, self._max_ms, window)
        self._autosaves[window] = autosave
        window.text_changed.connect(autosave.changed)
        window.editing_finished.connect(autosave.save_now)
        window.retry_requested.connect(autosave.save_now)
        window.closed.connect(lambda: self._forget(window))
        window.geometry_settled.connect(lambda: self.save_layout(window))
        self._windows.append(window)

        if not self._restore_place(window):
            offset = CASCADE_ORIGIN + CASCADE_STEP * (self._created % CASCADE_LENGTH)
            self._created += 1
            area = QGuiApplication.primaryScreen().availableGeometry()
            window.place(QRect(area.topLeft() + QPoint(offset, offset), window.size()))
        if note is not None and note.collapsed:
            window.set_collapsed(True)
            window.mark_placed()

        window.show()
        window.activateWindow()
        window.setFocus()
        return window

    def _forget(self, window: NoteWindow) -> None:
        self._windows.remove(window)
        self._autosaves.pop(window).stop()
        if not self._windows and not self._quitting:
            self.last_note_closed.emit()

    # Saving

    def save(self, window: NoteWindow) -> bool:
        """Store the window's text; False (and the window says so) if that failed."""
        if self._repository is None:
            return True
        text = window.text
        try:
            if window.note_id is None:
                if text:
                    window.note_id = self._repository.create(text, window.color).id
                    self.note_created.emit()
                    self.save_layout(window, force=True)
                    if window.collapsed:
                        self._repository.set_collapsed(window.note_id, True)
                    if not window.always_on_top:
                        self._repository.set_always_on_top(window.note_id, False)
            else:
                self._repository.update_body(window.note_id, text)
        except (apsw.Error, OSError) as error:
            log.error("could not save a note: %s", type(error).__name__)
            window.set_unsaved(True)
            return False
        window.set_unsaved(False)
        return True

    def flush(self, window: NoteWindow, closing: bool = False) -> bool:
        """Save now, with the character being composed (see finish_composition),
        and where the note is if it was just moved."""
        window.finish_composition(closing)
        self.save_layout(window)
        return self._autosaves[window].save_now()

    # Where notes are

    def _places(self, window: NoteWindow) -> dict[str, Place]:
        if self._layouts is None or window.note_id is None:
            return {}
        return self._layouts.places(window.note_id)

    def _restore_place(self, window: NoteWindow) -> bool:
        """Put a stored note where it was; False if nothing is remembered."""
        places = self._places(window)
        if not can_place_windows():
            # Only the size can be kept: the window system decides where windows go.
            if MAIN in places:
                window.resize(places[MAIN].width, places[MAIN].height)
            return False
        placement = restore(places, monitors())
        if placement is None:
            return False
        window.place(qrect(placement.window), placement.own_monitor)
        return True

    def save_layout(self, window: NoteWindow, force: bool = False) -> None:
        """Remember where the note is, if the user moved or resized it (or force)."""
        if self._layouts is None or window.note_id is None:
            return
        if not force and not window.moved_by_user:
            return
        places = self._places(window)
        if can_place_windows():
            window_rect = rect(window.expanded_geometry())  # folded or not, the full size
            places = remember(places, window_rect, monitors(), window.own_monitor)
        elif MAIN in places:
            size = {"width": window.width(), "height": window.height()}
            places = {slot: replace(place, **size) for slot, place in places.items()}
        else:
            return
        try:
            self._layouts.save(window.note_id, places)
        except apsw.Error as error:
            log.error("could not store where a note is: %s", type(error).__name__)
            return
        window.mark_placed()

    def place_all(self) -> None:
        """Monitors were connected, removed or changed: put every note where it belongs."""
        if not can_place_windows():
            return
        current = monitors()
        for window in self._windows:
            if self._restore_place(window):
                continue
            # Not remembered yet: at least keep it on a monitor.
            where = rect(window.expanded_geometry())
            _, monitor = monitor_at(where, current)
            window.place(qrect(fit(where, monitor.available)), window.own_monitor)
        log.info("monitors changed: %d notes on %d monitors", len(self._windows), len(current))

    def save_all(self) -> None:
        """Save every note that stays open (logout, sleep)."""
        for window in self._windows:
            self.flush(window)

    # Staying on top

    def set_always_on_top(self, window: NoteWindow, on_top: bool) -> None:
        """Keep a note above other windows or not. If that cannot be stored,
        the note stays as it was (the pin shows so)."""
        if self._repository is not None and window.note_id is not None:
            try:
                self._repository.set_always_on_top(window.note_id, on_top)
            except apsw.Error as error:
                log.error("could not store a note staying on top: %s", type(error).__name__)
                window.set_always_on_top(window.always_on_top)
                return
        window.set_always_on_top(on_top)
        window.mark_placed()  # the window system may have nudged it: not the user's move

    def raise_all(self) -> None:
        """Bring every open note in front of other windows (notes not on top get covered)."""
        for window in self._windows:
            window.show()
            window.raise_()
        if self._windows:
            self._windows[-1].activateWindow()

    # Folding

    def set_collapsed(self, window: NoteWindow, collapsed: bool) -> None:
        """Fold a note to its title bar, or unfold it (kept on screen)."""
        if collapsed:
            # Like hiding: the text goes out of sight, and some input methods
            # drop a character still being composed.
            self.flush(window, closing=True)
        window.set_collapsed(collapsed)
        if not collapsed and can_place_windows():
            where = rect(window.geometry())
            _, monitor = monitor_at(where, monitors())
            fitted = fit(where, monitor.available)
            if fitted != where:
                window.place(qrect(fitted), window.own_monitor)
        window.mark_placed()  # folding is not moving: the remembered place stays
        if self._repository is None or window.note_id is None:
            return
        try:
            self._repository.set_collapsed(window.note_id, collapsed)
        except apsw.Error as error:
            log.error("could not store a note being folded: %s", type(error).__name__)

    # Colour

    def _new_note_color(self) -> str:
        return self._settings.get(DEFAULT_NOTE_COLOR) if self._settings else DEFAULT_COLOR

    def set_color(self, window: NoteWindow, color: str) -> None:
        """Give the note a palette colour, which new notes then take too.

        A note that is not stored yet takes the colour when it is first stored.
        If storing fails the note keeps its colour, as nothing changed.
        """
        try:
            if self._repository is not None and window.note_id is not None:
                self._repository.set_color(window.note_id, color)
            if self._settings is not None:
                self._settings.set(DEFAULT_NOTE_COLOR, color)
        except apsw.Error as error:
            log.error("could not store a note colour: %s", type(error).__name__)
            window.set_color(window.color)  # the menu shows the colour kept
            return
        window.set_color(color)

    # Hiding, deleting, bringing back

    def hide(self, window: NoteWindow) -> None:
        if self._quitting:
            window.release()
            return
        # A note that could not be saved stays open: closing it would lose the text.
        if not self.flush(window, closing=True):
            return
        if self._repository is not None and window.note_id is not None:
            try:
                if window.text.strip():
                    self._repository.set_hidden(window.note_id, True)
                else:
                    self._repository.delete(window.note_id)
            except apsw.Error as error:
                log.error("could not hide a note: %s", type(error).__name__)
                return
            self.changed.emit()
        self._autosaves[window].stop()
        window.release()

    def delete(self, window: NoteWindow) -> None:
        if not self.flush(window, closing=True):
            return
        if self._repository is not None and window.note_id is not None:
            try:
                self._repository.delete(window.note_id)
            except apsw.Error as error:
                log.error("could not delete a note: %s", type(error).__name__)
                return
            self.changed.emit()
        self._autosaves[window].stop()
        window.release()

    def waiting_to_save(self) -> bool:
        return any(autosave.waiting for autosave in self._autosaves.values())

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
