"""Asking for a new category: its name and the colour of its dot."""

from collections.abc import Callable
from typing import override

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from stickle.app.palette import color_name, swatch_icon
from stickle.core.colors import PALETTE
from stickle.core.labels import NAME_LENGTH, Category
from stickle.data.labels import CategoryNameError

MIN_WIDTH = 320

# The dot is beside a note of any colour: these stand out on most of them.
DOT_COLORS = ("blue", "coral", "green", "lavender", "apricot", "sky", "pink", "mint")


def next_dot_color(taken: int) -> str:
    """A colour for the next category, going round DOT_COLORS."""
    return DOT_COLORS[taken % len(DOT_COLORS)]


class NewCategoryDialog(QDialog):
    """A name and a colour. create makes the category, or raises CategoryNameError,
    which is shown here while the dialog stays open."""

    def __init__(
        self, parent: QWidget | None, create: Callable[[str, str], Category], color: str
    ) -> None:
        super().__init__(parent)
        self._create = create
        self.created: Category | None = None
        # Narrower, and window managers cut its title short.
        self.setMinimumWidth(MIN_WIDTH)

        self.name = QLineEdit(self)
        self.name.setMaxLength(NAME_LENGTH)
        self.color = QComboBox(self)
        for key in PALETTE:
            self.color.addItem(swatch_icon(key), "", key)
        self.color.setCurrentIndex(max(0, self.color.findData(color)))
        self.problem = QLabel(self)
        self.problem.setWordWrap(True)
        self.problem.hide()

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.name.textChanged.connect(self._name_changed)

        self.form = QFormLayout()
        self.name_label = QLabel(self)
        self.name_label.setBuddy(self.name)
        self.color_label = QLabel(self)
        self.color_label.setBuddy(self.color)
        self.form.addRow(self.name_label, self.name)
        self.form.addRow(self.color_label, self.color)
        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(self.problem)
        layout.addWidget(self.buttons)

        self.retranslate()
        self._name_changed("")

    @property
    def ok_button(self) -> QPushButton:
        button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        assert button is not None
        return button

    def retranslate(self) -> None:
        self.setWindowTitle(self.tr("New category"))
        self.name_label.setText(self.tr("&Name:"))
        self.color_label.setText(self.tr("&Color:"))
        for index in range(self.color.count()):
            self.color.setItemText(index, color_name(str(self.color.itemData(index))))

    @override
    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()
        super().changeEvent(event)

    def _name_changed(self, text: str) -> None:
        self.ok_button.setEnabled(bool(text.strip()))
        self.problem.hide()

    @override
    def accept(self) -> None:
        try:
            self.created = self._create(self.name.text(), str(self.color.currentData()))
        except CategoryNameError:
            self.problem.setText(self.tr("There is already a category with this name."))
            self.problem.show()
            self.name.setFocus()
            self.name.selectAll()
            return
        super().accept()
