"""Tests for the BD-MP4K protocol client, against a fake player on 127.0.0.1."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import MagicMock, patch

import pytest

from custom_components.tascam_bdmp4k import const, protocol
from custom_components.tascam_bdmp4k.coordinator import parse_hms, parse_number
from custom_components.tascam_bdmp4k.protocol import (
    MAX_MESSAGE_LENGTH,
    TascamBusyError,
    TascamClient,
    TascamConnectionError,
    TascamNackError,
    validate_command,
)
from custom_components.tascam_bdmp4k.wol import async_send_magic_packet, normalize_mac
from homeassistant.core import HomeAssistant


class FakeDevice:
    """A minimal BD-MP4K control port that answers like the real player."""

    def __init__(self) -> None:
        """Prepare an empty reply table."""
        self.replies: dict[str, bytes | list[bytes]] = {}
        self.received: list[str] = []
        self.port = 0
        self._server: asyncio.Server | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def start(self) -> None:
        """Listen on a free port on 127.0.0.1."""
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        """Stop listening and wait for open connections to finish."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    def push(self, data: bytes) -> None:
        """Send unsolicited data, such as a status notification."""
        if self._writer is not None:
            self._writer.write(data)

    async def wait_for_received(self, command: str) -> None:
        """Wait until the device has received the given command."""
        async with asyncio.timeout(2):
            while command not in self.received:
                await asyncio.sleep(0.01)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writer = writer
        try:
            while True:
                try:
                    line = await reader.readuntil(b"\r")
                except (asyncio.IncompleteReadError, ConnectionError):
                    break
                command = line.decode("ascii").removesuffix("\r")
                self.received.append(command)
                reply = self.replies.get(command)
                if isinstance(reply, list):
                    # A list of replies: one per attempt, the last one repeats.
                    reply = reply.pop(0) if len(reply) > 1 else reply[0]
                if reply:
                    writer.write(reply)
                    await writer.drain()
        finally:
            self._writer = None
            writer.close()


@pytest.fixture
async def device(socket_enabled: None) -> AsyncGenerator[FakeDevice]:
    """Run a fake player on 127.0.0.1 for the duration of a test."""
    fake = FakeDevice()
    await fake.start()
    yield fake
    await fake.stop()


@pytest.fixture
async def client(device: FakeDevice) -> AsyncGenerator[TascamClient]:
    """Return a client for the fake player, disconnected after the test."""
    tascam = TascamClient("127.0.0.1", device.port)
    yield tascam
    await tascam.async_disconnect()


async def test_control_command_is_acknowledged(device: FakeDevice, client: TascamClient) -> None:
    """A control command returns once the player replies with ack."""
    device.replies["!7PLY"] = b"ack"

    assert await client.async_send("!7PLY") is None
    assert client.connected
    assert device.received == ["!7PLY"]


async def test_status_request_returns_answer(device: FakeDevice, client: TascamClient) -> None:
    """A status request returns the answer that follows the ack."""
    device.replies["!7?SST"] = b"ack+!7SSTPL"

    assert await client.async_send("!7?SST") == "!7SSTPL"


async def test_nack_raises(device: FakeDevice, client: TascamClient) -> None:
    """A nack is raised as TascamNackError, without retrying."""
    device.replies["!7?SRT"] = b"nack"

    with pytest.raises(TascamNackError):
        await client.async_send("!7?SRT")
    assert device.received == ["!7?SRT"]


async def test_notification_is_dispatched_and_acknowledged(
    device: FakeDevice, client: TascamClient
) -> None:
    """A pushed status notification reaches the callback and is acknowledged."""
    device.replies["!7PLY"] = b"ack"
    received: asyncio.Queue[str] = asyncio.Queue()
    client.set_notification_callback(received.put_nowait)
    await client.async_send("!7PLY")

    device.push(b"!7MSTTO")
    async with asyncio.timeout(2):
        assert await received.get() == "!7MSTTO"
    await device.wait_for_received("ack")


async def test_notification_mixed_with_answer(device: FakeDevice, client: TascamClient) -> None:
    """A notification arriving together with an answer is told apart from it."""
    device.replies["!7?SET"] = b"!7MSTTCack+!7SET0011230"
    received: list[str] = []
    client.set_notification_callback(received.append)

    assert await client.async_send("!7?SET") == "!7SET0011230"
    assert received == ["!7MSTTC"]


