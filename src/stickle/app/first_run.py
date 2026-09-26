"""The first start on a computer: a welcome, a few choices, and the recovery key.

Shown once, when the notes database was just made, before the first note
appears. Page one asks whether the notes are for this computer only (kept
for when sync exists), whether Stickle starts at login, and, for an
AppImage, whether it goes in the application list. Page two shows the
recovery key. Closing the window without going on changes nothing: no
choice is taken for the user.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from stickle.app.app_list import switch_app_list
from stickle.app.recovery_key_dialog import RecoveryKeyPanel
from stickle.app.tray import switch_autostart
from stickle.data.notes import NoteRepository
from stickle.data.settings import (
    APP_MENU_ASKED,
    RECOVERY_KEY_KEPT,
    SEVERAL_DEVICES,
    THIS_DEVICE,
    USAGE,
    Settings,
)
from stickle.platform.autostart import Autostart
from stickle.platform.linux.appimage import AppMenuEntry

log = logging.getLogger(__name__)


def sample_note() -> str:
    """The first note: how Stickle works, in the interface language, as Markdown."""
    return QCoreApplication.translate(
        "FirstRun",
        "# Welcome to Stickle\n"
        "Click this note to edit it; click elsewhere to see it formatted again.\n"
        "\n"
        "- [ ] Tick a box like this one\n"
        "- [ ] Double-click the title bar to fold the note\n"
        "- [ ] Use the pin to keep a note above other windows, or not\n"
        "- [ ] Change its colour from the menu with three dots\n"
        "\n"
        "The **X** hides a note: bring it back from the Stickle icon. "
        "**Ctrl+N** makes a new note.",
    )


@dataclass(frozen=True)
class FirstRunChoices:
    usage: str | None  # THIS_DEVICE, SEVERAL_DEVICES, or None if not answered
    start_at_login: bool
    app_list: bool
    recovery_key_kept: bool


class FirstRunDialog(QDialog):
    def __init__(
        self,
        recovery_key: str,
        offer_start_at_login: bool,
        offer_app_list: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._offers = (offer_start_at_login, offer_app_list)
        self.heading = QLabel()
        font = QFont(self.heading.font())
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.3)
        self.heading.setFont(font)
        self.heading.setWordWrap(True)

        # Page one: welcome and choices.
        self.intro = QLabel()
        self.intro.setWordWrap(True)
        self.usage_label = QLabel()
        self.usage_label.setWordWrap(True)
        self.this_device = QRadioButton()
        self.several_devices = QRadioButton()
        self.this_device.setChecked(True)
        self.usage = QButtonGroup(self)
        self.usage.addButton(self.this_device)
        self.usage.addButton(self.several_devices)
        self.start_at_login = QCheckBox()
        self.start_at_login.setChecked(True)
        self.start_at_login.setVisible(offer_start_at_login)
        self.app_list = QCheckBox()
        self.app_list.setChecked(True)
        self.app_list.setVisible(offer_app_list)
        welcome = QWidget()
        welcome_layout = QVBoxLayout(welcome)
        welcome_layout.setContentsMargins(0, 0, 0, 0)
        welcome_layout.addWidget(self.intro)
        welcome_layout.addSpacing(8)
        welcome_layout.addWidget(self.usage_label)
        welcome_layout.addWidget(self.this_device)
        welcome_layout.addWidget(self.several_devices)
        welcome_layout.addSpacing(8)
        welcome_layout.addWidget(self.start_at_login)
        welcome_layout.addWidget(self.app_list)
        welcome_layout.addStretch()

        # Page two: the recovery key.
        self.recovery = RecoveryKeyPanel(recovery_key)

        self.pages = QStackedWidget()
        self.pages.addWidget(welcome)
        self.pages.addWidget(self.recovery)

        self.buttons = QDialogButtonBox()
        self.next_button = self.buttons.addButton("", QDialogButtonBox.ButtonRole.ActionRole)
        self.next_button.clicked.connect(self._next)
        self.next_button.setDefault(True)
        self.done_button = self.buttons.addButton("", QDialogButtonBox.ButtonRole.AcceptRole)
        self.later_button = self.buttons.addButton("", QDialogButtonBox.ButtonRole.RejectRole)
        self.done_button.hide()
        self.later_button.hide()
        self.done_button.setEnabled(False)
        self.recovery.kept.toggled.connect(self.done_button.setEnabled)
        self.done_button.clicked.connect(self.accept)
        self.later_button.clicked.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.heading)
        layout.addWidget(self.pages, 1)
        layout.addWidget(self.buttons)
        self.setMinimumWidth(520)
        self.went_on = False  # past page one: its choices stand
        self.retranslate()

    def retranslate(self) -> None:
        self.setWindowTitle("Stickle")
        if self.pages.currentIndex() == 0:
            self.heading.setText(self.tr("Welcome to Stickle"))
        else:
            self.heading.setText(self.tr("Your recovery key"))
        self.intro.setText(
            self.tr(
                "Stickle keeps sticky notes on your desktop. They are saved as you type, "
                "encrypted on this computer, and nothing is sent anywhere."
            )
        )
        self.usage_label.setText(self.tr("Where will you use your notes?"))
        self.this_device.setText(self.tr("On this &computer only"))
        self.several_devices.setText(
            self.tr("On &several devices (syncing through your own cloud comes later)")
        )
        self.start_at_login.setText(self.tr("&Start Stickle when I log in"))
        self.app_list.setText(self.tr("Show Stickle in the &app list"))
        self.next_button.setText(self.tr("&Next"))
        self.done_button.setText(self.tr("Done"))
        self.later_button.setText(self.tr("Later"))

    @override
    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()
        super().changeEvent(event)

    def _next(self) -> None:
        self.went_on = True
        if not self.recovery.recovery_key:
            # It could not be made (logged); it is offered again later.
            self.reject()
            return
        self.pages.setCurrentIndex(1)
        self.next_button.hide()
        self.done_button.show()
        self.later_button.show()
        self.recovery.kept.setFocus()
        self.retranslate()

    def choices(self) -> FirstRunChoices:
        """What was chosen; nothing at all if the window was closed on page one."""
        if not self.went_on:
            return FirstRunChoices(None, False, False, False)
        usage = SEVERAL_DEVICES if self.several_devices.isChecked() else THIS_DEVICE
        offer_login, offer_list = self._offers
        return FirstRunChoices(
            usage=usage,
            start_at_login=offer_login and self.start_at_login.isChecked(),
            app_list=offer_list and self.app_list.isChecked(),
            recovery_key_kept=self.result() == QDialog.DialogCode.Accepted,
        )


def welcome(
    notes: NoteRepository,
    settings: Settings,
    make_recovery_key: Callable[[], str],
    autostart: Autostart | None,
    app_list: AppMenuEntry | None,
    ask: Callable[[FirstRunDialog], object] = FirstRunDialog.exec,
) -> FirstRunChoices:
    """The first start: the sample note, then the choices, carried out."""
    notes.create(sample_note())
    try:
        recovery_key = make_recovery_key()
    except OSError as error:
        log.error("no recovery key at first start: %s", type(error).__name__)
        recovery_key = ""
    dialog = FirstRunDialog(recovery_key, autostart is not None, app_list is not None)
    ask(dialog)
    choices = dialog.choices()
    if choices.usage is not None:
        settings.set(USAGE, choices.usage)
    if autostart is not None and choices.start_at_login:
        switch_autostart(autostart, True)
    if app_list is not None and dialog.went_on:
        settings.set(APP_MENU_ASKED, True)  # asked here: not again separately
        if choices.app_list:
            switch_app_list(app_list, True)
    if choices.recovery_key_kept:
        settings.set(RECOVERY_KEY_KEPT, True)
    log.info(
        "first start: usage %s, start at login %s, recovery key %s",
        choices.usage,
        choices.start_at_login,
        "kept" if choices.recovery_key_kept else "not yet",
    )
    return choices
