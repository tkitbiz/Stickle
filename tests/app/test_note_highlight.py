"""Markdown colouring of a note's text while it is edited."""

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from PySide6.QtGui import QFont, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import QApplication
from pytestqt.qtbot import QtBot

from stickle.app.note_highlight import MarkdownHighlighter
from stickle.app.note_view import utf16_length
from stickle.app.note_window import NoteWindow
from stickle.app.palette import qcolor
from stickle.core.colors import DEFAULT_COLOR, note_colors

DEFAULT = note_colors(DEFAULT_COLOR)
FOREGROUND = qcolor(DEFAULT.text)
HIGHLIGHT = qcolor(DEFAULT.highlight)
CODE_BACKGROUND = qcolor(DEFAULT.code_background)

_windows: list[NoteWindow] = []  # kept alive while their documents are examined


def highlighted(qtbot: QtBot, text: str) -> QTextDocument:
    window = NoteWindow(text=text)
    qtbot.addWidget(window)
    _windows.append(window)
    QApplication.processEvents()  # the first colouring is done from the event loop
    return window.editor.document()


def format_at(document: QTextDocument, line: int, index: int) -> QTextCharFormat:
    """The colouring of character index on a line."""
    block = document.findBlockByNumber(line)
    position = utf16_length(block.text()[:index])
    for part in block.layout().formats():
        if part.start <= position < part.start + part.length:
            return QTextCharFormat(part.format)  # the range list is temporary
    return QTextCharFormat()


def dimmed(char: QTextCharFormat) -> bool:
    return char.hasProperty(QTextCharFormat.Property.ForegroundBrush) and (
        char.foreground().color().alpha() < FOREGROUND.alpha()
    )


def bold(char: QTextCharFormat) -> bool:
    return char.fontWeight() == QFont.Weight.Bold


def test_heading_is_bold_with_its_marks_dimmed(qtbot: QtBot) -> None:
    document = highlighted(qtbot, "## 제목")

    assert dimmed(format_at(document, 0, 0))
    assert bold(format_at(document, 0, 3))
    assert not dimmed(format_at(document, 0, 3))


def test_inline_formats_and_their_marks(qtbot: QtBot) -> None:
    text = "😀 **굵게** *기울임* ==형광== `코드`"
    document = highlighted(qtbot, text)

    def at(part: str) -> QTextCharFormat:
        return format_at(document, 0, text.index(part))

    assert dimmed(at("**"))
    assert bold(at("굵게"))
    assert at("기울임").fontItalic()
    assert at("형광").background().color() == HIGHLIGHT
    assert at("코드").background().color() == CODE_BACKGROUND
    assert not bold(at("😀"))


def test_bold_is_not_also_italic(qtbot: QtBot) -> None:
    text = "milk **2** and __3__"
    document = highlighted(qtbot, text)

    for part in ("2", "3"):
        char = format_at(document, 0, text.index(part))
        assert bold(char)
        assert not char.fontItalic()
    assert not format_at(document, 0, text.index("*")).fontItalic()


def test_nothing_inside_code_is_formatted(qtbot: QtBot) -> None:
    text = "`**not bold**`"
    document = highlighted(qtbot, text)

    assert not bold(format_at(document, 0, text.index("not")))


def test_list_and_task_marks_are_dimmed(qtbot: QtBot) -> None:
    document = highlighted(qtbot, "- [ ] 할 일\n> 1. 인용")

    assert dimmed(format_at(document, 0, 0))
    assert dimmed(format_at(document, 0, 3))
    assert not dimmed(format_at(document, 0, 6))
    assert dimmed(format_at(document, 1, 0))
    assert dimmed(format_at(document, 1, 2))


def test_code_block_lines_are_shaded_until_the_fence_closes(qtbot: QtBot) -> None:
    document = highlighted(qtbot, "```\n**literal**\n```\n**bold**")

    inside = format_at(document, 1, 2)
    assert inside.background().color() == CODE_BACKGROUND
    assert not bold(inside)
    assert bold(format_at(document, 3, 2))


def test_link_address_is_dimmed_but_not_its_text(qtbot: QtBot) -> None:
    text = "[링크](https://example.com)"
    document = highlighted(qtbot, text)

    assert not dimmed(format_at(document, 0, 1))
    assert dimmed(format_at(document, 0, text.index("https")))


def test_opening_a_fence_while_typing_recolours_the_lines_after(qtbot: QtBot) -> None:
    window = NoteWindow(text="code\n**after**")
    qtbot.addWidget(window)
    QApplication.processEvents()
    document = window.editor.document()
    assert bold(format_at(document, 1, 2))

    window.editor.moveCursor(QTextCursor.MoveOperation.Start)
    window.editor.insertPlainText("```\n")

    after = format_at(document, 2, 2)
    assert after.background().color() == CODE_BACKGROUND
    assert not bold(after)
    window.release()


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(st.text(alphabet=st.sampled_from([*"-*_=#>`[]()x !.1\n\t한😀"])))
def test_colouring_never_changes_the_text(qtbot: QtBot, text: str) -> None:
    document = QTextDocument()
    document.setPlainText(text)
    before = document.toPlainText()
    highlighter = MarkdownHighlighter(document, DEFAULT)
    highlighter.rehighlight()

    assert document.toPlainText() == before


def test_colouring_alone_is_not_a_change_to_save(qtbot: QtBot) -> None:
    window = NoteWindow(text="# **title**\n```\ncode")
    qtbot.addWidget(window)
    changes: list[None] = []
    window.text_changed.connect(lambda: changes.append(None))

    window.highlighter.rehighlight()
    qtbot.wait(10)
    assert changes == []

    window.editor.insertPlainText("x")
    assert changes == [None]
    window.release()
