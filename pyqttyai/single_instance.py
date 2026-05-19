"""Single-instance manager using QLocalServer / QLocalSocket."""

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

APP_SOCKET_NAME = "pyqttyai-instance"


class SingleInstance(QObject):
    """Ensures only one app instance runs. Forwards args to the primary."""

    message_received = pyqtSignal(str)  # emitted when 2nd instance sends data

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server: QLocalServer | None = None
        self._is_primary = False

    def try_start(self, args: list[str]) -> bool:
        """Try to become the primary instance.

        Returns True  → we ARE the primary (start the UI).
        Returns False → another instance exists (we sent args and should quit).
        """
        # Try connecting to an existing instance
        socket = QLocalSocket(self)
        socket.connectToServer(APP_SOCKET_NAME)

        if socket.waitForConnected(1000):
            # ── Another instance is running → send our argument ──
            if args:
                socket.write(args[0].encode("utf-8"))
                socket.waitForBytesWritten(2000)
            socket.disconnectFromServer()
            return False

        # ── No existing instance → we become the primary ──
        self._is_primary = True

        # Clean up stale socket (e.g. after crash)
        QLocalServer.removeServer(APP_SOCKET_NAME)

        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)

        if not self._server.listen(APP_SOCKET_NAME):
            print(f"⚠ Could not start local server: {self._server.errorString()}")

        return True

    def _on_new_connection(self):
        """Handle incoming connection from a second instance."""
        client = self._server.nextPendingConnection()
        if client:
            client.waitForReadyRead(2000)
            data = client.readAll().data().decode("utf-8").strip()
            if data:
                self.message_received.emit(data)
            client.disconnectFromServer()
