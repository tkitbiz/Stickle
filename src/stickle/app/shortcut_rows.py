"""Changing the shortcuts in the Stickle window: one row per action, each with
what holds for it now (another app has it, or it cannot be used)."""

import re
from functools import partial
from typing import override

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWidgets import QGridLayout, QKeySequenceEdit, QLabel, QWidget

from stickle.app.shortcuts import GlobalShortcuts, Refused, State
from stickle.data.settings import SHORTCUT_ACTIONS


def plain_name(label: str) -> str:
    """A label as a screen reader should say it: no shortcut mark, no colon.

    Korean writes the mark after the words, in brackets: "새 메모(&E):".
    """
    return re.sub(r"\(&.\)", "", label).replace("&", "").strip().rstrip(":").strip()


class ShortcutRows(QWidget):
    def __init__(self, shortcuts: GlobalShortcuts, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._shortcuts = shortcuts
        self._refused: dict[str, str] = {}  # action: why the last change was not taken
        self._showing = False  # putting the stored combination in: not the user's change
        self.heading = QLabel(self)
        font = QFont(self.heading.font())
        font.setBold(True)
        self.heading.setFont(font)
        self.unavailable = QLabel(self)
        self.unavailable.setWordWrap(True)
        self.unavailable.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.names: dict[str, QLabel] = {}
        self.edits: dict[str, QKeySequenceEdit] = {}
        self.notes: dict[str, QLabel] = {}
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.addWidget(self.heading, 0, 0, 1, 2)
        grid.addWidget(self.unavailable, 1, 0, 1, 2)
        for row, action in enumerate(SHORTCUT_ACTIONS):
            name = QLabel(self)
            edit = QKeySequenceEdit(self)
            edit.setMaximumSequenceLength(1)
            edit.setClearButtonEnabled(True)
            name.setBuddy(edit)
            note = QLabel(self)
            note.setWordWrap(True)
            edit.editingFinished.connect(partial(self._chosen, action))
            edit.keySequenceChanged.connect(partial(self._cleared, action))
            grid.addWidget(name, 2 + row * 2, 0)
            grid.addWidget(edit, 2 + row * 2, 1)
            grid.addWidget(note, 3 + row * 2, 1)
            self.names[action], self.edits[action], self.notes[action] = name, edit, note
        grid.setColumnStretch(1, 1)
        shortcuts.changed.connect(self.refresh)
        self.retranslate()

    def retranslate(self) -> None:
        self.heading.setText(self.tr("Shortcuts from anywhere"))
        self.unavailable.setText(
            self.tr(
                "Stickle cannot set shortcuts on this desktop. In your keyboard settings, "
                "give a shortcut to Stickle started with --new-note, --show or --hide-all."
            )
        )
        names = {
            "new-note": self.tr("New not&e:"),  # N is the list of notes'
            "show": self.tr("Stickle &window:"),
            "hide-all": self.tr("&Hide all notes for now:"),
        }
        for action, text in names.items():
            self.names[action].setText(text)
            self.edits[action].setAccessibleName(plain_name(text))
        self.refresh()

    @override
    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()
        super().changeEvent(event)

    def refresh(self) -> None:
        available = self._shortcuts.available
        self.unavailable.setVisible(not available)
        for action in SHORTCUT_ACTIONS:
            for part in (self.names[action], self.edits[action]):
                part.setVisible(available)
            self._showing = True
            try:
                self.edits[action].setKeySequence(QKeySequence(self._shortcuts.combo(action)))
            finally:
                self._showing = False
            note = self._refused.get(action) or self._state_note(action)
            self.notes[action].setText(note)
            self.notes[action].setVisible(available and bool(note))
            self.edits[action].setAccessibleDescription(note)

    def _state_note(self, action: str) -> str:
        if self._shortcuts.state(action) == State.TAKEN:
            return self.tr("Another app is using %1, so it does not work. Choose another.").replace(
                "%1", self._shortcuts.combo(action)
            )
        return ""

    def _chosen(self, action: str) -> None:
        text = self.edits[action].keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        if text == self._shortcuts.combo(action):
            return
        refused = self._shortcuts.change(action, text)
        if refused == Refused.NOT_A_SHORTCUT:
            self._refused[action] = self.tr(
                "%1 cannot be used: hold Ctrl or Alt with a letter, digit or F1 to F12."
            ).replace("%1", self._readable(text))
        elif refused == Refused.IN_USE_HERE:
            self._refused[action] = self.tr("Stickle already uses %1 for something else.").replace(
                "%1", self._readable(text)
            )
        else:
            self._refused.pop(action, None)
        self.refresh()

    def _cleared(self, action: str, sequence: QKeySequence) -> None:
        """The clear button (or every key taken back): the shortcut is turned off."""
        if not self._showing and sequence.isEmpty():
            self._chosen(action)

    @staticmethod
    def _readable(text: str) -> str:
        return QKeySequence(text).toString(QKeySequence.SequenceFormat.NativeText)