async def test_connection_refused_is_retried_then_raised(
    device: FakeDevice, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A player that refuses connections raises TascamConnectionError after a retry."""
    monkeypatch.setattr(protocol, "RETRY_DELAY", 0)
    port = device.port
    await device.stop()
    tascam = TascamClient("127.0.0.1", port)

    with pytest.raises(TascamConnectionError):
        await tascam.async_send("!7PLY")
    assert not tascam.connected


async def test_no_reply_disconnects(
    device: FakeDevice, client: TascamClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A command without a reply closes the connection and raises after a retry."""
    monkeypatch.setattr(protocol, "RETRY_DELAY", 0)
    monkeypatch.setattr(protocol, "RESPONSE_TIMEOUT", 0.1)

    with pytest.raises(TascamConnectionError):
        await client.async_send("!7STP")
    assert device.received == ["!7STP", "!7STP"]
    assert not client.connected


async def test_single_attempt_without_retry(
    device: FakeDevice, client: TascamClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without retry a command is tried once, which keeps polling a standby player quiet."""
    monkeypatch.setattr(protocol, "RESPONSE_TIMEOUT", 0.1)

    with pytest.raises(TascamConnectionError):
        await client.async_send("!7?SST", retry=False)
    assert device.received == ["!7?SST"]


async def test_busy_reply_is_resent(
    device: FakeDevice, client: TascamClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A busy player gets the command once more, over the same connection."""
    monkeypatch.setattr(protocol, "BUSY_DELAY", 0)
    device.replies["!7PLY"] = [b"@0BDERBUSY", b"ack"]

    assert await client.async_send("!7PLY") is None
    assert device.received == ["!7PLY", "!7PLY"]
    assert client.connected


async def test_busy_twice_raises(
    device: FakeDevice, client: TascamClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A player that stays busy raises TascamBusyError, which counts as a NACK."""
    monkeypatch.setattr(protocol, "BUSY_DELAY", 0)
    device.replies["!7?SET"] = [b"@0BDERBUSY"]

    with pytest.raises(TascamBusyError):
        await client.async_send("!7?SET")
    assert issubclass(TascamBusyError, TascamNackError)


def test_notification_ack_fits_the_players_window() -> None:
    """Notifications are acknowledged fast enough, and the ack keeps the 30 ms gap."""
    # The player waits 30 ms for the ack and otherwise sends the notification again.
    assert protocol.FLUSH_TIMEOUT < 0.03
    tascam = TascamClient("127.0.0.1", 9030)
    writer = MagicMock()
    tascam._writer = writer

    tascam._dispatch("!7SSTPL")
    writer.write.assert_called_once_with(b"ack\r")
    assert tascam._last_command > 0


def test_all_commands_pass_the_guard() -> None:
    """Every command and request the integration defines is well formed."""
    commands = [value for name, value in vars(const).items() if name.startswith(("CMD_", "REQ_"))]
    assert len(commands) > 20
    for command in commands:
        validate_command(command)


@pytest.mark.parametrize(
    "command",
    ["!7PLY\r!7INI", "!7PLY\n", "!7ply", "PLY", "!7", "!7?", "!7OPC OP", "!7PLY" + "A" * 600],
)
async def test_malformed_command_is_refused(
    device: FakeDevice, client: TascamClient, command: str
) -> None:
    """Commands with other characters, or that are too long, never reach the player."""
    with pytest.raises(ValueError):
        validate_command(command)
    with pytest.raises(ValueError):
        await client.async_send(command)
    assert device.received == []


def test_long_message_split_across_reads() -> None:
    """A message longer than a few bytes survives being split across reads."""
    tascam = TascamClient("127.0.0.1", 9030)
    received: list[str] = []
    tascam.set_notification_callback(received.append)
    message = "!7XYZ" + "AB12" * 25

    rest = tascam._dispatch_buffer(message[:60], final=False)
    rest = tascam._dispatch_buffer(rest + message[60:], final=False)
    assert received == []
    tascam._dispatch_buffer(rest, final=True)
    assert received == [message]


def test_oversized_message_is_dropped() -> None:
    """Input longer than the protocol allows is dropped and never grows the buffer."""
    tascam = TascamClient("127.0.0.1", 9030)
    received: list[str] = []
    tascam.set_notification_callback(received.append)
    stream = "!7XYZ" + "A" * 2000

    rest = ""
    for start in range(0, len(stream), 256):
        rest = tascam._dispatch_buffer(rest + stream[start : start + 256], final=False)
        assert len(rest) <= MAX_MESSAGE_LENGTH
    tascam._dispatch_buffer(rest, final=True)
    tascam._dispatch_buffer("!7XYZ" + "A" * MAX_MESSAGE_LENGTH, final=True)
    assert received == []


@pytest.mark.parametrize(
    ("value", "seconds"),
    [("0011230", 4350), ("0000000", 0), ("1000000", 360000), ("UNKNOWN", None), ("12", None)],
)
def test_parse_hms(value: str, seconds: int | None) -> None:
    """Times are hhhmmss; anything else is unknown."""
    assert parse_hms(value) == seconds


@pytest.mark.parametrize(("value", "number"), [("0003", 3), ("9999", 9999), ("UNKN", None)])
def test_parse_number(value: str, number: int | None) -> None:
    """Chapter and title numbers are four digits or UNKN."""
    assert parse_number(value) == number


@pytest.mark.parametrize(
    ("value", "normalized"),
    [
        ("00:11:22:33:44:55", "00:11:22:33:44:55"),
        ("00-11-22-AA-BB-CC", "00:11:22:aa:bb:cc"),
        (" 001122aabbcc ", "00:11:22:aa:bb:cc"),
        ("00:11:22:33:44", None),
        ("not-a-mac", None),
    ],
)
def test_normalize_mac(value: str, normalized: str | None) -> None:
    """MAC addresses are accepted with or without separators."""
    assert normalize_mac(value) == normalized


async def test_magic_packet(hass: HomeAssistant) -> None:
    """The magic packet is six 0xff bytes and the MAC address sixteen times."""
    with patch("custom_components.tascam_bdmp4k.wol.socket") as mock_socket:
        sock = MagicMock()
        mock_socket.socket.return_value.__enter__.return_value = sock
        await async_send_magic_packet(hass, "00:11:22:33:44:55")

    packet = b"\xff" * 6 + bytes.fromhex("001122334455") * 16
    sock.sendto.assert_called_once_with(packet, ("255.255.255.255", 9))
