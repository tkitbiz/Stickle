"""Saving the recovery key and choosing a folder: the desktop's dialog, else Qt's."""

from pathlib import Path
from typing import Literal

import pytest
from PySide6.QtWidgets import QFileDialog, QWidget
from pytestqt.qtbot import QtBot

from stickle.app import file_dialogs
from stickle.app.file_dialogs import existing_folder, save_file_name
from stickle.app.recovery_key_dialog import RecoveryKeyPanel

RECOVERY_KEY = "ABCD-EFGH-JKMN-PQRS-TVWX-YZ01-2345-6789"
type Answer = Path | Literal["unavailable"] | None


class Desktop:
    """Stands in for the desktop's dialog: records what was asked, answers as set."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, answer: Answer) -> None:
        self.answer: Answer = answer
        self.asked: list[tuple[str, str, Path | None]] = []
        monkeypatch.setattr(file_dialogs, "from_the_desktop", self.ask)

    def ask(self, _parent: QWidget, kind: str, title: str, suggested: Path | None) -> Answer:
        self.asked.append((kind, title, suggested))
        return self.answer


class Qt:
    """Stands in for Qt's own dialogs."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, answer: str) -> None:
        self.answer = answer
        self.asked = 0

        def save(*_args: object) -> tuple[str, str]:
            self.asked += 1
            return self.answer, ""

        def folder(*_args: object) -> str:
            self.asked += 1
            return self.answer

        monkeypatch.setattr(QFileDialog, "getSaveFileName", save)
        monkeypatch.setattr(QFileDialog, "getExistingDirectory", folder)


def test_the_recovery_key_is_saved_where_the_desktop_dialog_says(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    desktop = Desktop(monkeypatch, tmp_path / "key.txt")
    qt = Qt(monkeypatch, "")
    panel = RecoveryKeyPanel(RECOVERY_KEY)
    qtbot.addWidget(panel)

    panel._save()  # pyright: ignore[reportPrivateUsage]

    assert RECOVERY_KEY in (tmp_path / "key.txt").read_text(encoding="utf-8")
    kind, _title, suggested = desktop.asked[0]
    assert kind == "save" and suggested is not None and suggested.name.endswith(".txt")
    assert qt.asked == 0


def test_cancelled_nothing_is_saved(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    Desktop(monkeypatch, None)
    qt = Qt(monkeypatch, str(tmp_path / "never.txt"))
    panel = RecoveryKeyPanel(RECOVERY_KEY)
    qtbot.addWidget(panel)

    panel._save()  # pyright: ignore[reportPrivateUsage]

    assert list(tmp_path.iterdir()) == []
    assert qt.asked == 0  # cancelled is an answer: Qt's dialog is not asked instead


def test_without_the_desktops_dialog_qts_is_shown(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    Desktop(monkeypatch, "unavailable")
    qt = Qt(monkeypatch, str(tmp_path / "chosen"))
    parent = QWidget()
    qtbot.addWidget(parent)

    assert save_file_name(parent, "t", tmp_path / "a.txt", "*.txt") == tmp_path / "chosen"
    assert existing_folder(parent, "t") == tmp_path / "chosen"
    assert qt.asked == 2


def test_off_linux_the_system_dialog_comes_from_qt(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(file_dialogs.sys, "platform", "win32")
    parent = QWidget()
    qtbot.addWidget(parent)

    assert file_dialogs._from_the_desktop(parent, "save", "t", None) == "unavailable"  # pyright: ignore[reportPrivateUsage]
