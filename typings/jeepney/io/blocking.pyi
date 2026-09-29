import socket
from collections.abc import Iterator

from jeepney import Message

class DBusConnection:
    sock: socket.socket
    unique_name: str
    outgoing_serial: Iterator[int]
    def send(self, message: Message, serial: int | None = None) -> None: ...
    def receive(self, *, timeout: float | None = None) -> Message: ...
    def close(self) -> None: ...

def open_dbus_connection(
    bus: str = "SESSION", enable_fds: bool = False, auth_timeout: float = 1.0
) -> DBusConnection: ...
