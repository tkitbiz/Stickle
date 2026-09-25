import logging
import sys
import threading
from collections.abc import Iterator
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from stickle import logs
from stickle.logs import FILES_KEPT, LOG_FILE, MAX_BYTES, Redactor, setup_logging


@pytest.fixture
def restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    hooks = (sys.excepthook, threading.excepthook)
    redactor = logs._redact  # pyright: ignore[reportPrivateUsage]
    yield
    for handler in root.handlers:
        if handler not in handlers:
            handler.close()
    root.handlers[:] = handlers
    root.setLevel(level)
    sys.excepthook, threading.excepthook = hooks
    logs._redact = redactor  # pyright: ignore[reportPrivateUsage]


def test_personal_folders_are_hidden_in_any_spelling() -> None:
    home = Path("C:/Users/Kim") if sys.platform == "win32" else Path("/home/kim")
    data = home / "AppData" / "Roaming" / "Stickle"
    redact = Redactor([(data, "<data>"), (home, "~")])

    for folder, name in ((data, "<data>"), (home, "~")):
        assert redact(f"at {folder}{'/'}x") == f"at {name}/x"
        assert redact(f"at {folder.as_posix()}/x") == f"at {name}/x"
    if sys.platform == "win32":
        assert redact(r"C:\USERS\KIM\notes") == r"~\notes"  # Windows paths ignore case
        assert redact(r"'C:\\Users\\Kim\\x'") == r"'~\\x'"  # as repr() writes it


def test_log_file_is_written_with_paths_hidden(tmp_path: Path, restore_logging: None) -> None:
    data = tmp_path / "data"
    setup_logging(data / "logs", data=data, home=tmp_path)

    logging.getLogger("stickle.test").warning("could not open %s", data / "notes.db")

    text = (data / "logs" / LOG_FILE).read_text(encoding="utf-8")
    assert "could not open <data>" in text
    assert str(tmp_path) not in text


def test_log_files_are_rotated_at_five_megabytes_keeping_three(
    tmp_path: Path, restore_logging: None
) -> None:
    setup_logging(tmp_path / "logs", data=tmp_path)
    handlers = [h for h in logging.getLogger().handlers if isinstance(h, RotatingFileHandler)]

    assert len(handlers) == 1
    assert handlers[0].maxBytes == MAX_BYTES == 5 * 1024 * 1024
    assert handlers[0].backupCount + 1 == FILES_KEPT == 3


def test_crashes_are_logged(tmp_path: Path, restore_logging: None) -> None:
    # Stand in for the default hooks (which print, and which pytest turns into failures).
    def quiet(*_: object) -> None:
        pass

    sys.excepthook = quiet
    threading.excepthook = quiet
    setup_logging(tmp_path / "logs", data=tmp_path)
    try:
        raise ValueError("boom")
    except ValueError as error:
        sys.excepthook(ValueError, error, error.__traceback__)

    thread = threading.Thread(target=lambda: 1 / 0)
    thread.start()
    thread.join()

    text = (tmp_path / "logs" / LOG_FILE).read_text(encoding="utf-8")
    assert "ValueError: boom" in text
    assert "ZeroDivisionError" in text
