"""A single sticky note window."""

from collections.abc import Callable
from typing import override

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QEventLoop,
    QObject,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QColor,
    QContextMenuEvent,
    QFocusEvent,
    QGuiApplication,
    QIcon,
    QInputMethodEvent,
    QKeyEvent,
    QKeySequence,
    QMouseEvent,
    QMoveEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
    QPixmap,
    QResizeEvent,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QSizeGrip,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from stickle.app.note_highlight import MarkdownHighlighter
from stickle.app.note_view import NoteView, utf16_length
from stickle.app.palette import color_name, qcolor, swatch_icon
from stickle.core.colors import DARK_TEXT, DEFAULT_COLOR, PALETTE, note_colors
from stickle.core.markdown import note_title, task_box

CORNER_RADIUS = 6
TITLE_BAR_HEIGHT = 28  # also the height of a folded note
MAX_HEIGHT = 16_777_215  # Qt's QWIDGETSIZE_MAX: no limit
DEFAULT_SIZE = (260, 240)
CLOSE_ICON_SIZE = 10
# How long an input method has to commit a character after the focus left.
DROP_CHECK_MS = 150
# Moving and resizing report a stream of positions: the place is kept once they stop.
SETTLE_MS = 500


def drawn_icon(draw: Callable[[QPainter, float], None], color: QColor) -> QIcon:
    """An icon drawn in color at 1x and 2x for high-DPI screens.

    Drawn rather than symbol characters: finding a font with such a glyph
    made showing the first note take a third of a second longer.
    """
    icon = QIcon()
    for scale in (1, 2):
        size = CLOSE_ICON_SIZE * scale
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(color, 1.4 * scale)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        draw(painter, size)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def _cross(painter: QPainter, size: float) -> None:
    inset = size * 0.15
    painter.drawLine(QPointF(inset, inset), QPointF(size - inset, size - inset))
    painter.drawLine(QPointF(size - inset, inset), QPointF(inset, size - inset))


def _bars(painter: QPainter, size: float) -> None:
    for y in (0.2, 0.5, 0.8):
        painter.drawLine(QPointF(size * 0.1, size * y), QPointF(size * 0.9, size * y))


def _bin(painter: QPainter, size: float) -> None:
    painter.drawLine(QPointF(size * 0.1, size * 0.22), QPointF(size * 0.9, size * 0.22))
    painter.drawLine(QPointF(size * 0.38, size * 0.08), QPointF(size * 0.62, size * 0.08))
    painter.drawRoundedRect(QRectF(size * 0.2, size * 0.22, size * 0.6, size * 0.7), 1, 1)


def _warning(painter: QPainter, size: float) -> None:
    painter.drawEllipse(QRectF(size * 0.08, size * 0.08, size * 0.84, size * 0.84))
    painter.drawLine(QPointF(size * 0.5, size * 0.28), QPointF(size * 0.5, size * 0.55))
    painter.drawPoint(QPointF(size * 0.5, size * 0.72))


def _pin(painter: QPainter, size: float, filled: bool) -> None:
    """A push pin: a round head on a plate, and its point below."""
    if filled:
        painter.setBrush(painter.pen().color())
    painter.drawEllipse(QRectF(size * 0.28, size * 0.06, size * 0.44, size * 0.44))
    painter.drawLine(QPointF(size * 0.2, size * 0.6), QPointF(size * 0.8, size * 0.6))
    painter.drawLine(QPointF(size * 0.5, size * 0.6), QPointF(size * 0.5, size * 0.95))


def make_pin_icon(color: QColor, pinned: bool) -> QIcon:
    """Solid while the note stays on top; faint and hollow while it does not."""
    if pinned:
        return drawn_icon(lambda painter, size: _pin(painter, size, filled=True), color)
    faint = QColor(color)
    faint.setAlphaF(0.45)
    return drawn_icon(lambda painter, size: _pin(painter, size, filled=False), faint)


def make_close_icon(color: QColor) -> QIcon:
    return drawn_icon(_cross, color)


def make_menu_icon(color: QColor) -> QIcon:
    return drawn_icon(_bars, color)


def make_delete_icon(color: QColor) -> QIcon:
    return drawn_icon(_bin, color)


def make_unsaved_icon(color: QColor) -> QIcon:
    return drawn_icon(_warning, color)


