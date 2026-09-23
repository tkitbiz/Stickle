"""Quit cleanly on Ctrl+C and termination signals while Qt's event loop runs.

Python only runs its signal handlers when it gets to execute Python code,
which never happens while Qt's C++ event loop sits idle, so Ctrl+C and
SIGTERM (sent at logout and shutdown) would otherwise be ignored.
signal.set_wakeup_fd makes the interpreter write a byte to a socket the moment
a signal arrives; a QSocketNotifier on the other end wakes the event loop, the
Python handler runs and quits the application. Nothing polls, so an idle app
still uses no CPU.
"""

import contextlib
import signal
import socket
import sys
from collections.abc import Callable

from PySide6.QtCore import QObject, QSocketNotifier

QUIT_SIGNALS = (
    [signal.SIGINT, signal.SIGTERM]
    if sys.platform == "win32"
    else [signal.SIGINT, signal.SIGTERM, signal.SIGHUP]
)


class SignalWatcher(QObject):
    def __init__(self, on_quit: Callable[[], object], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._reader, self._writer = socket.socketpair()
        self._reader.setblocking(False)
        self._writer.setblocking(False)
        self._previous_wakeup_fd = signal.set_wakeup_fd(self._writer.fileno())
        self._notifier = QSocketNotifier(self._reader.fileno(), QSocketNotifier.Type.Read, self)
        self._notifier.activated.connect(self._drain)
        self._previous_handlers = {sig: signal.getsignal(sig) for sig in QUIT_SIGNALS}
        for sig in QUIT_SIGNALS:
            signal.signal(sig, lambda _signum, _frame: on_quit())

    def _drain(self) -> None:
        # Reading empties the socket; by now the Python handler has run.
        with contextlib.suppress(BlockingIOError):
            self._reader.recv(64)

    def close(self) -> None:
        """Restore the previous handlers (for tests and orderly shutdown)."""
        for sig, handler in self._previous_handlers.items():
            signal.signal(sig, handler)
        signal.set_wakeup_fd(self._previous_wakeup_fd)
        self._notifier.setEnabled(False)
        self._reader.close()
        self._writer.close()
