"""Shortcuts through the desktop portal (org.freedesktop.portal.GlobalShortcuts).

Under Wayland an application cannot grab keys; it asks the desktop, which
shows the user the shortcuts once to accept, and lets them be changed in its
own keyboard settings. Stickle runs through XWayland there, but the portal
is reached over D-Bus all the same.

Everything goes over one D-Bus connection of Stickle's own (jeepney), since
the portal ties a session to the connection that made it. Its replies are
read whenever the bus writes to the socket, so nothing here waits.

The steps: register the app id with the host portal (not needed by every
desktop), open a session, bind the shortcuts (the desktop may ask the user),
then hear Activated for each press. The desktop answers each request later,
through a Response signal on the request's own object path.
"""

import logging
import secrets
from collections.abc import Callable
from typing import Any, cast, override

from jeepney import DBusAddress, HeaderFields, Message, MessageType, new_method_call
from jeepney.bus_messages import MatchRule, message_bus
from jeepney.io.blocking import DBusConnection, open_dbus_connection
from PySide6.QtCore import QSocketNotifier

from stickle.platform.hotkeys import Portal

log = logging.getLogger(__name__)

DESKTOP = "org.freedesktop.portal.Desktop"
DESKTOP_PATH = "/org/freedesktop/portal/desktop"
SHORTCUTS = "org.freedesktop.portal.GlobalShortcuts"
REQUEST = "org.freedesktop.portal.Request"
PORTAL = DBusAddress(DESKTOP_PATH, bus_name=DESKTOP, interface=SHORTCUTS)
REGISTRY = DBusAddress(
    DESKTOP_PATH, bus_name=DESKTOP, interface="org.freedesktop.host.portal.Registry"
)
PROPERTIES = DBusAddress(
    DESKTOP_PATH, bus_name=DESKTOP, interface="org.freedesktop.DBus.Properties"
)
ACCEPTED = 0  # a Response's code; 1 is cancelled by the user, 2 anything else

type Variants = dict[str, tuple[str, Any]]
type Handler = Callable[[Message], None]


def _request_path(unique_name: str, token: str) -> str:
    """Where the portal will answer a request made with this handle_token."""
    sender = unique_name.lstrip(":").replace(".", "_")
    return f"{DESKTOP_PATH}/request/{sender}/{token}"


def _token() -> str:
    return f"stickle_{secrets.token_hex(8)}"


