"""Manages telnet/SSH connections to devices using raw sockets."""

import socket
import threading
import time
from typing import Optional

from PyQt6.QtCore import pyqtSignal, QThread

from .device import Device, Protocol, DeviceStatus

try:
    import paramiko
    HAS_PARAMIKO = True
except ImportError:
    HAS_PARAMIKO = False


# ── Telnet protocol constants ────────────────────────────
IAC  = bytes([255])  # Interpret As Command
DONT = bytes([254])
DO   = bytes([253])
WONT = bytes([252])
WILL = bytes([251])
SB   = bytes([250])  # Sub-negotiation Begin
SE   = bytes([240])  # Sub-negotiation End
NOP  = bytes([241])


class RawTelnetSocket:
    """
    Minimal telnet client using raw sockets.
    Handles IAC negotiation (refuses everything) — perfect for EVE-NG consoles.
    """

    def __init__(self, host: str, port: int, timeout: float = 10.0):
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.settimeout(0.1)  # Non-blocking reads

    def read(self, bufsize: int = 4096) -> bytes:
        """
        Read available data, stripping/handling telnet IAC sequences.
        Returns b'' if nothing available (timeout), raises on closed.
        """
        try:
            data = self._sock.recv(bufsize)
        except socket.timeout:
            return b""
        except OSError:
            raise EOFError("Connection closed")

        if not data:
            raise EOFError("Connection closed by remote host")

        return self._process_telnet(data)

    def _process_telnet(self, data: bytes) -> bytes:
        """Strip IAC sequences, refusing all DO/WILL negotiations."""
        cleaned = bytearray()
        i = 0
        while i < len(data):
            if data[i:i+1] == IAC:
                if i + 1 >= len(data):
                    break
                cmd = data[i+1:i+2]

                if cmd == IAC:
                    # Escaped 0xFF → literal byte
                    cleaned.append(255)
                    i += 2
                elif cmd in (DO, DONT):
                    # Refuse: reply WONT
                    if i + 2 < len(data):
                        option = data[i+2:i+3]
                        self._sock.sendall(IAC + WONT + option)
                    i += 3
                elif cmd in (WILL, WONT):
                    # Refuse: reply DONT
                    if i + 2 < len(data):
                        option = data[i+2:i+3]
                        self._sock.sendall(IAC + DONT + option)
                    i += 3
                elif cmd == SB:
                    # Skip sub-negotiation until SE
                    end = data.find(IAC + SE, i)
                    if end == -1:
                        break
                    i = end + 2
                else:
                    # Other 2-byte command (NOP, etc.) — skip
                    i += 2
            else:
                cleaned.append(data[i])
                i += 1

        return bytes(cleaned)

    def write(self, data: bytes):
        """Send raw bytes to the connection."""
        self._sock.sendall(data)

    def close(self):
        """Close the socket."""
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._sock.close()


class ConnectionWorker(QThread):
    """Background worker that reads from a network connection."""
    data_received = pyqtSignal(str)
    connection_lost = pyqtSignal(str)
    connected = pyqtSignal()

    def __init__(self, device: Device, parent=None):
        super().__init__(parent)
        self.device = device
        self._running = False
        self._telnet: Optional[RawTelnetSocket] = None
        self._ssh_channel = None
        self._ssh_client: Optional["paramiko.SSHClient"] = None
        self._lock = threading.Lock()

    def run(self):
        """Connect and start reading loop."""
        try:
            if self.device.protocol == Protocol.TELNET:
                self._connect_telnet()
            else:
                self._connect_ssh()

            self._running = True
            self.connected.emit()
            self._read_loop()
        except Exception as e:
            self.connection_lost.emit(f"Connection error: {e}")

    def _connect_telnet(self):
        self._telnet = RawTelnetSocket(
            self.device.host, self.device.port, timeout=10.0
        )

    def _connect_ssh(self):
        if not HAS_PARAMIKO:
            raise RuntimeError("paramiko not installed — SSH unavailable")
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=self.device.host,
            port=self.device.port,
            username=self.device.username,
            password=self.device.password,
            timeout=10,
            look_for_keys=False,
            allow_agent=False,
        )
        self._ssh_client = client
        self._ssh_channel = client.invoke_shell(
            term="xterm-256color", width=120, height=40
        )
        self._ssh_channel.settimeout(0.5)

    def _read_loop(self):
        while self._running:
            try:
                data = self._read_data()
                if data:
                    self.data_received.emit(data)
            except EOFError:
                break
            except Exception:
                time.sleep(0.05)
                continue

        self.connection_lost.emit("Connection closed.")

    def _read_data(self) -> str:
        if self.device.protocol == Protocol.TELNET:
            raw = self._telnet.read(4096)
            if not raw:
                time.sleep(0.05)
                return ""
            return raw.decode("utf-8", errors="replace")
        else:
            if self._ssh_channel.recv_ready():
                data = self._ssh_channel.recv(4096)
                if not data:
                    raise EOFError("SSH channel closed")
                return data.decode("utf-8", errors="replace")
            time.sleep(0.05)
            return ""

    def send(self, text: str):
        """Send text to the device (thread-safe)."""
        with self._lock:
            try:
                if self.device.protocol == Protocol.TELNET:
                    if self._telnet:
                        self._telnet.write(text.encode("utf-8"))
                else:
                    if self._ssh_channel:
                        self._ssh_channel.send(text.encode("utf-8"))
            except (OSError, EOFError):
                pass

    def stop(self):
        """Disconnect cleanly."""
        self._running = False
        with self._lock:
            try:
                if self._telnet:
                    self._telnet.close()
                    self._telnet = None
                if self._ssh_client:
                    self._ssh_client.close()
                    self._ssh_client = None
                    self._ssh_channel = None
            except Exception:
                pass
        self.wait(3000)
