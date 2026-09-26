"""Settings needed before the notes database can be opened, in startup.json.

The database is encrypted, but some things must be known before it is
open: the language of the password prompt and of the recovery screen. They
live in this small plain file in the data folder, which is why only
settings that reveal nothing about the notes may go here. A file that is
missing or damaged counts as empty: the app then follows the system.
"""

import json
import os
import sys
from pathlib import Path
from typing import cast

FILE_NAME = "startup.json"
LANGUAGES = frozenset({"en", "ko"})


def _write_atomically(path: Path, data: bytes) -> None:
    """Replace the file whole, flushed to disk, so it is never half written."""
    temporary = path.with_name(path.name + ".new")
    try:
        with temporary.open("wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    if sys.platform != "win32":
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


class StartupSettings:
    def __init__(self, folder: Path) -> None:
        self._path = folder / FILE_NAME

    def _read(self) -> dict[str, object]:
        try:
            decoded: object = json.loads(self._path.read_bytes())
        except OSError, ValueError:
            return {}
        return cast(dict[str, object], decoded) if isinstance(decoded, dict) else {}

    @property
    def language(self) -> str | None:
        """The interface language chosen on this computer; None follows the system."""
        value = self._read().get("language")
        return value if isinstance(value, str) and value in LANGUAGES else None

    def set_language(self, language: str | None) -> None:
        if language is not None and language not in LANGUAGES:
            raise ValueError(f"unknown language: {language!r}")
        if language == self.language:
            return
        # Keeps whatever else is in the file (written by a newer version, say).
        values = self._read()
        if language is None:
            values.pop("language", None)
        else:
            values["language"] = language
        data = json.dumps(values, indent=2, ensure_ascii=False).encode("utf-8")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        _write_atomically(self._path, data)
