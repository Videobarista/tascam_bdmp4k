"""Wake-on-LAN support for the Tascam BD-MP4K.

Power-on over the Ethernet control protocol is not supported by the
device; the protocol specification prescribes Wake-on-LAN instead.
"""

from __future__ import annotations

import re
import socket

from homeassistant.core import HomeAssistant

MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}[:\-]?){5}[0-9A-Fa-f]{2}$")
WOL_PORT = 9


def normalize_mac(mac: str) -> str | None:
    """Validate and normalize a MAC address to aa:bb:cc:dd:ee:ff."""
    mac = mac.strip()
    if not MAC_RE.match(mac):
        return None
    raw = mac.replace(":", "").replace("-", "").lower()
    return ":".join(raw[i : i + 2] for i in range(0, 12, 2))


async def async_send_magic_packet(hass: HomeAssistant, mac: str) -> None:
    """Broadcast a Wake-on-LAN magic packet for the given MAC address."""
    raw = bytes.fromhex(mac.replace(":", ""))
    packet = b"\xff" * 6 + raw * 16

    def _send() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(packet, ("255.255.255.255", WOL_PORT))

    await hass.async_add_executor_job(_send)
