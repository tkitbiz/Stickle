"""The formatted view of a note, drawn from its Markdown text.

The text itself lives only in the note's plain-text editor; this view reads
it and draws it, so switching between the two never changes the text. The
document is built directly from the parsed Markdown rather than through
HTML, which keeps every format under test and means nothing is ever loaded:
images show their description instead.

A line break inside a paragraph shows as a line break, and blank lines show
as the space they take in the text, so a note looks laid out as it was typed.
"""

from dataclasses import dataclass
from typing import override

from markdown_it.tree import SyntaxTreeNode
from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import (
    QFont,
    QFontDatabase,
    QKeyEvent,
    QMouseEvent,
    QTextBlock,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextLength,
    QTextList,
    QTextListFormat,
)
from PySide6.QtWidgets import QApplication, QTextEdit, QWidget

from stickle.app.palette import qcolor
from stickle.core.colors import DEFAULT_COLOR, NoteColors, note_colors
from stickle.core.markdown import LINE_SEPARATOR, parse, source_position

INDENT_WIDTH = 20
QUOTE_MARGIN = 14
# Font size steps above normal (Qt's scale, as for HTML headings), by heading level.
HEADING_SIZE = {1: 2, 2: 1}
BULLETS = (
    QTextListFormat.Style.ListDisc,
    QTextListFormat.Style.ListCircle,
    QTextListFormat.Style.ListSquare,
)


@dataclass(frozen=True)
class BlockSource:
    """The lines of text a shown block was drawn from (inclusive)."""

    first_line: int
    last_line: int
    checkbox_line: int | None = None  # a task item: the line with its "[ ]"


@dataclass
class _ListLevel:
    format: QTextListFormat
    items: QTextList | None = None
    item_starts: bool = False  # the next block is the first of a new item
    checked: bool | None = None  # that item's checkbox, if it is a task


def utf16_length(text: str) -> int:
    """Length as Qt counts positions: characters outside the BMP count twice."""
    return len(text.encode("utf-16-le")) // 2


def from_utf16(text: str, position: int) -> int:
    """The index into text of a Qt position within it."""
    count = 0
    for index, char in enumerate(text):
        if count >= position:
            return index
        count += 2 if ord(char) > 0xFFFF else 1
    return len(text)


