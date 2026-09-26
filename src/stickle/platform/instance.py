"""One Stickle per user and data folder.

The running app holds a lock on a file in the data folder; the operating
system lets go of it when the process ends, however it ends, so a crash
never leaves a stale lock. A second start that cannot take the lock asks
the running app, through a local socket only the same user can reach, to
show itself, and ends without touching the notes. This side needs only the
standard library, so it runs before Qt loads.
"""

import hashlib
import os
import socket
import sys
import tempfile
import time
from pathlib import Path
from typing import IO

LOCK_FILE = "instance.lock"
SHOW = b"show\n"
CONNECT_FOR_S = 5.0  # the running app may itself still be starting
RETRY_S = 0.1


def _socket_folder(data_folder: Path) -> Path:
    """A short folder only this user can use, for the socket file.

    Socket paths are limited to about 100 characters, which a data folder
    can exceed; the user's runtime folder or a private folder under the
    temporary one stays short. If that folder is not safely this user's,
    the data folder (private too) is used and a long path simply fails.
    """
    if sys.platform == "win32":
        return data_folder
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime and Path(runtime).is_dir():
        return Path(runtime)
    folder = Path(tempfile.gettempdir()) / f"stickle-{os.getuid()}"
    try:
        folder.mkdir(mode=0o700, exist_ok=True)
        status = folder.lstat()
    except OSError:
        return data_folder
    # Someone else could have made it first, to listen in their place.
    if status.st_uid != os.getuid() or status.st_mode & 0o077 or folder.is_symlink():
        return data_folder
    return folder


def server_name(folder: Path) -> str:
    """Where the running app listens: a named pipe on Windows, a socket file elsewhere."""
    digest = hashlib.sha256(str(folder.resolve()).lower().encode("utf-8")).hexdigest()[:24]
    if sys.platform == "win32":
        return f"stickle-{digest}"
    return str(_socket_folder(folder) / f"stickle-{digest}.sock")


class InstanceLock:
    """Held for as long as this process runs Stickle on this data folder."""

    def __init__(self, folder: Path) -> None:
        self._path = folder / LOCK_FILE
        self._file: IO[bytes] | None = None

    def acquire(self) -> bool:
        """True if no other Stickle holds the lock (it is then held until release)."""
        file = self._path.open("a+b")
        try:
            if sys.platform == "win32":
                import msvcrt

                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            file.close()
            return False
        self._file = file
        return True

    def release(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


def ask_to_show(folder: Path, timeout: float = CONNECT_FOR_S) -> bool:
    """Ask the running Stickle to show itself; False if it could not be reached."""
    name = server_name(folder)
    deadline = time.monotonic() + timeout
    while True:
        try:
            if sys.platform == "win32":
                with Path(rf"\\.\pipe\{name}").open("wb", buffering=0) as pipe:
                    pipe.write(SHOW)
            else:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                    connection.settimeout(timeout)
                    connection.connect(name)
                    connection.sendall(SHOW)
            return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(RETRY_S)