class PortalShortcuts(Portal):
    """One session of shortcuts with the desktop, through
    org.freedesktop.portal.GlobalShortcuts (see Portal for what it tells)."""

    def __init__(self, app_id: str, connection: DBusConnection | None = None) -> None:
        super().__init__()
        self._app_id = app_id
        self._connection = connection or open_dbus_connection(bus="SESSION")
        self._unique_name = str(self._connection.unique_name)
        self._replies: dict[int, Handler] = {}
        self._responses: dict[str, Handler] = {}
        self._wanted: list[tuple[str, str, str]] = []
        self._parent_window = ""
        self._session = ""
        self.version = 0
        self._notifier = QSocketNotifier(
            self._connection.sock.fileno(), QSocketNotifier.Type.Read, self
        )
        self._notifier.activated.connect(self.read)
        for rule in (
            MatchRule(type="signal", interface=REQUEST, member="Response"),
            MatchRule(type="signal", interface=SHORTCUTS, member="Activated"),
            MatchRule(type="signal", interface=SHORTCUTS, member="ShortcutsChanged"),
        ):
            self._send(message_bus.AddMatch(rule))

    # Talking

    def _send(self, message: Message, on_reply: Handler | None = None) -> None:
        serial = next(self._connection.outgoing_serial)  # the connection's own count
        if on_reply is not None:
            self._replies[serial] = on_reply
        self._connection.send(message, serial=serial)

    def _ask(self, method: str, signature: str, body: tuple[Any, ...], then: Handler) -> None:
        """A portal request: the answer comes later, as a Response signal."""
        options = cast(Variants, body[-1])
        token = _token()
        options["handle_token"] = ("s", token)
        self._responses[_request_path(self._unique_name, token)] = then
        self._send(new_method_call(PORTAL, method, signature, body), self._refused_if_error)

    def read(self) -> None:
        """Handle every message the bus has sent so far."""
        while True:
            try:
                message = self._connection.receive(timeout=0)
            except TimeoutError:
                return
            except OSError as error:
                log.warning("the desktop portal connection broke: %s", type(error).__name__)
                self._notifier.setEnabled(False)
                self.failed.emit()
                return
            self.handle(message)

    def handle(self, message: Message) -> None:
        header = message.header
        kind = header.message_type
        if kind in (MessageType.method_return, MessageType.error):
            serial = cast(int, header.fields.get(HeaderFields.reply_serial, 0))
            handler = self._replies.pop(serial, None)
            if handler is not None:
                handler(message)
        elif kind == MessageType.signal:
            member = header.fields.get(HeaderFields.member)
            path = str(header.fields.get(HeaderFields.path, ""))
            if member == "Response" and path in self._responses:
                self._responses.pop(path)(message)
            elif member == "Activated" and message.body and message.body[0] == self._session:
                self.activated.emit(str(message.body[1]))
            elif member == "ShortcutsChanged" and message.body[0] == self._session:
                self.bound.emit(self._described(message.body[1]))

    def _refused_if_error(self, message: Message) -> None:
        if message.header.message_type == MessageType.error:
            log.warning("the desktop portal refused a request: %s", message.body[:1])
            self.failed.emit()

    # The steps

    @override
    def bind(self, shortcuts: list[tuple[str, str, str]], parent_window: str = "") -> None:
        """(id, description, preferred trigger or "") for each shortcut; see
        Combo.portal_trigger for how the trigger is written."""
        self._wanted = shortcuts
        self._parent_window = parent_window
        # Tells the portal which app this is (a host app has no id of its own).
        self._send(new_method_call(REGISTRY, "Register", "sa{sv}", (self._app_id, {})), _ignore)
        get = new_method_call(PROPERTIES, "Get", "ss", (SHORTCUTS, "version"))
        self._send(get, self._have_version)

    def _have_version(self, message: Message) -> None:
        if message.header.message_type == MessageType.error:
            log.info("no shortcuts portal on this desktop")
            self.failed.emit()
            return
        _signature, version = message.body[0]
        self.version = int(version)
        options: Variants = {"session_handle_token": ("s", _token())}
        self._ask("CreateSession", "a{sv}", (options,), self._have_session)

    def _have_session(self, message: Message) -> None:
        code, results = cast(tuple[int, Variants], message.body)
        if code != ACCEPTED or "session_handle" not in results:
            log.warning("the desktop portal did not open a session: %d", code)
            self.failed.emit()
            return
        self._session = str(results["session_handle"][1])
        wanted: list[tuple[str, Variants]] = []
        for shortcut_id, text, keys in self._wanted:
            details: Variants = {"description": ("s", text)}
            if keys:  # a suggestion: the desktop decides
                details["preferred_trigger"] = ("s", keys)
            wanted.append((shortcut_id, details))
        no_options: Variants = {}
        body = (self._session, wanted, self._parent_window, no_options)
        self._ask("BindShortcuts", "oa(sa{sv})sa{sv}", body, self._have_shortcuts)

    def _have_shortcuts(self, message: Message) -> None:
        code, results = cast(tuple[int, Variants], message.body)
        if code != ACCEPTED:
            # Turned down by the user: nothing works, as they chose.
            log.info("shortcuts not accepted in the desktop's dialog: %d", code)
            self.bound.emit({shortcut_id: "" for shortcut_id, _, _ in self._wanted})
            return
        self.bound.emit(self._described(results.get("shortcuts", ("", []))[1]))

    def _described(self, shortcuts: list[tuple[str, Variants]]) -> dict[str, str]:
        found = {shortcut_id: "" for shortcut_id, _, _ in self._wanted}
        for shortcut_id, details in shortcuts:
            found[shortcut_id] = str(details.get("trigger_description", ("s", ""))[1])
        return found

    @override
    def configure(self) -> bool:
        """Open the desktop's own page for these shortcuts (portal version 2 on)."""
        if self.version < 2 or not self._session:
            return False
        body: tuple[str, str, Variants] = (self._session, "", {})
        self._send(new_method_call(PORTAL, "ConfigureShortcuts", "osa{sv}", body), _ignore)
        return True


def _ignore(_message: Message) -> None:
    """For requests whose answer changes nothing (an older portal may not know them)."""
