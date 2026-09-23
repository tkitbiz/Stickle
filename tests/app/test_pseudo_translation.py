"""Every visible text must go through a translation function.

All strings are extracted afresh from the source and given a fake translation
that is longer and marked with brackets and accents. After switching to it at
run time, any visible text without the marker was either never passed through
tr() or is not re-applied when the language changes.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QWidget
from pytestqt.qtbot import QtBot
from update_translations import compile_to, extract

from stickle.app.application import NoteManager
from stickle.app.i18n import Translations
from stickle.app.tray import Tray

ACCENTED = str.maketrans("aeiouAEIOUcnst", "åëïöüÅËÏÖÜçñşŧ")
# Texts that are not translated on purpose.
UNTRANSLATED = {"", "Stickle", "English", "한국어"}


def pseudo(text: str) -> str:
    return f"[{text.translate(ACCENTED)}{'~' * (len(text) // 3 + 1)}]"


def make_pseudo_translation(folder: Path) -> None:
    ts_file = folder / "stickle_fr.ts"
    extract(ts_file)
    tree = ET.parse(ts_file)
    for message in tree.getroot().iter("message"):
        translation = message.find("translation")
        assert translation is not None
        translation.attrib.pop("type", None)
        translation.text = pseudo(message.findtext("source") or "")
    tree.write(ts_file, encoding="utf-8", xml_declaration=True)
    compile_to(ts_file, folder / "stickle_fr.qm")


def visible_texts(widget: QWidget) -> list[str]:
    texts: list[str] = []
    for item in [widget, *widget.findChildren(QWidget)]:
        texts += [item.windowTitle(), item.toolTip(), item.accessibleName()]
        texts += [action.text() for action in item.actions()]
    return texts


def test_every_visible_text_is_translated(qtbot: QtBot, tmp_path: Path) -> None:
    make_pseudo_translation(tmp_path)
    translations = Translations(tmp_path)
    translations.apply("en")
    manager = NoteManager()
    tray = Tray(manager.new_note, lambda: None, translations)
    note = manager.new_note()
    try:
        # Switched after the windows exist, so re-application is covered too.
        translations.apply("fr")
        menu = tray.contextMenu()
        assert menu is not None
        texts = visible_texts(note) + visible_texts(menu) + visible_texts(tray.language_menu)

        untranslated = [text for text in texts if text not in UNTRANSLATED and "~]" not in text]
        assert untranslated == []
    finally:
        note.close()
        translations.apply("en")
        QLocale.setDefault(QLocale.system())
