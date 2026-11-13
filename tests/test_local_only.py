"""The integration only talks to the configured player.

The runtime half of the "Local only" badge: the real protocol client runs against a
fake player on 127.0.0.1, and every connection opened during the config flow, setup,
polling and commands is recorded and must go to the configured host and port. The
Wake-on-LAN packet must go to the local broadcast address only. The static half is
scripts/check_local_only.py, which is tested here as well.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
import importlib.util
import json
from pathlib import Path
import shutil
from typing import Any
from unittest.mock import MagicMock, patch

from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.tascam_bdmp4k.const import DOMAIN
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, CONF_HOST, CONF_MAC, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util

from .conftest import MAC

ROOT = Path(__file__).resolve().parents[1]
LOOPBACK = "127.0.0.1"
MEDIA_PLAYER = "media_player.tascam_bd_mp4k"
MAGIC_PACKET = b"\xff" * 6 + bytes.fromhex(MAC.replace(":", "")) * 16

# Answers of a player that is playing, in the form the real firmware sends them.
ANSWERS = {
    "!7?SST": "!7SSTPL",
    "!7?MST": "!7MSTCI",
    "!7?SET": "!7SET0011230",
    "!7?SRT": "!7SRT0004500",
    "!7?STC": "!7TN0003",
    "!7?SGN": "!7GNMX0001",
}


class FakePlayer:
    """A BD-MP4K control port on 127.0.0.1 that answers like the real player."""

    def __init__(self) -> None:
        """Prepare an empty command log."""
        self.received: list[str] = []
        self.port = 0
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        """Listen on a free port on 127.0.0.1."""
        self._server = await asyncio.start_server(self._handle, LOOPBACK, 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        """Stop listening and wait for open connections to finish."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                try:
                    line = await reader.readuntil(b"\r")
                except (asyncio.IncompleteReadError, ConnectionError):
                    break
                command = line.decode("ascii").removesuffix("\r")
                self.received.append(command)
                if command in ANSWERS:
                    writer.write(f"ack+{ANSWERS[command]}".encode("ascii"))
                elif command.startswith("!7?"):
                    writer.write(b"nack")
                else:
                    writer.write(b"ack")
                await writer.drain()
        finally:
            writer.close()


def _load_checker() -> Any:
    spec = importlib.util.spec_from_file_location(
        "check_local_only", ROOT / "scripts" / "check_local_only.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_all_traffic_goes_to_the_player(hass: HomeAssistant, socket_enabled: None) -> None:
    """Config flow, setup, polling and commands only reach the configured host and port."""
    player = FakePlayer()
    await player.start()
    connections: list[tuple[str, int]] = []
    open_connection = asyncio.open_connection

    async def record_connection(host: str, port: int, *args: Any, **kwargs: Any) -> Any:
        connections.append((host, port))
        return await open_connection(host, port, *args, **kwargs)

    try:
        with (
            patch("asyncio.open_connection", new=record_connection),
            patch("custom_components.tascam_bdmp4k.wol.socket") as mock_socket,
        ):
            sock = MagicMock()
            mock_socket.socket.return_value.__enter__.return_value = sock

            # Config flow: the connection test, then setup of the new entry.
            result = await hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_USER}
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], {CONF_HOST: LOOPBACK, CONF_PORT: player.port, CONF_MAC: MAC}
            )
            assert result["type"] is FlowResultType.CREATE_ENTRY
            entry = result["result"]
            await hass.async_block_till_done()
            assert entry.state is ConfigEntryState.LOADED
            assert hass.states.get(MEDIA_PLAYER).state == "playing"

            # Polling.
            for seconds in (11, 22, 33):
                async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=seconds))
                await hass.async_block_till_done()

            # Commands, including power on with Wake-on-LAN.
            await hass.services.async_call(
                "media_player", "media_pause", {ATTR_ENTITY_ID: MEDIA_PLAYER}, blocking=True
            )
            await hass.services.async_call(
                "button",
                "press",
                {ATTR_ENTITY_ID: "button.tascam_bd_mp4k_tray_open"},
                blocking=True,
            )
            await hass.services.async_call(
                "media_player", "turn_on", {ATTR_ENTITY_ID: MEDIA_PLAYER}, blocking=True
            )

            assert await hass.config_entries.async_unload(entry.entry_id)
            await hass.async_block_till_done()
    finally:
        await player.stop()

    assert connections, "the test opened no connections"
    assert set(connections) == {(LOOPBACK, player.port)}
    assert {"!7?SST", "!7?SET", "!7PAS", "!7OPCOP"} <= set(player.received)
    # Wake-on-LAN is the one packet that is not sent to the player's address: a single
    # UDP datagram to the local broadcast address, holding only the player's MAC address.
    sock.sendto.assert_called_once_with(MAGIC_PACKET, ("255.255.255.255", 9))


