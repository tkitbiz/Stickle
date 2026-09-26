"""Markdown syntax colouring for a note's text while it is edited.

Only how the text looks changes; the text itself is never touched. The
marks that make formats (#, **, ==, ~~, `, list markers) are dimmed and what they
format is shown formatted, line by line, so it stays quick while typing.
"""

import re
from typing import override

from PySide6.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)

from stickle.app.note_view import utf16_length
from stickle.app.palette import qcolor
from stickle.core.colors import NoteColors

OUTSIDE_FENCE = 0
INSIDE_FENCE = 1

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]|$)")
_QUOTE = re.compile(r"^(?:[ \t]*>)+")
_LIST = re.compile(r"^[ \t]*(?:>[ \t]*)*(?:[-+*]|\d{1,9}[.)])(?:[ \t]+\[[ xX]\])?(?=[ \t]|$)")
_RULE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_CODE = re.compile(r"(`+)(.+?)\1")
_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
# Not the inside of **bold**: the text may not begin or end with another marker.
_ITALIC = re.compile(r"(?<![*_\w])([*_])(?![\s*_])(.+?)(?<![\s*_])\1(?![*_\w])")
_HIGHLIGHT = re.compile(r"(==)(?=\S)(.+?)(?<=\S)==")
_STRIKE = re.compile(r"(?<!~)(~~)(?=[^\s~])(.+?)(?<=[^\s~])~~(?!~)")
_LINK = re.compile(r"!?\[([^\]]*)\](\([^)]*\))")


def _utf16(text: str, index: int) -> int:
    return utf16_length(text[:index])


class MarkdownHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument, colors: NoteColors) -> None:
        super().__init__(document)
        self._marks = QTextCharFormat()
        self._code = QColor()
        self._highlight = QColor()
        self._take_colors(colors)

    def _take_colors(self, colors: NoteColors) -> None:
        dimmed = qcolor(colors.text)
        dimmed.setAlphaF(0.45)
        self._marks.setForeground(dimmed)
        self._code = qcolor(colors.code_background)
        self._highlight = qcolor(colors.highlight)

    def set_colors(self, colors: NoteColors) -> None:
        self._take_colors(colors)
        self.rehighlight()

    def _apply(self, text: str, start: int, end: int, char: QTextCharFormat) -> None:
        begin = _utf16(text, start)
        self.setFormat(begin, _utf16(text, end) - begin, char)

    def _merge(self, text: str, start: int, end: int, char: QTextCharFormat) -> None:
        """Add char to what each character in start..end already has."""
        for index in range(start, end):
            position = _utf16(text, index)
            merged = self.format(position)
            merged.merge(char)
            self.setFormat(position, _utf16(text, index + 1) - position, merged)

    @override
    def highlightBlock(self, text: str) -> None:
        inside = self.previousBlockState() == INSIDE_FENCE
        fence = _FENCE.match(text)
        if inside or fence:
            code = QTextCharFormat()
            code.setBackground(self._code)
            self._apply(text, 0, len(text), code)
            if fence:
                self._apply(text, 0, len(text), self._marks)
            self.setCurrentBlockState(OUTSIDE_FENCE if inside == bool(fence) else INSIDE_FENCE)
            return
        self.setCurrentBlockState(OUTSIDE_FENCE)

        if _RULE.match(text):
            self._apply(text, 0, len(text), self._marks)
            return
        heading = _HEADING.match(text)
        if heading:
            bold = QTextCharFormat()
            bold.setFontWeight(QFont.Weight.Bold)
            self._apply(text, 0, len(text), bold)
            self._merge(text, heading.start(1), heading.end(1), self._marks)
        for pattern in (_QUOTE, _LIST):
            match = pattern.match(text)
            if match:
                self._merge(text, match.start(), match.end(), self._marks)

        code_spans: list[tuple[int, int]] = []
        for match in _CODE.finditer(text):
            code = QTextCharFormat()
            code.setBackground(self._code)
            self._merge(text, match.start(), match.end(), code)
            self._merge(text, match.start(1), match.end(1), self._marks)
            self._merge(text, match.end(2), match.end(), self._marks)
            code_spans.append((match.start(), match.end()))

        def in_code(position: int) -> bool:
            return any(start <= position < end for start, end in code_spans)

        styles: list[tuple[re.Pattern[str], QTextCharFormat]] = []
        bold = QTextCharFormat()
        bold.setFontWeight(QFont.Weight.Bold)
        italic = QTextCharFormat()
        italic.setFontItalic(True)
        highlight = QTextCharFormat()
        highlight.setBackground(self._highlight)
        struck = QTextCharFormat()
        struck.setFontStrikeOut(True)
        styles += [(_BOLD, bold), (_ITALIC, italic), (_HIGHLIGHT, highlight), (_STRIKE, struck)]
        for pattern, char in styles:
            for match in pattern.finditer(text):
                if in_code(match.start()):
                    continue
                self._merge(text, match.start(2), match.end(2), char)
                self._merge(text, match.start(1), match.end(1), self._marks)
                self._merge(text, match.end(2), match.end(), self._marks)
        for match in _LINK.finditer(text):
            if not in_code(match.start()):
                self._merge(text, match.start(2), match.end(2), self._marks)
