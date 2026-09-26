"""One Stickle per user and data folder: the lock, and asking the running one to show itself."""

import os
import subprocess
import sys
import time
from pathlib import Path

from stickle.platform.instance import InstanceLock, ask_to_show, server_name

HOLD_LOCK = """
import sys
from pathlib import Path
from stickle.platform.instance import InstanceLock
lock = InstanceLock(Path(sys.argv[1]))
print("held" if lock.acquire() else "busy", flush=True)
sys.stdin.readline()
"""


def hold_lock_elsewhere(folder: Path) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        [sys.executable, "-c", HOLD_LOCK, str(folder)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "held"
    return process


def test_a_second_process_cannot_take_the_lock(tmp_path: Path) -> None:
    other = hold_lock_elsewhere(tmp_path)
    try:
        assert not InstanceLock(tmp_path).acquire()
    finally:
        other.communicate("\n", timeout=10)


def test_the_lock_is_free_once_the_holder_is_gone_however_it_ended(tmp_path: Path) -> None:
    other = hold_lock_elsewhere(tmp_path)
    other.kill()  # as in a crash: no chance to clean up
    other.wait(timeout=10)

    lock = InstanceLock(tmp_path)
    # Windows lets go of a killed process's lock a moment later.
    deadline = time.monotonic() + 5
    while not lock.acquire():
        assert time.monotonic() < deadline
        time.sleep(0.1)
    lock.release()


def test_released_lock_can_be_taken_again(tmp_path: Path) -> None:
    lock = InstanceLock(tmp_path)
    assert lock.acquire()
    lock.release()

    assert InstanceLock(tmp_path).acquire()


def test_nobody_to_ask_gives_up_after_the_timeout(tmp_path: Path) -> None:
    started = time.monotonic()

    assert not ask_to_show(tmp_path, timeout=0.3)
    assert time.monotonic() - started < 3


def test_each_data_folder_has_its_own_name(tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()

    assert server_name(first) != server_name(second)
    assert server_name(first) == server_name(first)
    if sys.platform != "win32":
        assert server_name(first).startswith(os.fspath(first))
