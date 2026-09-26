"""Where a second start of Stickle asks the running one to show itself."""

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from stickle.platform.instance import SHOW, server_name

log = logging.getLogger(__name__)
MAX_MESSAGE = 64  # "show\n": anything longer is not from Stickle


class InstanceServer(QObject):
    """Listens while this process holds the instance lock (stickle.platform.instance)."""

    show_requested = Signal()

    def __init__(self, folder: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.requested = False  # asked before anyone was listening to show_requested
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        name = server_name(folder)
        # Holding the lock means no other Stickle listens here: a socket file
        # still there was left by one that crashed.
        QLocalServer.removeServer(name)
        if not self._server.listen(name):
            # Stickle runs on; a second start then only fails to bring it forward.
            log.warning("cannot listen for a second start: %s", self._server.errorString())
        self._server.newConnection.connect(self._accept)

    def _accept(self) -> None:
        while self._server.hasPendingConnections():
            connection = self._server.nextPendingConnection()
            # Left to the server, which owns it: deleting it here as well
            # crashed on Linux. A second start is rare; each leaves a few bytes.
            connection.readyRead.connect(self._ready)
            self._read(connection)

    def _ready(self) -> None:
        connection = self.sender()
        if isinstance(connection, QLocalSocket):
            self._read(connection)

    def _read(self, connection: QLocalSocket) -> None:
        if connection.bytesAvailable() > MAX_MESSAGE:
            connection.abort()
            return
        if not connection.canReadLine():
            return
        line = connection.readLine(MAX_MESSAGE).data()
        connection.disconnectFromServer()
        if line == SHOW:
            self.requested = True
            self.show_requested.emit()
