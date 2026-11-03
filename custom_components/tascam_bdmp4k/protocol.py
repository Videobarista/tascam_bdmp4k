"""Async TCP protocol client for the Tascam BD-MP4K.

The BD-MP4K protocol specification requires that the TCP connection is held
open continuously and that only one client connects at a time. This client
keeps a single connection with a background listener task, so unsolicited
status notifications from the player are received and dispatched in real
time (push) while commands and status requests share the same connection.

Protocol notes (RS-232C/Ethernet spec v1.01):
- Commands are ASCII, start with ``!7`` and end with CR (0x0D).
- The device replies ``ack`` (optionally followed by ``+`` and an answer
  such as ``!7SET0011230``) or ``nack``.
- The interval between commands must be at least 30 ms.
- The device pushes status notifications on state changes. The spec asks the
  controller to acknowledge them, but the player does not accept an ``ack`` from
  the controller: it sends every notification once more regardless (spec 4.4.3),
  and the stray reply can make it refuse the next request. Notifications are
  therefore not acknowledged; the repeat is harmless, as unchanged values are
  ignored.
- Device messages have no end character, so a message counts as complete once the
  line has been quiet for a moment.
- A message is at most 600 bytes, start and end character included.
- A device without room for another command replies ``@0BDERBUSY``.

The player has no authentication, so this client only ever sends the fixed
commands from ``const.py`` and treats everything the device sends as untrusted:
messages are length-limited and unknown input is ignored.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import logging
import re
import time

_LOGGER = logging.getLogger(__name__)

START = "!7"
CR = "\r"
ACK = "ack"
NACK = "nack"
BUSY = "@0BDERBUSY"

COMMAND_INTERVAL = 0.03  # 30 ms minimum between commands (spec 4.3.6)
RESPONSE_TIMEOUT = 1.0
CONNECT_TIMEOUT = 5.0
# A device message is complete after this much silence (device messages have no end
# character).
FLUSH_TIMEOUT = 0.05
RETRY_DELAY = 0.5  # pause before retrying a failed command
RETRY_ATTEMPTS = 2  # initial attempt plus one retry
BUSY_DELAY = 0.1  # pause before resending a command the player was too busy for
MAX_MESSAGE_LENGTH = 600  # spec 2: start character to end character included

# A device message is "!7", a three character code and parameters made of upper case
# letters, digits, "+" and "-" (spec 5.3). Replies are the lower case "ack" or "nack",
# so a message running straight into a reply still splits correctly.
_MESSAGE_RE = re.compile(r"!7[A-Z0-9]{3}[A-Z0-9+\-]*|@0BDERBUSY|nack|ack")

# What may be sent: "!7", an optional "?" for a status request, and upper case letters,
# digits, "+" and "-". No CR, LF or other characters can ever reach the device.
_COMMAND_RE = re.compile(r"!7\??[A-Z0-9][A-Z0-9+\-]{2,}")

# Longest unparsed remainder worth keeping between reads: enough for a partial "!7XY",
# "nac", "ack+" or "@0BDER" to complete with the next read.
_MAX_REMAINDER = 16


class TascamError(Exception):
    """Base error for Tascam protocol failures."""


class TascamConnectionError(TascamError):
    """Raised when the device cannot be reached."""


class TascamNackError(TascamError):
    """Raised when the device replies with NACK."""


class TascamBusyError(TascamNackError):
    """Raised when the device had no room for the command and did not execute it."""


def validate_command(command: str) -> None:
    """Refuse anything that is not a well-formed BD-MP4K command.

    Every command comes from ``const.py``; this guard keeps it that way, so no
    value from Home Assistant or a user can be smuggled into the protocol.
    """
    if len(command) + len(CR) > MAX_MESSAGE_LENGTH or not _COMMAND_RE.fullmatch(command):
        raise ValueError(f"Refusing to send malformed command {command!r}")


class _Pending:
    """An in-flight command awaiting its reply."""

    def __init__(self, is_request: bool) -> None:
        """Initialize the pending command."""
        self.is_request = is_request
        self.acked = False
        loop = asyncio.get_running_loop()
        self.future: asyncio.Future[str | None] = loop.create_future()


class TascamClient:
    """Maintain a single persistent, push-capable connection."""

    def __init__(self, host: str, port: int) -> None:
        """Initialize the client."""
        self._host = host
        self._port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._listen_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._last_command = 0.0
        self._pending: _Pending | None = None
        self._notification_callback: Callable[[str], None] | None = None

    @property
    def connected(self) -> bool:
        """Return True if the connection is open."""
        return self._writer is not None and not self._writer.is_closing()

    def set_notification_callback(
        self,
        callback: Callable[[str], None] | None,
    ) -> None:
        """Register a callback for unsolicited status notifications."""
        self._notification_callback = callback

    async def async_connect(self) -> None:
        """Open the TCP connection and start the listener task."""
        if self.connected:
            return
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=CONNECT_TIMEOUT,
            )
        except (OSError, TimeoutError) as err:
            self._reader = None
            self._writer = None
            raise TascamConnectionError(
                f"Cannot connect to {self._host}:{self._port}: {err}",
            ) from err
        loop = asyncio.get_running_loop()
        self._listen_task = loop.create_task(self._listen())
        _LOGGER.debug("Connected to %s:%s", self._host, self._port)

    async def async_disconnect(self) -> None:
        """Close the TCP connection and stop the listener task."""
        task = self._listen_task
        self._listen_task = None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            # Wait for the cancellation to finish, so no reader task outlives
            # the connection it was reading from.
            await asyncio.wait({task})
        writer = self._writer
        self._reader = None
        self._writer = None
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError as err:
                # The socket was already gone; nothing left to close.
                _LOGGER.debug("Error while closing connection: %s", err)
        self._fail_pending(TascamConnectionError("Disconnected"))

    async def async_send(self, command: str, *, retry: bool = True) -> str | None:
        """Send a command and return the answer message, if any.

        Returns the ``!7XXX...`` answer for status requests, or None for
        plain control commands that are only acknowledged. With ``retry``, a
        connection failure is retried once after a short delay, since the player
        briefly refuses connections around power state changes, and a busy reply
        is retried once without reconnecting. Without ``retry`` there is a single
        attempt, which keeps polling quiet while the player is switched off.
        """
        validate_command(command)
        attempts = RETRY_ATTEMPTS if retry else 1
        attempt = 1
        while True:
            try:
                return await self._async_send_once(command)
            except TascamBusyError:
                if attempt >= attempts:
                    raise
                _LOGGER.debug("Player busy, resending %s", command)
                await asyncio.sleep(BUSY_DELAY)
            except TascamConnectionError as err:
                if attempt >= attempts:
                    raise
                _LOGGER.debug("Retrying %s after failure: %s", command, err)
                await self.async_disconnect()
                await asyncio.sleep(RETRY_DELAY)
            attempt += 1

    async def _async_send_once(self, command: str) -> str | None:
        """Send a command once over the shared connection."""
        async with self._lock:
            await self.async_connect()
            await self._respect_interval()
            writer = self._writer
            if writer is None:
                raise TascamConnectionError("Connection lost before sending")
            pending = _Pending(is_request=command.startswith(f"{START}?"))
            self._pending = pending
            try:
                writer.write(f"{command}{CR}".encode("ascii"))
                await writer.drain()
                self._last_command = time.monotonic()
                return await asyncio.wait_for(
                    pending.future,
                    RESPONSE_TIMEOUT,
                )
            except (OSError, TimeoutError) as err:
                await self.async_disconnect()
                raise TascamConnectionError(
                    f"No reply to {command}: {err}",
                ) from err
            finally:
                self._pending = None

    async def _respect_interval(self) -> None:
        """Enforce the 30 ms minimum interval between commands."""
        elapsed = time.monotonic() - self._last_command
        if elapsed < COMMAND_INTERVAL:
            await asyncio.sleep(COMMAND_INTERVAL - elapsed)

    async def _listen(self) -> None:
        """Continuously read the socket and dispatch incoming tokens."""
        reader = self._reader
        if reader is None:
            return
        buffer = ""
        try:
            while True:
                try:
                    if buffer:
                        chunk = await asyncio.wait_for(
                            reader.read(256),
                            timeout=FLUSH_TIMEOUT,
                        )
                    else:
                        chunk = await reader.read(256)
                except TimeoutError:
                    # No more data: the partial tail is a complete token.
                    self._dispatch_buffer(buffer, final=True)
                    buffer = ""
                    continue
                if not chunk:
                    raise TascamConnectionError("Connection closed by device")
                buffer += chunk.decode("ascii", errors="replace")
                buffer = self._dispatch_buffer(buffer, final=False)
        except asyncio.CancelledError:
            raise
        except (TascamError, OSError) as err:
            _LOGGER.debug("Listener stopped: %s", err)
            self._fail_pending(TascamConnectionError(str(err)))
            self._listen_task = None
            writer = self._writer
            self._reader = None
            self._writer = None
            if writer is not None:
                writer.close()

    def _dispatch_buffer(self, buffer: str, final: bool) -> str:
        """Dispatch the complete messages in the buffer and return what is left over.

        A message at the very end of the buffer may still be growing, so it is held
        back until more data arrives or the line stays quiet (``final``). Text after
        the last message is kept too, as it may be the start of the next one.
        """
        matches = list(_MESSAGE_RE.finditer(buffer))
        remainder = buffer[matches[-1].end() :] if matches else buffer
        held = ""
        if not final and matches and not remainder and matches[-1].group().startswith(START):
            held = matches.pop().group()
        for match in matches:
            # A trailing "+" belongs to an "ack+answer" separator, not to the message.
            self._dispatch(match.group().rstrip("+"))
        if final:
            return ""
        if held:
            if len(held) > MAX_MESSAGE_LENGTH:
                # Longer than the protocol allows: not a real message, so drop it
                # instead of letting the buffer grow.
                _LOGGER.debug("Dropping a message longer than %s bytes", MAX_MESSAGE_LENGTH)
                return ""
            return held
        return remainder[-_MAX_REMAINDER:]

    def _dispatch(self, token: str) -> None:
        """Route one token to the pending command or the callback."""
        if not token:
            return
        if len(token) > MAX_MESSAGE_LENGTH:
            _LOGGER.debug("Ignoring a message longer than %s bytes", MAX_MESSAGE_LENGTH)
            return
        pending = self._pending
        if token in (NACK, BUSY):
            if pending is not None and not pending.future.done():
                error = TascamBusyError if token == BUSY else TascamNackError
                pending.future.set_exception(error(f"Device replied {token}"))
            return
        if token == ACK:
            if pending is None or pending.future.done():
                return
            if pending.is_request:
                pending.acked = True
            else:
                pending.future.set_result(None)
            return
        if token.startswith(START):
            if (
                pending is not None
                and pending.is_request
                and pending.acked
                and not pending.future.done()
            ):
                pending.future.set_result(token)
                return
            # Unsolicited status notification. Deliberately not acknowledged; see the
            # protocol notes at the top of this module.
            _LOGGER.debug("Notification: %s", token)
            if self._notification_callback is not None:
                self._notification_callback(token)

    def _fail_pending(self, err: TascamError) -> None:
        """Fail the in-flight command, if there is one."""
        if self._pending is not None and not self._pending.future.done():
            self._pending.future.set_exception(err)
