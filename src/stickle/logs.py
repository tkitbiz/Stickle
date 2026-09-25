"""The app's log: local files only, without note text, keys or personal paths.

Nothing is ever sent anywhere; users attach the file to an issue if they want.
Log calls never include note text or keys. As a safety net against paths in
error messages and tracebacks, the data folder is written as <data> and the
home folder as ~.
"""

import logging
import os
import re
import sys
import threading
import time
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

LOG_FILE = "stickle.log"
MAX_BYTES = 5 * 1024 * 1024
FILES_KEPT = 3  # the current file and two older ones

log = logging.getLogger("stickle")


class Redactor:
    """Replaces personal folders in text: the most specific first."""

    def __init__(self, folders: list[tuple[Path, str]]) -> None:
        patterns: list[tuple[re.Pattern[str], str]] = []
        flags = re.IGNORECASE if sys.platform == "win32" else 0
        for folder, name in folders:
            spellings = {str(folder), folder.as_posix(), str(folder).replace("\\", "\\\\")}
            for spelling in sorted(spellings, key=len, reverse=True):
                if len(spelling) > 1:  # never replace a bare "/"
                    patterns.append((re.compile(re.escape(spelling), flags), name))
        self._patterns = patterns

    def __call__(self, text: str) -> str:
        for pattern, name in self._patterns:
            text = pattern.sub(name, text)
        return text


_redact: Redactor = Redactor([])


def redact(text: str) -> str:
    return _redact(text)


class _Formatter(logging.Formatter):
    converter = time.gmtime

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def _log_uncaught(
    kind: type[BaseException], error: BaseException | None, trace: TracebackType | None
) -> None:
    if error is not None and not isinstance(error, KeyboardInterrupt):
        log.critical("unhandled exception", exc_info=(kind, error, trace))


def setup_logging(folder: Path, data: Path, home: Path | None = None) -> None:
    global _redact
    home = Path.home() if home is None else home
    _redact = Redactor([(data, "<data>"), (home, "~")])
    formatter = _Formatter("%(asctime)sZ %(levelname)s %(name)s: %(message)s", "%Y-%m-%dT%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if os.environ.get("STICKLE_LOG") == "debug" else logging.INFO)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        file = RotatingFileHandler(
            folder / LOG_FILE, maxBytes=MAX_BYTES, backupCount=FILES_KEPT - 1, encoding="utf-8"
        )
        file.setFormatter(formatter)
        root.addHandler(file)
    except OSError:
        pass  # a read-only data folder must not stop the app; stderr still works
    if sys.stderr is not None:  # a Windows GUI build has none
        console = logging.StreamHandler()
        console.setLevel(logging.WARNING)
        console.setFormatter(formatter)
        root.addHandler(console)

    previous_hook = sys.excepthook

    def excepthook(
        kind: type[BaseException], error: BaseException, trace: TracebackType | None
    ) -> None:
        _log_uncaught(kind, error, trace)
        previous_hook(kind, error, trace)

    sys.excepthook = excepthook
    previous_thread_hook: Callable[[threading.ExceptHookArgs], object] = threading.excepthook

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        _log_uncaught(args.exc_type, args.exc_value, args.exc_traceback)
        previous_thread_hook(args)

    threading.excepthook = thread_hook
