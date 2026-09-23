import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QLocale
from pytestqt.qtbot import QtBot
from update_translations import QT_TRANSLATIONS, TS_DIR, compile_to

from stickle.app.i18n import Translations


@pytest.fixture
def translations_dir(tmp_path: Path) -> Path:
    """The Korean translations, compiled from the committed sources."""
    compile_to(TS_DIR / "stickle_ko.ts", tmp_path / "stickle_ko.qm")
    shutil.copy2(QT_TRANSLATIONS / "qtbase_ko.qm", tmp_path)
    return tmp_path


@pytest.fixture
def translations(qtbot: QtBot, translations_dir: Path) -> Iterator[Translations]:
    translations = Translations(translations_dir)
    translations.apply("en")
    yield translations
    # English needs no files, so this removes every translator the test installed.
    translations.apply("en")
    QLocale.setDefault(QLocale.system())
