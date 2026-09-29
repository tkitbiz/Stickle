"""Links and checkboxes in the formatted note, with the mouse and with the keyboard."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QPoint, Qt, QUrl
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest
from pytestqt.qtbot import QtBot

from stickle.app import note_window
from stickle.app.i18n import Translations
from stickle.app.note_window import NoteWindow

TEXT = (
    "할 일\n- [ ] 우유\n- [x] 빵\n\n[문서](https://example.com/doc) 그리고 https://example.org/a\n"
)


class Opened:
    """Stands in for the system's browser: records what was asked to open."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.urls: list[str] = []
        monkeypatch.setattr(note_window, "open_url", self.open)

    def open(self, url: QUrl) -> bool:
        self.urls.append(url.toString())
        return True


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> Opened:
    return Opened(monkeypatch)


@pytest.fixture
def window(qtbot: QtBot) -> Iterator[NoteWindow]:
    window = NoteWindow(text=TEXT)
    window.resize(360, 320)
    window.show()
    qtbot.waitExposed(window)
    yield window
    window.release()


def point_on(window: NoteWindow, words: str) -> QPoint:
    """Where the given words are drawn in the formatted note (viewport coordinates)."""
    view = window.view
    found = view.document().find(words)
    assert not found.isNull(), words
    middle = QTextCursor(view.document())
    middle.setPosition((found.selectionStart() + found.selectionEnd()) // 2)
    return view.cursorRect(middle).center()


def click(window: NoteWindow, point: QPoint) -> None:
    QTest.mouseClick(window.view.viewport(), Qt.MouseButton.LeftButton, pos=point)


def press(window: NoteWindow, key: Qt.Key, modifier: Qt.KeyboardModifier | None = None) -> None:
    QTest.keyClick(window.view, key, modifier or Qt.KeyboardModifier.NoModifier)


def selected(window: NoteWindow) -> str:
    return window.view.textCursor().selectedText()


def test_links_written_both_ways_are_links_and_the_text_is_unchanged(window: NoteWindow) -> None:
    hrefs = [stop.href for stop in window.view.stops if stop.href]

    assert hrefs == ["https://example.com/doc", "https://example.org/a"]
    assert window.text == TEXT


def test_a_click_on_a_link_opens_it(window: NoteWindow, opened: Opened) -> None:
    click(window, point_on(window, "문서"))
    click(window, point_on(window, "example.org"))

    assert opened.urls == ["https://example.com/doc", "https://example.org/a"]
    assert not window.editing


def test_a_click_elsewhere_opens_nothing_and_does_not_edit(
    window: NoteWindow, opened: Opened
) -> None:
    click(window, point_on(window, "그리고"))

    assert opened.urls == []
    assert not window.editing


@pytest.mark.parametrize("href", ["file:///etc/passwd", "javascript:alert(1)", "ftp://x.y/z"])
def test_only_web_and_mail_links_are_opened(opened: Opened, href: str) -> None:
    assert not note_window.open_link(href)
    assert note_window.open_link("mailto:me@example.com")
    assert opened.urls == ["mailto:me@example.com"]


def test_tab_goes_from_box_to_link_in_order_and_round(window: NoteWindow) -> None:
    window.view.setFocus()
    seen: list[str] = []
    for _ in range(5):
        press(window, Qt.Key.Key_Tab)
        seen.append(selected(window))

    assert seen == ["우유", "빵", "문서", "https://example.org/a", "우유"]
    press(window, Qt.Key.Key_Backtab)
    assert selected(window) == "https://example.org/a"


def test_space_checks_the_box_chosen_and_it_stays_chosen(window: NoteWindow) -> None:
    window.view.setFocus()
    press(window, Qt.Key.Key_Tab)

    press(window, Qt.Key.Key_Space)

    assert window.text == TEXT.replace("- [ ] 우유", "- [x] 우유")
    assert selected(window) == "우유"
    window.editor.undo()  # through the editor, as a click would be
    assert window.text == TEXT


def test_enter_opens_the_link_chosen_and_edits_with_none_chosen(
    window: NoteWindow, opened: Opened
) -> None:
    window.view.setFocus()
    for _ in range(3):
        press(window, Qt.Key.Key_Tab)

    press(window, Qt.Key.Key_Return)
    assert opened.urls == ["https://example.com/doc"]
    assert not window.editing

    press(window, Qt.Key.Key_Escape)  # lets go of the link
    assert selected(window) == ""
    press(window, Qt.Key.Key_Return)
    assert window.editing


def test_a_locked_note_opens_links_but_its_boxes_stay(window: NoteWindow, opened: Opened) -> None:
    window.set_locked(True)
    window.view.setFocus()

    press(window, Qt.Key.Key_Tab)
    press(window, Qt.Key.Key_Space)
    click(window, point_on(window, "문서"))

    assert window.text == TEXT
    assert opened.urls == ["https://example.com/doc"]


def test_the_way_to_use_it_is_told_to_screen_readers(
    window: NoteWindow, translations: Translations
) -> None:
    assert "Tab" in window.view.accessibleDescription()
    translations.apply("ko")
    assert "Tab" in window.view.accessibleDescription()
    assert "체크" in window.view.accessibleDescription()
