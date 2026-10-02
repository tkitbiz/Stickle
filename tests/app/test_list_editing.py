"""Help with lists in a note's editor: Enter, Tab, Shift+Tab and "[]"."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QInputMethodEvent, QTextCursor
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from stickle.app.note_window import NoteWindow


@pytest.fixture
def note(qtbot: QtBot) -> Iterator[NoteWindow]:
    window = NoteWindow(text="")
    window.show()
    qtbot.waitExposed(window)
    window.edit()
    yield window
    window.release()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def type_in(note: NoteWindow, text: str) -> None:
    for character in text:
        if character == "\n":
            QTest.keyClick(note.editor, Qt.Key.Key_Return)
        elif character == "\t":
            QTest.keyClick(note.editor, Qt.Key.Key_Tab)
        elif character.isascii():
            QTest.keyClicks(note.editor, character)
        else:
            # As an input method gives Korean (QTest cannot type it: it crashes).
            commit = QInputMethodEvent("", [])
            commit.setCommitString(character)
            QCoreApplication.sendEvent(note.editor, commit)


def test_enter_continues_a_checklist_and_ends_it(note: NoteWindow) -> None:
    type_in(note, "- [ ] 우유\n두부\n\n끝")
    assert note.text == "- [ ] 우유\n- [ ] 두부\n\n끝"


def test_tab_nests_and_shift_tab_brings_it_back(note: NoteWindow) -> None:
    type_in(note, "- [ ] 장보기\n\t우유")
    assert note.text == "- [ ] 장보기\n  - [ ] 우유"
    QTest.keyClick(note.editor, Qt.Key.Key_Backtab)
    assert note.text == "- [ ] 장보기\n- [ ] 우유"


def test_an_empty_nested_item_moves_out_first(note: NoteWindow) -> None:
    type_in(note, "1. a\n\tb\n\n")
    assert note.text == "1. a\n   2. b\n2. "  # out a level, numbering on
    QTest.keyClick(note.editor, Qt.Key.Key_Return)
    assert note.text == "1. a\n   2. b\n\n"


def test_brackets_make_a_checkbox(note: NoteWindow) -> None:
    type_in(note, "[]우유")
    assert note.text == "- [ ] 우유"


def test_shift_enter_is_an_ordinary_new_line(note: NoteWindow) -> None:
    type_in(note, "- a")
    QTest.keyClick(note.editor, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert note.text.startswith("- a") and not note.text.endswith("- ")  # no new item


def test_one_undo_takes_back_the_help(note: NoteWindow) -> None:
    type_in(note, "- [ ] 우유\n")
    assert note.text == "- [ ] 우유\n- [ ] "
    note.editor.undo()
    assert note.text == "- [ ] 우유"


def test_in_a_code_block_the_keys_are_as_ever(note: NoteWindow) -> None:
    note.editor.setPlainText("```\n- a")
    note.editor.moveCursor(QTextCursor.MoveOperation.End)
    type_in(note, "\n\t")
    assert note.text == "```\n- a\n\t"


def test_a_locked_note_gets_no_help(note: NoteWindow) -> None:
    note.editor.setPlainText("- a")
    note.set_locked(True)
    assert note.text == "- a"


def test_a_character_being_composed_is_left_to_the_input_method(note: NoteWindow) -> None:
    type_in(note, "- 우")  # committed by the input method
    composing = QInputMethodEvent("유", [])
    QCoreApplication.sendEvent(note.editor, composing)
    assert note.composing
    QTest.keyClick(note.editor, Qt.Key.Key_Return)  # as an input method that passes it on
    assert "- " not in note.text.split("\n")[-1]  # no help while composing
    commit = QInputMethodEvent("", [])
    commit.setCommitString("유")
    QCoreApplication.sendEvent(note.editor, commit)
    assert "우" in note.text and "유" in note.text  # nothing lost


def test_the_usual_order_commit_then_enter_gets_the_help(note: NoteWindow) -> None:
    type_in(note, "- 우")  # committed by the input method
    QCoreApplication.sendEvent(note.editor, QInputMethodEvent("유", []))
    commit = QInputMethodEvent("", [])
    commit.setCommitString("유")
    QCoreApplication.sendEvent(note.editor, commit)  # Enter commits first (fcitx5, IBus)
    QTest.keyClick(note.editor, Qt.Key.Key_Return)  # then is passed on
    assert note.text == "- 우유\n- "
