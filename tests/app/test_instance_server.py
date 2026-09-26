"""A second start of Stickle asks the running one to show itself, and ends."""

import os
import socket
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from stickle.app.instance_server import InstanceServer
from stickle.platform.instance import InstanceLock, ask_to_show, server_name


@pytest.fixture
def server(qtbot: QtBot, tmp_path: Path) -> Iterator[InstanceServer]:
    lock = InstanceLock(tmp_path)
    assert lock.acquire()
    server = InstanceServer(tmp_path)
    yield server
    server.deleteLater()
    lock.release()


def send_raw(folder: Path, data: bytes) -> None:
    name = server_name(folder)
    if sys.platform == "win32":
        with Path(rf"\\.\pipe\{name}").open("wb", buffering=0) as pipe:
            pipe.write(data)
    else:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.connect(name)
            connection.sendall(data)


def in_background(action: object) -> threading.Thread:
    assert callable(action)
    thread = threading.Thread(target=action)
    thread.start()
    return thread


def test_a_second_start_is_heard(qtbot: QtBot, server: InstanceServer, tmp_path: Path) -> None:
    answered: list[bool] = []

    with qtbot.waitSignal(server.show_requested, timeout=5000):
        thread = in_background(lambda: answered.append(ask_to_show(tmp_path)))
    thread.join(timeout=5)

    assert answered == [True]
    assert server.requested


def test_anything_else_is_ignored(qtbot: QtBot, server: InstanceServer, tmp_path: Path) -> None:
    with qtbot.assertNotEmitted(server.show_requested, wait=500):
        thread = in_background(lambda: send_raw(tmp_path, b"open the notes\n"))
        qtbot.wait(300)
        thread.join(timeout=5)
        thread = in_background(lambda: send_raw(tmp_path, b"x" * 500))
        qtbot.wait(300)
        thread.join(timeout=5)

    assert not server.requested


@pytest.mark.skipif(sys.platform == "win32", reason="socket files: Linux and macOS")
def test_a_socket_file_left_by_a_crash_is_replaced(qtbot: QtBot, tmp_path: Path) -> None:
    Path(server_name(tmp_path)).write_text("left over")
    lock = InstanceLock(tmp_path)
    assert lock.acquire()
    server = InstanceServer(tmp_path)

    with qtbot.waitSignal(server.show_requested, timeout=5000):
        thread = in_background(lambda: ask_to_show(tmp_path))
    thread.join(timeout=5)
    lock.release()


def test_starting_stickle_again_shows_the_running_one_and_opens_nothing(
    qtbot: QtBot, server: InstanceServer, tmp_path: Path
) -> None:
    environment = {**os.environ, "STICKLE_DATA_DIR": str(tmp_path)}
    process = subprocess.Popen([sys.executable, "-m", "stickle"], env=environment)

    qtbot.waitSignal(server.show_requested, timeout=15000).wait()
    assert process.wait(timeout=15) == 0

    # It never got as far as the notes: no database, no key, no log.
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(
        path.name for path in tmp_path.iterdir() if path.name.startswith("instance.")
    )