class TitleBar(QWidget):
    """Drag handle with the menu and hide buttons. Right-clicking it opens the menu,
    double-clicking it folds or unfolds the note, and a folded note shows its title."""

    menu_requested = Signal(QPoint)  # where, on the screen
    double_clicked = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedHeight(TITLE_BAR_HEIGHT)
        self._drag_offset: QPoint | None = None
        self._press: QPoint | None = None  # a press that may yet become a drag

        self.title = QLabel(self)
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.title.setMinimumWidth(0)
        self.title.hide()
        self._full_title = ""

        # Always on top: a pin that shows at a glance whether the note stays on top.
        self.pin_button = QToolButton(self)
        self.pin_button.setAutoRaise(True)
        self.pin_button.setCheckable(True)
        self.pin_button.setChecked(True)
        # The icon itself shows the state; a pressed-in button on top of it looks heavy.
        self.pin_button.setStyleSheet(
            "QToolButton:checked { background: transparent; border: none; }"
        )
        self._icon_color = qcolor(DARK_TEXT)
        self.pin_button.toggled.connect(self._show_pin)
        self.menu_button = QToolButton(self)
        self.menu_button.setAutoRaise(True)
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        # The menu arrow would crowd the small title bar; the icon says it is a menu.
        self.menu_button.setStyleSheet("QToolButton::menu-indicator { image: none; }")
        self.close_button = QToolButton(self)
        self.close_button.setAutoRaise(True)
        # Shown only while the note could not be saved; clicking tries again at once.
        self.unsaved_button = QToolButton(self)
        self.unsaved_button.setAutoRaise(True)
        self.unsaved_button.hide()
        self.set_icon_color(qcolor(DARK_TEXT))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 2, 2)
        layout.addWidget(self.unsaved_button)
        layout.addWidget(self.title, 1)
        layout.addStretch()
        # Kept away from the hide button, so it is not hit by mistake.
        layout.addWidget(self.pin_button)
        layout.addWidget(self.menu_button)
        layout.addWidget(self.close_button)

    def set_icon_color(self, color: QColor) -> None:
        self._icon_color = color
        self.menu_button.setIcon(make_menu_icon(color))
        self.close_button.setIcon(make_close_icon(color))
        self.unsaved_button.setIcon(make_unsaved_icon(color))
        self._show_pin(self.pin_button.isChecked())

    def _show_pin(self, pinned: bool) -> None:
        self.pin_button.setIcon(make_pin_icon(self._icon_color, pinned))

    def set_title(self, title: str) -> None:
        """Shown while the note is folded, shortened to the width it has."""
        self._full_title = title
        self._elide()

    def _elide(self) -> None:
        metrics = self.title.fontMetrics()
        self.title.setText(
            metrics.elidedText(self._full_title, Qt.TextElideMode.ElideRight, self.title.width())
        )

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._elide()

    @override
    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        self.menu_requested.emit(event.globalPos())
        event.accept()

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        # The window starts moving only once the mouse moves: a click or a
        # double-click (to fold the note) must reach the note first.
        self._press = event.globalPosition().toPoint()
        event.accept()

    @override
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        point = event.globalPosition().toPoint()
        if self._press is not None and self._drag_offset is None:
            if (point - self._press).manhattanLength() < QApplication.startDragDistance():
                return
            start = self._press
            self._press = None
            # Let the window system move the window: the only way that also works on Wayland.
            if not self.window().windowHandle().startSystemMove():
                self._drag_offset = start - self.window().pos()
        if self._drag_offset is None:
            super().mouseMoveEvent(event)
            return
        self.window().move(point - self._drag_offset)
        event.accept()

    @override
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._press = None
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    @override
    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = None
            self.double_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class NoteWindow(QWidget):
    """Frameless, always-on-top note with rounded corners that stays off the taskbar.

    Its colours all follow from one palette key (see stickle.core.colors); the
    background is opaque so the text always contrasts as intended.

    The window only asks: hiding and deleting are decided (and stored) by its
    owner, which then closes it with release(). Any other close, such as Alt+F4,
    asks to hide too, so a note never leaves the screen without being stored.
    """

    closed = Signal()
    new_note_requested = Signal()
    hide_requested = Signal()
    delete_requested = Signal()
    editing_finished = Signal()  # the text lost focus: a moment to save
    text_changed = Signal()
    retry_requested = Signal()
    color_requested = Signal(str)  # a palette key
    collapse_requested = Signal(bool)  # True: fold to the title bar, False: unfold
    on_top_requested = Signal(bool)  # True: stay above other windows
    geometry_settled = Signal()  # moved or resized, and then left alone for a moment

    def __init__(
        self,
        note_id: str | None = None,
        text: str = "",
        color: str = DEFAULT_COLOR,
        always_on_top: bool = True,
    ) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        # Only so the rounded corners are see-through; the note itself is opaque.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        # macOS hides tool windows while the app is inactive unless told otherwise.
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.resize(*DEFAULT_SIZE)

        self.note_id = note_id  # None until the note is first stored
        self._released = False
        # An input method is composing a character (Hangul syllables, for example).
        # The editor's text holds only what is committed, so saving never catches
        # half a character.
        self.composing = False
        self._preedit = ""
        self._commit_seen = False
        self._commits = 0  # committed texts seen, to tell a drop from a commit

        # Where the app last put the note; anything else is the user's doing.
        self._placed: QRect | None = None
        # False while shown in its spare place because its own monitor is missing.
        self.own_monitor = True
        self.collapsed = False
        self._expanded_height = 0  # the height to unfold to, while folded
        self._settle = QTimer(self)
        self._settle.setSingleShot(True)
        self._settle.setInterval(SETTLE_MS)
        self._settle.timeout.connect(self.geometry_settled)

        self.color = color
        self.colors = note_colors(color)

        self.title_bar = TitleBar(self)
        self.title_bar.close_button.clicked.connect(self.hide_requested)
        self.title_bar.menu_requested.connect(self.open_menu_at)
        self.title_bar.double_clicked.connect(
            lambda: self.collapse_requested.emit(not self.collapsed)
        )
        self.menu = QMenu(self)
        self.color_menu = self.menu.addMenu("")
        self.color_actions: dict[str, QAction] = {}
        colors = QActionGroup(self)
        for key in PALETTE:
            action = self.color_menu.addAction(swatch_icon(key), "")
            action.setCheckable(True)
            action.triggered.connect(lambda _=False, key=key: self.color_requested.emit(key))
            colors.addAction(action)
            self.color_actions[key] = action
        self.collapse_action = self.menu.addAction("")
        self.collapse_action.triggered.connect(
            lambda: self.collapse_requested.emit(not self.collapsed)
        )
        # The same as the pin, for the keyboard and screen readers.
        self.on_top_action = self.menu.addAction("")
        self.on_top_action.setCheckable(True)
        self.on_top_action.setChecked(True)
        self.on_top_action.triggered.connect(self.on_top_requested)
        self.title_bar.pin_button.clicked.connect(self.on_top_requested)
        self.menu.addSeparator()
        # The menu has the system's colours, which are the note's only by chance.
        self.delete_action = self.menu.addAction(make_delete_icon(qcolor(DARK_TEXT)), "")
        self.delete_action.triggered.connect(self.delete_requested)
        self.title_bar.menu_button.setMenu(self.menu)

        self.editor = QPlainTextEdit(self)
        self.editor.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.editor.setPlainText(text)
        self.highlighter = MarkdownHighlighter(self.editor.document(), self.colors)
        self.editor.installEventFilter(self)
        # The editor also reports a change when only the colouring changed.
        self._last_text = self.text
        self.editor.textChanged.connect(self._text_changed)
        self.title_bar.unsaved_button.clicked.connect(self.retry_requested)
        # The formatted note, drawn from the editor's text; a click edits it.
        self.view = NoteView(self)
        self.view.edit_requested.connect(self.edit)
        self.view.checkbox_clicked.connect(self.toggle_checkbox)
        self.stack = QStackedWidget(self)
        self.stack.addWidget(self.view)
        self.stack.addWidget(self.editor)
        self.stack.setCurrentWidget(self.editor)

        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 0, 0)
        grip_row.addStretch()
        self.size_grip = QSizeGrip(self)
        grip_row.addWidget(self.size_grip)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.title_bar)
        layout.addWidget(self.stack)
        layout.addLayout(grip_row)

        self.new_note_action = self._add_action(QKeySequence.StandardKey.New)
        self.new_note_action.triggered.connect(self.new_note_requested)
        self.close_action = self._add_action(QKeySequence.StandardKey.Close)
        self.close_action.triggered.connect(self.hide_requested)
        # Tab types a tab in the text, so the menu has a key of its own.
        self.menu_action = QAction(self)
        self.menu_action.setShortcut(QKeySequence(Qt.Key.Key_F10))
        self.menu_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.menu_action.triggered.connect(self.open_menu)
        self.addAction(self.menu_action)

        self.set_color(color)
        self.set_always_on_top(always_on_top)
        self.retranslate()
        if text.strip():
            self.show_formatted()
        else:
            self.edit()

    def retranslate(self) -> None:
        """Apply every visible text; runs again when the UI language changes."""
        self.setWindowTitle(self.tr("Note"))
        self.setAccessibleName(self.tr("Note"))
        self.editor.setAccessibleName(self.tr("Note text"))
        self.view.setAccessibleName(self.tr("Note text"))
        self.view.setAccessibleDescription(self.tr("Press Enter to edit."))
        hide_note = self.tr("Hide note")
        self.title_bar.close_button.setAccessibleName(hide_note)
        self.title_bar.close_button.setToolTip(hide_note)
        self.close_action.setText(hide_note)
        note_menu = self.tr("Note menu")
        self.title_bar.menu_button.setAccessibleName(note_menu)
        self.title_bar.menu_button.setToolTip(note_menu)
        on_top = self.tr("Always on top")
        self.on_top_action.setText(on_top)
        self.title_bar.pin_button.setAccessibleName(on_top)
        self.title_bar.pin_button.setToolTip(on_top)
        self.menu_action.setText(note_menu)
        self.color_menu.setTitle(self.tr("Color"))
        self.collapse_action.setText(
            self.tr("Expand note") if self.collapsed else self.tr("Collapse note")
        )
        self._update_title()
        for key, action in self.color_actions.items():
            action.setText(color_name(key))
        self.delete_action.setText(self.tr("Delete note"))
        self.new_note_action.setText(self.tr("New note"))
        self.title_bar.unsaved_button.setAccessibleName(self.tr("Not saved"))
        self.title_bar.unsaved_button.setToolTip(
            self.tr("This note could not be saved. Trying again; click to try now.")
        )

    @override
    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()
        super().changeEvent(event)

    def _add_action(self, key: QKeySequence.StandardKey) -> QAction:
        action = QAction(self)
        action.setShortcuts(key)
        action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.addAction(action)
        return action

    def place(self, geometry: QRect, own_monitor: bool = True) -> None:
        """Put the note somewhere as the app, not the user, decided.

        geometry has the unfolded height; a folded note keeps it for later.
        """
        if self.collapsed:
            self._expanded_height = geometry.height()
            geometry = QRect(geometry.topLeft(), QSize(geometry.width(), TITLE_BAR_HEIGHT))
        self.setGeometry(geometry)
        self._placed = self.geometry()
        self.own_monitor = own_monitor

    def expanded_geometry(self) -> QRect:
        """Where the note is, with the height it has when unfolded."""
        geometry = self.geometry()
        if self.collapsed:
            geometry.setHeight(self._expanded_height)
        return geometry

    @property
    def always_on_top(self) -> bool:
        return bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

    def set_always_on_top(self, on_top: bool) -> None:
        """Keep the note above other windows, or let them cover it."""
        self.title_bar.pin_button.setChecked(on_top)
        self.on_top_action.setChecked(on_top)
        if on_top == self.always_on_top:
            return
        was_visible = self.isVisible()
        geometry = self.geometry()
        # Qt hides a window whose flags change; it comes back where it was.
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on_top)
        if was_visible:
            self.setGeometry(geometry)
            self.show()
            self.raise_()
            self.activateWindow()

    def set_collapsed(self, collapsed: bool) -> None:
        """Fold the note to its title bar, keeping its top edge where it is, or unfold it."""
        if collapsed == self.collapsed:
            return
        top_left = self.pos()
        if collapsed:
            self._expanded_height = self.height()
            self.collapsed = True
            self.stack.hide()
            self.size_grip.hide()
            self.setFixedHeight(TITLE_BAR_HEIGHT)
            # The keyboard stays with the note (on its title bar): Enter unfolds it.
            self.title_bar.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.setFocusProxy(self.title_bar)
            self.title_bar.setFocus()
        else:
            self.collapsed = False
            self.setMinimumHeight(0)
            self.setMaximumHeight(MAX_HEIGHT)
            self.stack.show()
            self.size_grip.show()
            self.resize(self.width(), self._expanded_height)
            self.title_bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            focus = self.editor if self.editing else self.view
            self.setFocusProxy(focus)
            focus.setFocus()
        self.move(top_left)
        self.title_bar.title.setVisible(collapsed)
        self.retranslate()

    def _update_title(self) -> None:
        if not self.collapsed:
            self.title_bar.set_title("")  # only a folded note shows it
            return
        self.title_bar.set_title(note_title(self.text) or self.tr("Empty note"))

    @override
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self.collapsed and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.collapse_requested.emit(False)
            return
        super().keyPressEvent(event)

    @property
    def moved_by_user(self) -> bool:
        """Moved or resized since the app last placed it."""
        return self.geometry() != self._placed

    def mark_placed(self) -> None:
        """Where the note is now has been remembered."""
        self._placed = self.geometry()

    @override
    def moveEvent(self, event: QMoveEvent) -> None:
        super().moveEvent(event)
        if self.isVisible():
            self._settle.start()

    @override
    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self.isVisible():
            self._settle.start()

    def set_color(self, color: str) -> None:
        """Show the note in a palette colour (an unknown key shows the default)."""
        self.color = color
        self.colors = note_colors(color)
        text = qcolor(self.colors.text).name()
        title_text = qcolor(self.colors.title_text).name()
        # Style sheets rather than a palette: native styles ignore palette text colours.
        # Pinned so a dark system theme does not paint light text on a light note.
        self.setStyleSheet(
            f"QPlainTextEdit, QTextEdit {{ background: transparent; color: {text}; }}"
            f"TitleBar QToolButton, TitleBar QLabel {{ color: {title_text}; }}"
        )
        self.title_bar.set_icon_color(qcolor(self.colors.title_text))
        self.view.set_colors(self.colors)
        self.highlighter.set_colors(self.colors)
        for key, action in self.color_actions.items():
            action.setChecked(key == color)
        self.update()

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        shape = QPainterPath()
        outline = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)  # the border on whole pixels
        shape.addRoundedRect(outline, CORNER_RADIUS, CORNER_RADIUS)
        painter.fillPath(shape, qcolor(self.colors.background))
        painter.setClipPath(shape)
        painter.fillRect(0, 0, self.width(), self.title_bar.height(), qcolor(self.colors.title_bar))
        painter.setClipping(False)
        painter.setPen(QPen(qcolor(self.colors.border), 1))
        painter.drawPath(shape)

    @property
    def text(self) -> str:
        return self.editor.toPlainText()

    @property
    def editing(self) -> bool:
        return self.stack.currentWidget() is self.editor

    def edit(self, position: int = -1) -> None:
        """Show the text to edit, with the cursor at position (-1: the end)."""
        self.stack.setCurrentWidget(self.editor)
        self.setFocusProxy(self.editor)
        cursor = self.editor.textCursor()
        if 0 <= position <= self.editor.document().characterCount() - 1:
            cursor.setPosition(position)
        else:
            cursor.movePosition(QTextCursor.MoveOperation.End)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
        self.editor.ensureCursorVisible()

    def show_formatted(self) -> None:
        """Show the note formatted; an empty note stays ready to type in."""
        if not self.editing or not self.text.strip():
            return
        self.view.show_markdown(self.text)
        self.stack.setCurrentWidget(self.view)
        if self.collapsed:
            return  # the folded note keeps the keyboard itself
        self.setFocusProxy(self.view)
        # Given at once if the note is active, or when it next becomes active.
        self.view.setFocus()

    def toggle_checkbox(self, line: int) -> None:
        """Check or uncheck the task item on that line of the text.

        Only the mark inside its brackets changes, through the editor, so it
        can be undone and is saved like any other change.
        """
        block = self.editor.document().findBlockByNumber(line)
        found = task_box(block.text()) if block.isValid() else None
        if found is None:
            return
        column, mark = found
        cursor = QTextCursor(block)
        cursor.setPosition(block.position() + utf16_length(block.text()[:column]))
        cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(mark)

    def _text_changed(self) -> None:
        text = self.text
        if text == self._last_text:
            return
        self._last_text = text
        self.text_changed.emit()
        # The text can change while shown formatted: a checkbox was toggled, or
        # an input method committed a character after the focus left.
        if not self.editing:
            self.view.show_markdown(self.text)
        if self.collapsed:
            self._update_title()

    def _leave_editing(self) -> None:
        if not self._released and self.editing and not self.editor.hasFocus():
            self.show_formatted()

    def finish_composition(self, closing: bool) -> None:
        """Make sure the character being composed ends up in the text.

        Input methods differ: some commit when asked to, fcitx5 commits when
        reset, and some answer only after the request returns. When the note
        is closing, a character that was still not committed after all that
        is put into the text as the input method would have. While the note
        stays open (logout, sleep) it is only asked to commit, so that nothing
        can be typed twice when the user goes on typing.
        """
        if not self.composing:
            return
        preedit = self._preedit
        self._commit_seen = False
        if self.editor.hasFocus():
            self._request_commit()
            if closing and self.composing:
                self._request_reset()
            # Answers that arrive as posted events; the user's input waits.
            QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        if closing and not self._commit_seen:
            event = QInputMethodEvent("", [])
            event.setCommitString(preedit)
            QCoreApplication.sendEvent(self.editor, event)

    # Separate so tests can play the part of different input methods.
    def _request_commit(self) -> None:
        QGuiApplication.inputMethod().commit()

    def _request_reset(self) -> None:
        QGuiApplication.inputMethod().reset()

    def set_unsaved(self, unsaved: bool) -> None:
        self.title_bar.unsaved_button.setVisible(unsaved)

    @property
    def unsaved(self) -> bool:
        return self.title_bar.unsaved_button.isVisibleTo(self)

    def open_menu(self) -> None:
        button = self.title_bar.menu_button
        self.open_menu_at(button.mapToGlobal(button.rect().bottomLeft()))

    def open_menu_at(self, position: QPoint) -> None:
        self.menu.popup(position)
        # The first item, for the keyboard; not Delete, which Enter would then trigger.
        self.menu.setActiveAction(self.color_menu.menuAction())

    def allow_close(self) -> None:
        """Let the next close through without asking to hide (the app is quitting)."""
        self._released = True

    def release(self) -> None:
        """Close for real: the owner has stored what it needed."""
        self.allow_close()
        self.close()

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # Once released the note has been stored (or deleted): closing moves the focus
        # away, and that must not store it again.
        if (
            watched is self.editor
            and isinstance(event, QFocusEvent)
            and event.type() == QEvent.Type.FocusOut
            and not self._released
        ):
            if self.composing:
                self._watch_for_drop(self._preedit, self._commits)
            self.editing_finished.emit()
            # A menu opened from the note leaves it being edited.
            if event.reason() != Qt.FocusReason.PopupFocusReason:
                QTimer.singleShot(0, self, self._leave_editing)
        if (
            watched is self.editor
            and isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            self.show_formatted()
            return True
        if watched is self.editor and isinstance(event, QInputMethodEvent):
            self._preedit = event.preeditString()
            self.composing = bool(self._preedit)
            if event.commitString():
                self._commit_seen = True
                self._commits += 1
        return super().eventFilter(watched, event)

    def _watch_for_drop(self, preedit: str, commits: int) -> None:
        """Keep the character being composed if the input method drops it on focus loss.

        Some input methods (ibus on GNOME) throw away the character being composed
        when the focus moves elsewhere, in every application. Most commit it
        instead. If, shortly after the focus left, the composition has ended
        without anything being committed, the character is put in the text.
        """

        def check() -> None:
            if self._released or self.composing or self._commits != commits:
                return
            event = QInputMethodEvent("", [])
            event.setCommitString(preedit)
            QCoreApplication.sendEvent(self.editor, event)

        QTimer.singleShot(DROP_CHECK_MS, check)

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._released:
            event.ignore()
            # After this close has finished: Qt ignores a close started during another.
            QTimer.singleShot(0, self.hide_requested.emit)
            return
        self.closed.emit()
        super().closeEvent(event)
