"""Categories and marks on screen: names, drawn icons, and their place in a
note's title bar.

A note's category shows at the left of its title bar as a coloured dot and
its name, or only the name's first letter where the note is narrow. Its marks
show at the right as small drawn icons, as many as fit, then a count of the
rest. Clicking either opens the note menu.
"""

import math
from collections.abc import Callable
from typing import override

from PySide6.QtCore import QCoreApplication, QLocale, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPaintEvent, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QToolButton, QWidget

from stickle.app.palette import qcolor
from stickle.core.colors import PALETTE, colors_for
from stickle.core.labels import Category, Mark

ICON = 12  # as the title bar's other icons
STROKE = 1.1
HEIGHT = 20  # as the title bar's buttons
GAP = 3
DOT = 8
PADDING = 2


def mark_name(mark: Mark) -> str:
    """The name the user gave the mark, or a built-in mark's own, translated."""
    if mark.name is not None:
        return mark.name
    names = {
        "todo": QCoreApplication.translate("Mark", "To do"),
        "urgent": QCoreApplication.translate("Mark", "Urgent"),
        "important": QCoreApplication.translate("Mark", "Important"),
        "waiting": QCoreApplication.translate("Mark", "Waiting"),
    }
    return names.get(mark.id, mark.id)


def _todo(painter: QPainter, size: float) -> None:
    """A box with a tick."""
    painter.drawRoundedRect(QRectF(size * 0.1, size * 0.1, size * 0.8, size * 0.8), 2, 2)
    painter.drawPolyline(
        QPolygonF(
            [
                QPointF(size * 0.28, size * 0.52),
                QPointF(size * 0.44, size * 0.68),
                QPointF(size * 0.74, size * 0.34),
            ]
        )
    )


def _urgent(painter: QPainter, size: float) -> None:
    """A warning triangle with an exclamation mark."""
    painter.drawPolygon(
        QPolygonF(
            [
                QPointF(size * 0.5, size * 0.06),
                QPointF(size * 0.95, size * 0.9),
                QPointF(size * 0.05, size * 0.9),
            ]
        )
    )
    painter.drawLine(QPointF(size * 0.5, size * 0.38), QPointF(size * 0.5, size * 0.6))
    painter.drawPoint(QPointF(size * 0.5, size * 0.76))


def _important(painter: QPainter, size: float) -> None:
    """A filled five-pointed star."""
    points: list[QPointF] = []
    for corner in range(10):
        radius = size * (0.48 if corner % 2 == 0 else 0.2)
        angle = math.pi / 5 * corner - math.pi / 2
        points.append(
            QPointF(size * 0.5 + radius * math.cos(angle), size * 0.54 + radius * math.sin(angle))
        )
    painter.setBrush(painter.pen().color())
    painter.drawPolygon(QPolygonF(points))


def _waiting(painter: QPainter, size: float) -> None:
    """A clock."""
    painter.drawEllipse(QRectF(size * 0.08, size * 0.08, size * 0.84, size * 0.84))
    painter.drawLine(QPointF(size * 0.5, size * 0.5), QPointF(size * 0.5, size * 0.24))
    painter.drawLine(QPointF(size * 0.5, size * 0.5), QPointF(size * 0.7, size * 0.62))


def _other(painter: QPainter, size: float) -> None:
    """A filled dot, for a mark whose icon this version does not know."""
    painter.setBrush(painter.pen().color())
    painter.drawEllipse(QRectF(size * 0.25, size * 0.25, size * 0.5, size * 0.5))


MARK_DRAWINGS: dict[str, Callable[[QPainter, float], None]] = {
    "todo": _todo,
    "urgent": _urgent,
    "important": _important,
    "waiting": _waiting,
}


def draw_mark(painter: QPainter, icon: str, x: float, y: float, color: QColor) -> None:
    """The mark's icon, ICON across, with its top left at (x, y)."""
    painter.save()
    painter.translate(x, y)
    pen = QPen(color, STROKE)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    MARK_DRAWINGS.get(icon, _other)(painter, ICON)
    painter.restore()


