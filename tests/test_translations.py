import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLocale, QTranslator
from pytestqt.qtbot import QtBot

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "update_translations.py"
KOREAN = ROOT / "i18n" / "stickle_ko.ts"


def run_script(*args: str, root: Path) -> None:
    subprocess.run([sys.executable, str(root / "scripts" / SCRIPT.name), *args], check=True)


def copy_project(tmp_path: Path) -> Path:
    for part in ("scripts", "src", "i18n"):
        shutil.copytree(ROOT / part, tmp_path / part, ignore=shutil.ignore_patterns("*.qm"))
    return tmp_path


def test_every_ui_string_has_a_korean_translation(tmp_path: Path) -> None:
    # Re-extract from the current source into a copy: a new string without Korean shows up here.
    project = copy_project(tmp_path)
    run_script(root=project)

    messages = ET.parse(project / "i18n" / KOREAN.name).getroot().iter("message")
    missing = [
        message.findtext("source")
        for message in messages
        if (translation := message.find("translation")) is None
        or translation.get("type") is not None
        or not (translation.text or "").strip()
    ]
    assert missing == []


def test_committed_korean_file_is_up_to_date(tmp_path: Path) -> None:
    project = copy_project(tmp_path)
    run_script(root=project)

    assert (project / "i18n" / KOREAN.name).read_bytes() == KOREAN.read_bytes()


def test_compiled_korean_translation_is_used(qtbot: QtBot, tmp_path: Path) -> None:
    project = copy_project(tmp_path)
    run_script("--compile", root=project)

    translator = QTranslator()
    assert translator.load(
        QLocale(QLocale.Language.Korean), "stickle", "_", str(project / "src/stickle/translations")
    )
    QCoreApplication.installTranslator(translator)
    try:
        assert QCoreApplication.translate("Tray", "New note") == "새 메모"
    finally:
        QCoreApplication.removeTranslator(translator)
