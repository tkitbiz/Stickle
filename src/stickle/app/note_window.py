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
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QGuiApplication,
    QIcon,
    QInputMethodEvent,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMenu,
    QPlainTextEdit,
    QSizeGrip,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# Fixed until notes get their own colours. The text colour is pinned so a dark
# system theme does not paint light text on the light note.
BACKGROUND = QColor(255, 236, 140, 235)
FOREGROUND = QColor(32, 32, 32)
CORNER_RADIUS = 6
DEFAULT_SIZE = (260, 240)
CLOSE_ICON_SIZE = 10


def drawn_icon(draw: Callable[[QPainter, float], None]) -> QIcon:
    """An icon drawn in the text colour at 1x and 2x for high-DPI screens.

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
        pen = QPen(FOREGROUND, 1.4 * scale)
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


def make_close_icon() -> QIcon:
    return drawn_icon(_cross)


def make_menu_icon() -> QIcon:
    return drawn_icon(_bars)


def make_delete_icon() -> QIcon:
    return drawn_icon(_bin)


def make_unsaved_icon() -> QIcon:
    return drawn_icon(_warning)


class TitleBar(QWidget):
    """Drag handle with the menu and hide buttons."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedHeight(28)
        self._drag_offset: QPoint | None = None

        self.menu_button = QToolButton(self)
        self.menu_button.setIcon(make_menu_icon())
        self.menu_button.setAutoRaise(True)
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        # The menu arrow would crowd the small title bar; the icon says it is a menu.
        self.menu_button.setStyleSheet("QToolButton::menu-indicator { image: none; }")
        self.close_button = QToolButton(self)
        self.close_button.setIcon(make_close_icon())
        self.close_button.setAutoRaise(True)
        # Shown only while the note could not be saved; clicking tries again at once.
        self.unsaved_button = QToolButton(self)
        self.unsaved_button.setIcon(make_unsaved_icon())
        self.unsaved_button.setAutoRaise(True)
        self.unsaved_button.hide()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 2, 2)
        layout.addWidget(self.unsaved_button)
        layout.addStretch()
        layout.addWidget(self.menu_button)
        layout.addWidget(self.close_button)

    @override
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        # Let the window system move the window: the only way that also works on Wayland.
        if self.window().windowHandle().startSystemMove():
            self._drag_offset = None
        else:
            self._drag_offset = event.globalPosition().toPoint() - self.window().pos()
        event.accept()

    @override
    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is None:
            super().mouseMoveEvent(event)
            return
        self.window().move(event.globalPosition().toPoint() - self._drag_offset)
        event.accept()

    @override
    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class NoteWindow(QWidget):
    """Frameless, always-on-top, translucent note that stays off the taskbar.

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

    def __init__(self, note_id: str | None = None, text: str = "") -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        # macOS hides tool windows while the app is inactive unless told otherwise.
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.resize(*DEFAULT_SIZE)

        # Style sheets rather than a palette: native styles ignore palette text colours.
        self.setStyleSheet(
            f"QPlainTextEdit {{ background: transparent; color: {FOREGROUND.name()}; }}"
            f"QToolButton {{ color: {FOREGROUND.name()}; }}"
        )

        self.note_id = note_id  # None until the note is first stored
        self._released = False
        # An input method is composing a character (Hangul syllables, for example).
        # The editor's text holds only what is committed, so saving never catches
        # half a character.
        self.composing = False
        self._preedit = ""
        self._commit_seen = False

        self.title_bar = TitleBar(self)
        self.title_bar.close_button.clicked.connect(self.hide_requested)
        self.menu = QMenu(self)
        self.delete_action = self.menu.addAction(make_delete_icon(), "")
        self.delete_action.triggered.connect(self.delete_requested)
        self.title_bar.menu_button.setMenu(self.menu)

        self.editor = QPlainTextEdit(self)
        self.editor.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.editor.setPlainText(text)
        self.editor.installEventFilter(self)
        self.editor.textChanged.connect(self.text_changed)
        self.title_bar.unsaved_button.clicked.connect(self.retry_requested)

        grip_row = QHBoxLayout()
        grip_row.setContentsMargins(0, 0, 0, 0)
        grip_row.addStretch()
        grip_row.addWidget(QSizeGrip(self))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.title_bar)
        layout.addWidget(self.editor)
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

        self.setFocusProxy(self.editor)
        self.retranslate()

    def retranslate(self) -> None:
        """Apply every visible text; runs again when the UI language changes."""
        self.setWindowTitle(self.tr("Note"))
        self.setAccessibleName(self.tr("Note"))
        self.editor.setAccessibleName(self.tr("Note text"))
        hide_note = self.tr("Hide note")
        self.title_bar.close_button.setAccessibleName(hide_note)
        self.title_bar.close_button.setToolTip(hide_note)
        self.close_action.setText(hide_note)
        note_menu = self.tr("Note menu")
        self.title_bar.menu_button.setAccessibleName(note_menu)
        self.title_bar.menu_button.setToolTip(note_menu)
        self.menu_action.setText(note_menu)
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

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(BACKGROUND)
        painter.drawRoundedRect(self.rect(), CORNER_RADIUS, CORNER_RADIUS)

    @property
    def text(self) -> str:
        return self.editor.toPlainText()

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
        self.menu.popup(button.mapToGlobal(button.rect().bottomLeft()))
        self.menu.setActiveAction(self.delete_action)

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
        if watched is self.editor and event.type() == QEvent.Type.FocusOut and not self._released:
            self.editing_finished.emit()
        if watched is self.editor and isinstance(event, QInputMethodEvent):
            self._preedit = event.preeditString()
            self.composing = bool(self._preedit)
            if event.commitString():
                self._commit_seen = True
        return super().eventFilter(watched, event)

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._released:
            event.ignore()
            # After this close has finished: Qt ignores a close started during another.
            QTimer.singleShot(0, self.hide_requested.emit)
            return
        self.closed.emit()
        super().closeEvent(event)