def test_static_check_passes() -> None:
    """The integration passes scripts/check_local_only.py."""
    checker = _load_checker()
    assert checker.main(["check_local_only.py"]) == 0


def test_static_check_catches_leaks(tmp_path: Path) -> None:
    """The check fails on an integration that could send data elsewhere."""
    checker = _load_checker()
    leaky = tmp_path / "leaky"
    shutil.copytree(ROOT / "custom_components" / "tascam_bdmp4k", leaky)

    manifest = json.loads((leaky / "manifest.json").read_text())
    manifest.update(
        iot_class="cloud_polling",
        requirements=["phonehome==1.0"],
        dependencies=["mqtt"],
        mqtt=["tascam/#"],
    )
    (leaky / "manifest.json").write_text(json.dumps(manifest))

    (leaky / "telemetry.py").write_text(
        "import asyncio\n"
        "import socket\n"
        "import ssl\n"
        "import requests\n"
        "from homeassistant.helpers.aiohttp_client import async_get_clientsession\n\n\n"
        "async def leak(hass):\n"
        "    session = async_get_clientsession(hass)\n"
        "    await session.post('https://telemetry.example.com/collect')\n"
        "    await asyncio.start_server(None, '0.0.0.0', 8080)\n"
        "    await asyncio.open_connection('8.8.8.8', 53)\n"
        "    broadcast = '255.255.255.255'\n"
        "    return 'analytics.vendor.io'\n"
    )

    # The one allowed connection, pointed at a fixed address instead of the configured one.
    protocol = (leaky / "protocol.py").read_text()
    assert "asyncio.open_connection(self._host, self._port)" in protocol
    (leaky / "protocol.py").write_text(
        protocol.replace(
            "asyncio.open_connection(self._host, self._port)",
            "asyncio.open_connection('localhost', 80)",
        )
    )

    # The Wake-on-LAN exception, stretched to TCP, another address, binding and receiving.
    wol = (leaky / "wol.py").read_text()
    assert 'sock.sendto(packet, ("255.255.255.255", WOL_PORT))' in wol
    wol = wol.replace("socket.SOCK_DGRAM", "socket.SOCK_STREAM").replace(
        'sock.sendto(packet, ("255.255.255.255", WOL_PORT))',
        'sock.bind(("0.0.0.0", 9))\n'
        '            sock.sendto(packet, ("8.8.8.8", WOL_PORT))\n'
        "            sock.recvfrom(1024)",
    )
    (leaky / "wol.py").write_text(wol)

    problems = checker.check_manifest(leaky)
    for name in ("telemetry.py", "protocol.py", "wol.py"):
        problems += checker.check_source(leaky / name, f"leaky/{name}")
    text = "\n".join(problems)
    for expected in (
        "iot_class",
        "phonehome",
        "depends on 'mqtt'",
        "uses 'mqtt'",
        "telemetry.py:2: imports socket",
        "imports ssl",
        "imports requests",
        "imports homeassistant.helpers.aiohttp_client",
        "async_get_clientsession(): this integration has no HTTP",
        "session.post(): this integration has no HTTP",
        "start_server() listens",
        "open_connection() outside",
        "open_connection() to a literal address",
        "https://telemetry.example.com",
        "hard-coded IP address '8.8.8.8'",
        "hard-coded IP address '255.255.255.255'",
        "analytics.vendor.io",
        "not a UDP (SOCK_DGRAM) socket",
        "sock.bind()",
        "sock.recvfrom()",
        "sendto() to something other than",
    ):
        assert expected in text, expected
    assert checker.main(["check_local_only.py", str(leaky)]) == 1