class _Builder:
    def __init__(self, document: QTextDocument, colors: NoteColors) -> None:
        document.clear()
        document.setIndentWidth(INDENT_WIDTH)
        self._document = document
        self._highlight_color = qcolor(colors.highlight)
        self._code_color = qcolor(colors.code_background)
        self._cursor = QTextCursor(document)
        self._fresh = True  # the document's first block has not been used yet
        self._next_line = 0  # the first line not yet shown
        self.sources: list[BlockSource] = []
        self._lists: list[_ListLevel] = []
        self._quotes = 0
        self._heading = 0
        self._bold = 0
        self._italic = 0
        self._highlight = 0
        self._struck = 0
        self._code = False
        self._links: list[str] = []
        self._fixed_family: str | None = None

    # Blocks

    def blocks(self, node: SyntaxTreeNode) -> None:
        for child in node.children:
            self._block(child)

    def _block(self, node: SyntaxTreeNode) -> None:
        first, end = node.map or (self._next_line, self._next_line + 1)
        # Blank lines before a list or quote belong outside it.
        self._blank_lines(first)
        match node.type:
            case "paragraph":
                self._start_block(first, end)
                self._inline_children(node)
            case "heading":
                level = int(node.tag[1:])
                block = QTextBlockFormat()
                block.setHeadingLevel(level)
                self._start_block(first, end, block)
                self._heading = level
                self._inline_children(node)
                self._heading = 0
            case "code_block" | "fence":
                block = QTextBlockFormat()
                block.setBackground(self._code_color)
                self._start_block(first, end, block)
                self._code = True
                self._text(node.content.removesuffix("\n").replace("\n", LINE_SEPARATOR))
                self._code = False
            case "hr":
                block = QTextBlockFormat()
                block.setProperty(
                    QTextFormat.Property.BlockTrailingHorizontalRulerWidth,
                    QTextLength(QTextLength.Type.PercentageLength, 100),
                )
                self._start_block(first, end, block)
            case "blockquote":
                self._quotes += 1
                self.blocks(node)
                self._quotes -= 1
            case "bullet_list" | "ordered_list":
                self._list(node)
            case "list_item":
                level = self._lists[-1]
                level.item_starts = True
                checked = node.meta.get("checked")
                level.checked = checked if isinstance(checked, bool) else None
                self.blocks(node)
                # An item with nothing in it still shows its bullet.
                if level.item_starts:
                    self._start_block(first, first + 1)
            case _:
                # Nothing else is produced; show its text rather than lose it.
                self._start_block(first, end)
                self._text(node.content)

    def _list(self, node: SyntaxTreeNode) -> None:
        depth = len(self._lists)
        list_format = QTextListFormat()
        list_format.setIndent(depth + 1)
        if node.type == "ordered_list":
            list_format.setStyle(QTextListFormat.Style.ListDecimal)
            start = node.attrs.get("start", 1)
            list_format.setStart(start if isinstance(start, int) else 1)
            item = node.children[0] if node.children else None
            list_format.setNumberSuffix(item.markup if item is not None else ".")
        else:
            list_format.setStyle(BULLETS[depth % len(BULLETS)])
        self._lists.append(_ListLevel(list_format))
        self.blocks(node)
        self._lists.pop()

    def _start_block(self, first: int, end: int, block: QTextBlockFormat | None = None) -> None:
        """Begin a block drawn from lines first..end-1, after any blank lines before it."""
        self._blank_lines(first)
        self._next_line = max(self._next_line, end)
        level = self._lists[-1] if self._lists else None
        starts_item = level is not None and level.item_starts
        checkbox_line = None
        block = block or QTextBlockFormat()
        if starts_item and level is not None and level.checked is not None:
            block.setMarker(
                QTextBlockFormat.MarkerType.Checked
                if level.checked
                else QTextBlockFormat.MarkerType.Unchecked
            )
            checkbox_line = first
        self._insert_block(block, BlockSource(first, end - 1, checkbox_line), starts_item)

    def _blank_lines(self, until: int) -> None:
        for line in range(self._next_line, until):
            self._insert_block(QTextBlockFormat(), BlockSource(line, line), in_item=False)
        self._next_line = max(self._next_line, until)

    def _insert_block(self, block: QTextBlockFormat, source: BlockSource, in_item: bool) -> None:
        block.setLeftMargin(self._quotes * QUOTE_MARGIN)
        level = self._lists[-1] if self._lists else None
        if level is not None and not in_item:
            # Further paragraphs of an item line up with its text.
            block.setIndent(level.format.indent())
        if self._fresh:
            self._cursor.setBlockFormat(block)
            self._fresh = False
        else:
            self._cursor.insertBlock(block, QTextCharFormat())
        if level is not None and in_item:
            if level.items is None:
                level.items = self._cursor.createList(level.format)
            else:
                level.items.add(self._cursor.block())
            level.item_starts = False
        self.sources.append(source)

    # Text

    def _inline_children(self, node: SyntaxTreeNode) -> None:
        for child in node.children:
            self._inline(child)

    def _inline(self, node: SyntaxTreeNode) -> None:
        match node.type:
            case "inline":
                self._inline_children(node)
            case "text":
                self._text(node.content)
            case "softbreak" | "hardbreak":
                self._text(LINE_SEPARATOR)
            case "code_inline":
                self._code = True
                self._text(node.content)
                self._code = False
            case "strong":
                self._bold += 1
                self._inline_children(node)
                self._bold -= 1
            case "em":
                self._italic += 1
                self._inline_children(node)
                self._italic -= 1
            case "mark":
                self._highlight += 1
                self._inline_children(node)
                self._highlight -= 1
            case "s":
                self._struck += 1
                self._inline_children(node)
                self._struck -= 1
            case "link":
                href = node.attrs.get("href", "")
                self._links.append(href if isinstance(href, str) else "")
                self._inline_children(node)
                self._links.pop()
            case "image":
                # Never loaded: its description stands in for it.
                self._italic += 1
                self._inline_children(node)
                self._italic -= 1
            case _:
                self._text(node.content)

    def _text(self, text: str) -> None:
        if text:
            self._cursor.insertText(text, self._char_format())

    def _char_format(self) -> QTextCharFormat:
        char = QTextCharFormat()
        if self._bold or self._heading:
            char.setFontWeight(QFont.Weight.Bold)
        if self._heading in HEADING_SIZE:
            char.setProperty(QTextFormat.Property.FontSizeAdjustment, HEADING_SIZE[self._heading])
        if self._italic:
            char.setFontItalic(True)
        if self._code:
            if self._fixed_family is None:
                fixed = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
                self._fixed_family = fixed.family()
            char.setFontFamilies([self._fixed_family])
            # A code block has the background on the whole block already.
            if not self._cursor.blockFormat().hasProperty(QTextFormat.Property.BackgroundBrush):
                char.setBackground(self._code_color)
        if self._highlight:
            char.setBackground(self._highlight_color)
        if self._struck:
            char.setFontStrikeOut(True)
        if self._links:
            char.setAnchor(True)
            char.setAnchorHref(self._links[-1])
            char.setFontUnderline(True)
        return char


