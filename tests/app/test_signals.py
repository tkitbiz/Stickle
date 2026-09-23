import os
import signal
import subprocess
import sys
import time

import pytest

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


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals from another process")
def test_running_app_quits_on_sigterm() -> None:
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    app = subprocess.Popen([sys.executable, "-m", "stickle"], env=env)
    try:
        time.sleep(3)
        assert app.poll() is None, "the app should still be running"
        app.send_signal(signal.SIGTERM)
        assert app.wait(timeout=10) == 0
    finally:
        app.kill()
