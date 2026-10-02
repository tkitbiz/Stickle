"""Managing categories: making, renaming, recolouring, reordering and deleting them.

Deleting one asks first. With notes in it, the user chooses between taking the
category off them, which cannot be undone and is said so, and moving them to
the trash with it, asked once more with how many go, hidden and locked ones
included; the trash keeps them for a year.
"""

from collections.abc import Callable
from typing import Literal, override

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeyEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from stickle.app import notes as notes_module
from stickle.app.category_dialog import next_dot_color
from stickle.app.labels import dot_icon
from stickle.app.notes import NoteManager
from stickle.app.palette import color_name, swatch_icon
from stickle.core.colors import PALETTE
from stickle.core.labels import Category
from stickle.data.labels import CategoryNameError

CATEGORY_ID = Qt.ItemDataRole.UserRole

type Removal = Literal["category", "notes"] | None


def _ask_how(parent: QWidget, question: str, category_only: str, with_notes: str) -> Removal:
    box = QMessageBox(QMessageBox.Icon.Warning, "Stickle", question, parent=parent)
    only = box.addButton(category_only, QMessageBox.ButtonRole.DestructiveRole)
    notes = box.addButton(with_notes, QMessageBox.ButtonRole.DestructiveRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    clicked = box.clickedButton()
    return "category" if clicked is only else "notes" if clicked is notes else None


def _ask(parent: QWidget, question: str) -> bool:
    answer = QMessageBox.question(
        parent,
        "Stickle",
        question,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes


# Replaced in tests.
ask_how: Callable[[QWidget, str, str, str], Removal] = _ask_how
confirm: Callable[[QWidget, str], bool] = _ask


class CategoryManager(QDialog):
    def __init__(self, notes: NoteManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._notes = notes
        self.setMinimumWidth(360)

        self.label = QLabel(self)
        self.list = QListWidget(self)
        self.label.setBuddy(self.list)
        self.list.setEditTriggers(
            QListWidget.EditTrigger.EditKeyPressed | QListWidget.EditTrigger.DoubleClicked
        )
        self.list.itemChanged.connect(self._renamed)
        self.list.currentRowChanged.connect(self._enable)
        self.list.installEventFilter(self)
        self.problem = QLabel(self)
        self.problem.setWordWrap(True)
        self.problem.hide()

        self.new_button = QPushButton(self)
        self.new_button.clicked.connect(self.new_category)
        self.rename_button = QPushButton(self)
        self.rename_button.clicked.connect(self._rename)
        self.color_button = QPushButton(self)
        self.color_menu = QMenu(self.color_button)
        for key in PALETTE:
            action = self.color_menu.addAction(swatch_icon(key), "")
            action.setData(key)
            action.triggered.connect(lambda _=False, key=key: self._recolor(key))
        self.color_button.setMenu(self.color_menu)
        self.up_button = QPushButton(self)
        self.up_button.clicked.connect(lambda: self.move_selected(-1))
        self.down_button = QPushButton(self)
        self.down_button.clicked.connect(lambda: self.move_selected(1))
        self.delete_button = QPushButton(self)
        self.delete_button.clicked.connect(self.delete)
        for keys, step in (("Alt+Up", -1), ("Alt+Down", 1)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(lambda step=step: self.move_selected(step))
        self.close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        self.close_buttons.rejected.connect(self.reject)

        side = QVBoxLayout()
        for button in (
            self.new_button,
            self.rename_button,
            self.color_button,
            self.up_button,
            self.down_button,
            self.delete_button,
        ):
            side.addWidget(button)
        side.addStretch()
        body = QHBoxLayout()
        body.addWidget(self.list, 1)
        body.addLayout(side)
        layout = QVBoxLayout(self)
        layout.addWidget(self.label)
        layout.addLayout(body)
        layout.addWidget(self.problem)
        layout.addWidget(self.close_buttons)

        notes.changed.connect(self.refresh)
        self.retranslate()

    def retranslate(self) -> None:
        self.setWindowTitle(self.tr("Categories"))
        self.label.setText(self.tr("&Categories"))
        self.list.setAccessibleName(self.tr("Categories"))
        self.list.setAccessibleDescription(
            self.tr("F2 renames, Alt+Up and Alt+Down move, Delete deletes.")
        )
        self.new_button.setText(self.tr("&New…"))
        self.rename_button.setText(self.tr("&Rename"))
        self.color_button.setText(self.tr("C&olor"))
        self.up_button.setText(self.tr("Move &up"))
        self.down_button.setText(self.tr("Move do&wn"))
        self.delete_button.setText(self.tr("&Delete…"))
        for action in self.color_menu.actions():
            action.setText(color_name(str(action.data())))
        self.refresh()

    @override
    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()
        super().changeEvent(event)

    def categories(self) -> list[Category]:
        return self._notes.label_choices()[0]

    def selected(self) -> Category | None:
        row = self.list.currentRow()
        chosen = self.list.item(row).data(CATEGORY_ID) if row >= 0 else None
        return next((c for c in self.categories() if c.id == chosen), None)

    def refresh(self, keep: str | None = None) -> None:
        """The categories as they are now, the selected one (or keep) staying selected."""
        current = self.selected()
        keep = keep or (current.id if current is not None else None)
        self.list.blockSignals(True)
        self.list.clear()
        for category in self.categories():
            item = QListWidgetItem(dot_icon(category.color), category.name)
            item.setData(CATEGORY_ID, category.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.list.addItem(item)
            if category.id == keep:
                self.list.setCurrentItem(item)
        if self.list.count() and self.list.currentRow() < 0:
            self.list.setCurrentRow(0)
        self.list.blockSignals(False)
        self._enable()

    def _enable(self) -> None:
        chosen = self.selected() is not None
        row = self.list.currentRow()
        for button in (self.rename_button, self.color_button, self.delete_button):
            button.setEnabled(chosen)
        self.up_button.setEnabled(chosen and row > 0)
        self.down_button.setEnabled(chosen and row < self.list.count() - 1)

    def _show_problem(self, text: str) -> None:
        self.problem.setText(text)
        self.problem.setVisible(bool(text))

    def new_category(self) -> None:
        dialog = notes_module.new_category_dialog(
            self, self._notes.create_category, next_dot_color(len(self.categories()))
        )
        if dialog.created is not None:
            self.refresh(keep=dialog.created.id)

    def _rename(self) -> None:
        row = self.list.currentRow()
        if row >= 0:
            self.list.editItem(self.list.item(row))

    def _renamed(self, item: QListWidgetItem) -> None:
        category_id = str(item.data(CATEGORY_ID))
        try:
            self._notes.rename_category(category_id, item.text())
        except CategoryNameError:
            self._show_problem(self.tr("There is already a category with this name."))
            self.refresh(keep=category_id)  # back to the name it has
            return
        self._show_problem("")
        self.refresh(keep=category_id)

    def _recolor(self, color: str) -> None:
        category = self.selected()
        if category is not None:
            self._notes.set_category_color(category.id, color)

    def move_selected(self, step: int) -> None:
        category = self.selected()
        if category is not None:
            self._notes.move_category(category.id, step)
            self.refresh(keep=category.id)

    def delete(self) -> None:
        """Asks first: see the module's description."""
        category = self.selected()
        if category is None:
            return
        inside = self._notes.notes_in_category(category.id)
        if not inside:
            question = self.tr("Delete the category “%1”? No note has it.").replace(
                "%1", category.name
            )
            if confirm(self, question):
                self._notes.remove_category(category.id, with_notes=False)
            return
        question = self.tr(
            "%n note(s) will lose the category “%1”. This cannot be undone. "
            "The notes themselves stay as they are.",
            "",
            len(inside),
        ).replace("%1", category.name)
        how = ask_how(
            self,
            question,
            self.tr("Delete the category only"),
            self.tr("Move the notes to the trash too…"),
        )
        if how == "category":
            self._notes.remove_category(category.id, with_notes=False)
            return
        if how != "notes":
            return
        hidden = sum(note.hidden for note in inside)
        locked = sum(note.locked for note in inside)
        question = self.tr(
            "Move %n note(s) to the trash with the category “%1”? "
            "They can be brought back from the trash for a year.",
            "",
            len(inside),
        ).replace("%1", category.name)
        if hidden or locked:
            question += "\n\n" + self.tr(
                "Among them: %1 hidden, %2 locked.", "numbers of notes"
            ).replace("%1", str(hidden)).replace("%2", str(locked))
        if confirm(self, question):
            self._notes.remove_category(category.id, with_notes=True)

    @override
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self.list
            and isinstance(event, QKeyEvent)
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Delete
            and self.list.state() != QListWidget.State.EditingState
        ):
            self.delete()
            return True
        return super().eventFilter(watched, event)