def render(text: str, document: QTextDocument, colors: NoteColors) -> list[BlockSource]:
    """Draw a note's Markdown into document; returns where each block came from."""
    builder = _Builder(document, colors)
    if text.strip():
        builder.blocks(parse(text))
    # Nothing shown (such as an empty quote): the one empty block stands for all of it.
    return builder.sources or [BlockSource(0, text.count("\n"))]


class NoteView(QTextEdit):
    """Read-only formatted note. A click asks to edit, a drag selects text.

    Clicking a task item's checkbox asks to toggle it instead; the note
    changes its text, and the view is drawn again from it.
    """

    edit_requested = Signal(int)  # a position in the text, or -1 for its end
    checkbox_clicked = Signal(int)  # the line of the checkbox

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setFrameShape(QTextEdit.Shape.NoFrame)
        self.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self._source = ""
        self._blocks: list[BlockSource] = []
        self._press: QPoint | None = None
        self.colors = note_colors(DEFAULT_COLOR)

    def show_markdown(self, text: str) -> None:
        self._source = text
        # Drawn again when a checkbox is toggled: stay where the reader was.
        scrolled = self.verticalScrollBar().value()
        self._blocks = render(text, self.document(), self.colors)
        self.verticalScrollBar().setValue(scrolled)

    def set_colors(self, colors: NoteColors) -> None:
        self.colors = colors
        if self._source:
            self.show_markdown(self._source)

    def block_source(self, block: QTextBlock) -> BlockSource | None:
        number = block.blockNumber()
        return self._blocks[number] if 0 <= number < len(self._blocks) else None

    def checkbox_at(self, point: QPoint) -> int | None:
        """The checkbox line if point (in viewport coordinates) is on a task item's box."""
        block = self.cursorForPosition(point).block()
        source = self.block_source(block)
        if source is None or source.checkbox_line is None:
            return None
        layout = block.layout()
        if layout.lineCount() == 0:
            return None
        line = layout.lineAt(0)
        x = point.x() + self.horizontalScrollBar().value()
        y = point.y() + self.verticalScrollBar().value()
        text_left = layout.position().x() + line.x()
        top = layout.position().y() + line.y()
        # The box is drawn in the indent to the left of the item's text.
        on_box = text_left - self.document().indentWidth() <= x < text_left
        return source.checkbox_line if on_box and top <= y < top + line.height() else None

    def source_position_at(self, point: QPoint) -> int:
        """The position in the text (as Qt counts) that point shows."""
        cursor = self.cursorForPosition(point)
        block = cursor.block()
        source = self.block_source(block)
        if source is None:
            return -1
        shown = block.text()
        split = from_utf16(shown, cursor.position() - block.position())
        index = source_position(
            self._source, source.first_line, source.last_line, shown[:split], shown[split:]
        )
        return utf16_length(self._source[:index])

    @override
    def mousePressEvent(self, e: QMouseEvent) -> None:
        self._press = e.position().toPoint() if e.button() == Qt.MouseButton.LeftButton else None
        super().mousePressEvent(e)

    @override
    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        super().mouseReleaseEvent(e)
        press, self._press = self._press, None
        point = e.position().toPoint()
        if (
            press is None
            or e.button() != Qt.MouseButton.LeftButton
            or (point - press).manhattanLength() >= QApplication.startDragDistance()
            or self.textCursor().hasSelection()
        ):
            return
        line = self.checkbox_at(point)
        if line is not None:
            self.checkbox_clicked.emit(line)
        else:
            self.edit_requested.emit(self.source_position_at(point))

    @override
    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_F2):
            self.edit_requested.emit(-1)
            return
        super().keyPressEvent(e)
