# Types for the parts of jeepney (pure Python D-Bus, no type hints of its own) Stickle uses.
from enum import Enum, IntEnum
from typing import Any

class MessageType(Enum):
    method_call = 1
    method_return = 2
    error = 3
    signal = 4

class HeaderFields(IntEnum):
    path = 1
    interface = 2
    member = 3
    error_name = 4
    reply_serial = 5
    destination = 6
    sender = 7
    signature = 8
    unix_fds = 9

class Header:
    message_type: MessageType
    serial: int
    fields: dict[HeaderFields, Any]

class Message:
    header: Header
    body: tuple[Any, ...]
    def __init__(self, header: Header, body: tuple[Any, ...]) -> None: ...
    def serialise(self, serial: int | None = None, fds: Any = None) -> bytes: ...

class DBusAddress:
    object_path: str
    bus_name: str | None
    interface: str | None
    def __init__(
        self, object_path: str, bus_name: str | None = None, interface: str | None = None
    ) -> None: ...

def new_method_call(
    remote_obj: DBusAddress, method: str, signature: str | None = None, body: tuple[Any, ...] = ()
) -> Message: ...
def new_method_return(
    parent_msg: Message, signature: str | None = None, body: tuple[Any, ...] = ()
) -> Message: ...
def new_error(
    parent_msg: Message, error_name: str, signature: str | None = None, body: tuple[Any, ...] = ()
) -> Message: ...
def new_signal(
    emitter: DBusAddress, signal: str, signature: str | None = None, body: tuple[Any, ...] = ()
) -> Message: ...
