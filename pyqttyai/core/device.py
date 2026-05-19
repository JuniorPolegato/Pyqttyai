"""Device model and status definitions."""

from enum import Enum
from dataclasses import dataclass, field


class Protocol(Enum):
    TELNET = "telnet"
    SSH = "ssh"


class DeviceStatus(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"


@dataclass
class Device:
    """Represents a network device connection."""
    name: str = ""
    host: str = ""
    port: int = 22
    protocol: Protocol = Protocol.TELNET
    username: str = ""
    password: str = ""
    description: str = ""
    eve_node_id: str | None = None
    status: DeviceStatus = field(default=DeviceStatus.DISCONNECTED, repr=False)

    @property
    def display_name(self) -> str:
        """Clean display name: protocol icon + name"""  # + (host:port)."""
        proto_icon = "🔒" if self.protocol == Protocol.SSH else "📡"
        return f"{proto_icon} {self.name}"  # ({self.host}:{self.port})"