class _TitleBarPart(QToolButton):
    """Drawn in the title bar's text colour; a click opens the note menu."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAutoRaise(True)
        self.setFixedHeight(HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.color = QColor(Qt.GlobalColor.black)
        self.hide()

    def set_color(self, color: QColor) -> None:
        self.color = color
        self.update()


class CategoryTag(_TitleBarPart):
    """The note's category: a dot of its colour and its name, or the name's first
    letter where there is no room for all of it."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.category: Category | None = None

    def set_category(self, category: Category | None) -> None:
        self.category = category
        self.setVisible(category is not None)
        self.retranslate()
        self.updateGeometry()
        self.update()

    def retranslate(self) -> None:
        name = self.category.name if self.category is not None else ""
        text = QCoreApplication.translate("CategoryTag", "Category: %1").replace("%1", name)
        self.setAccessibleName(text)
        self.setToolTip(text)

    def _width_for(self, text: str) -> int:
        return PADDING + DOT + GAP + QFontMetrics(self.font()).horizontalAdvance(text) + PADDING

    def shown_text(self) -> str:
        """All of the name if it fits, else its first letter."""
        name = self.category.name if self.category is not None else ""
        return name if self.width() >= self._width_for(name) else name[:1]

    @override
    def sizeHint(self) -> QSize:
        name = self.category.name if self.category is not None else ""
        return QSize(self._width_for(name), self.height())

    @override
    def minimumSizeHint(self) -> QSize:
        name = self.category.name if self.category is not None else ""
        return QSize(self._width_for(name[:1]), self.height())

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        if self.category is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # The palette's deeper shade: its pastel would hardly show on a pastel note.
        colors = colors_for(PALETTE.get(self.category.color, PALETTE["blue"]))
        painter.setPen(QPen(qcolor(colors.border).darker(130), 1))
        painter.setBrush(qcolor(colors.border))
        top = (self.height() - DOT) / 2
        painter.drawEllipse(QRectF(PADDING + 0.5, top + 0.5, DOT - 1, DOT - 1))
        painter.setPen(self.color)
        left = PADDING + DOT + GAP
        painter.drawText(
            QRectF(left, 0, self.width() - left, self.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self.shown_text(),
        )
        painter.end()


class MarksBadge(_TitleBarPart):
    """The note's marks: their icons, as many as fit, then "+n" for the rest."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.marks: list[Mark] = []

    def set_marks(self, marks: list[Mark]) -> None:
        self.marks = marks
        self.setVisible(bool(marks))
        self.retranslate()
        self.updateGeometry()
        self.update()

    def retranslate(self) -> None:
        names = ", ".join(mark_name(mark) for mark in self.marks)
        text = QCoreApplication.translate("MarksBadge", "Marks: %1").replace("%1", names)
        self.setAccessibleName(text)
        self.setToolTip(text)

    def _more(self, count: int) -> str:
        return "+" + QLocale().toString(count)

    def _width_for(self, icons: int, more: int) -> int:
        width = PADDING + icons * ICON + max(0, icons - 1) * GAP + PADDING
        if more:
            width += GAP + QFontMetrics(self.font()).horizontalAdvance(self._more(more))
        return width

    def shown(self) -> tuple[int, int]:
        """(icons drawn, marks counted in "+n") for the width it has."""
        total = len(self.marks)
        for icons in range(total, 0, -1):
            if self.width() >= self._width_for(icons, total - icons):
                return icons, total - icons
        return min(1, total), max(0, total - 1)

    @override
    def sizeHint(self) -> QSize:
        return QSize(self._width_for(len(self.marks), 0), self.height())

    @override
    def minimumSizeHint(self) -> QSize:
        total = len(self.marks)
        return QSize(self._width_for(min(1, total), max(0, total - 1)), self.height())

    @override
    def paintEvent(self, event: QPaintEvent) -> None:
        icons, more = self.shown()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        top = (self.height() - ICON) / 2
        x = float(PADDING)
        for mark in self.marks[:icons]:
            draw_mark(painter, mark.icon, x, top, self.color)
            x += ICON + GAP
        if more:
            painter.setPen(self.color)
            painter.drawText(
                QRectF(x, 0, self.width() - x, self.height()),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                self._more(more),
            )
        painter.end()
