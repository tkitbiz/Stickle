import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from stickle.crypto.keyfile import KeyFile, wrap_with_password, write_key_file

# Runs in a child process. The signal comes from another thread while the main
# thread sits idle in Qt's event loop, which is exactly when Python cannot see it.
CHILD = """
import signal, sys, threading
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from stickle.app.signals import SignalWatcher

app = QApplication([])
if {watch}:
    watcher = SignalWatcher(app.quit)
threading.Timer(0.5, signal.raise_signal, [signal.SIGINT]).start()
QTimer.singleShot(4_000, lambda: app.exit(3))  # the signal was not handled in time
sys.exit(app.exec())
"""


def run_child(watch: bool) -> int | None:
    """Exit code of the child, or None if it was still running after 8 seconds."""
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    try:
        return subprocess.run(
            [sys.executable, "-c", CHILD.format(watch=watch)],
            env=env,
            capture_output=True,
            timeout=8,
            check=False,
        ).returncode
    except subprocess.TimeoutExpired:
        return None


def test_ctrl_c_ends_the_idle_event_loop() -> None:
    assert run_child(watch=True) == 0


def test_without_the_watcher_ctrl_c_is_not_handled_while_idle() -> None:
    # Shows the test above can fail: plain Python + Qt misses the signal (and
    # usually hangs, because even the safety timer cannot run its Python code).
    assert run_child(watch=False) != 0


def sigterm_exit_code(data: Path) -> int:
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "STICKLE_DATA_DIR": str(data)}
    app = subprocess.Popen([sys.executable, "-m", "stickle"], env=env)
    try:
        time.sleep(3)
        assert app.poll() is None, "the app should still be running"
        app.send_signal(signal.SIGTERM)
        return app.wait(timeout=10)
    finally:
        app.kill()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals from another process")
def test_app_quits_on_sigterm_at_first_start(tmp_path: Path) -> None:
    # An empty data folder: the welcome is open when the signal comes, and closing
    # it must end the app, not lead on into the main loop.
    assert sigterm_exit_code(tmp_path) == 0


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals from another process")
def test_app_quits_on_sigterm_at_the_password_prompt(tmp_path: Path) -> None:
    # A password-protected key file makes the app ask for the password, on any system.
    slot = wrap_with_password(bytes(32), "correct horse", opslimit=1, memlimit=8192)
    write_key_file(tmp_path / "keys.json", KeyFile(slot, {}))

    assert sigterm_exit_code(tmp_path) == 0
    assert not (tmp_path / "notes.db").exists()
