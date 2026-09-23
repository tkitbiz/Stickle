"""A single sticky note window."""

from typing import override

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QColor,
    QKeySequence,
    QMouseEvent,
    QPainter,
    QPaintEvent,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
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


class TitleBar(QWidget):
    """Drag handle with the close button."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedHeight(28)
        self._drag_offset: QPoint | None = None

        self.close_button = QToolButton(self)
        self.close_button.setText("✕")
        self.close_button.setAutoRaise(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 2, 2)
        layout.addStretch()
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
    """Frameless, always-on-top, translucent note that stays off the taskbar."""

    closed = Signal()
    new_note_requested = Signal()

    def __init__(self) -> None:
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

        self.title_bar = TitleBar(self)
        self.title_bar.close_button.clicked.connect(self.close)

        self.editor = QPlainTextEdit(self)
        self.editor.setFrameShape(QPlainTextEdit.Shape.NoFrame)

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
        self.close_action.triggered.connect(self.close)

        self.setFocusProxy(self.editor)
        self.retranslate()

    def retranslate(self) -> None:
        """Apply every visible text; runs again when the UI language changes."""
        self.setWindowTitle(self.tr("Note"))
        self.setAccessibleName(self.tr("Note"))
        self.editor.setAccessibleName(self.tr("Note text"))
        close_note = self.tr("Close note")
        self.title_bar.close_button.setAccessibleName(close_note)
        self.title_bar.close_button.setToolTip(close_note)
        self.close_action.setText(close_note)
        self.new_note_action.setText(self.tr("New note"))

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

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        self.closed.emit()
        super().closeEvent(event)
