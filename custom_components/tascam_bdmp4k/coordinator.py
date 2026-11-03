"""DataUpdateCoordinator for the Tascam BD-MP4K."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    DEFAULT_SCAN_INTERVAL,
    DISC_STATUS_MAP,
    DOMAIN,
    PLAYBACK_STATUS_MAP,
    REQ_CURRENT_CHAPTER,
    REQ_CURRENT_TITLE,
    REQ_DISC,
    REQ_ELAPSED,
    REQ_REMAIN,
    REQ_STATUS,
)
from .protocol import TascamClient, TascamConnectionError, TascamNackError

_LOGGER = logging.getLogger(__name__)

type TascamConfigEntry = ConfigEntry[TascamCoordinator]


@dataclass
class TascamState:
    """Parsed device state."""

    available: bool = False
    disc_status: str | None = None
    playback_status: str | None = None
    elapsed: int | None = None  # seconds
    position_updated_at: datetime | None = None
    remaining: int | None = None  # seconds
    current_chapter: int | None = None
    current_title: int | None = None
    raw: dict[str, str] = field(default_factory=dict)


def parse_hms(value: str) -> int | None:
    """Parse an hhhmmss time string into seconds."""
    if len(value) != 7 or not value.isdigit():
        return None
    hours = int(value[:3])
    minutes = int(value[3:5])
    seconds = int(value[5:7])
    return hours * 3600 + minutes * 60 + seconds


def parse_number(value: str) -> int | None:
    """Parse a 4-digit chapter or title number, handling UNKN."""
    if value.isdigit():
        return int(value)
    return None


# The specification gives the chapter and title as TNMxxxx and GNMxxxx, but the
# player's firmware sends TNxxxx and GNMXxxxx. Both forms are accepted; the longer
# prefix is tried first so "TNM0003" is not read as "TN" + "M0003".
CHAPTER_PREFIXES = ("TNM", "TN")
TITLE_PREFIXES = ("GNMX", "GNM")
# Total chapter and title counts (TTN/TT, TGN/TGNX) are pushed too but not shown.
TOTAL_PREFIXES = ("TT", "TGN")


def strip_prefix(body: str, prefixes: tuple[str, ...]) -> str | None:
    """Return the value after the first matching prefix, or None if none matches."""
    for prefix in prefixes:
        if body.startswith(prefix):
            return body[len(prefix) :]
    return None


class TascamCoordinator(DataUpdateCoordinator[TascamState]):
    """Poll the BD-MP4K and apply its pushed status notifications."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: TascamConfigEntry,
        client: TascamClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.client = client
        client.set_notification_callback(self._handle_notification)

    @callback
    def _handle_notification(self, message: str) -> None:
        """Apply a pushed status notification to the state immediately.

        A notification that changes nothing is ignored, so a player that repeats
        itself cannot flood Home Assistant with state writes.
        """
        body = message.removeprefix("!7")
        state = self.data
        if state is None:
            return
        if body.startswith("SST"):
            code = body.removeprefix("SST")
            status = PLAYBACK_STATUS_MAP.get(code)
            if status is None:
                _LOGGER.debug("Unknown playback status code: %s", code)
            if state.available and status == state.playback_status:
                return
            state.raw["status"] = code
            state.playback_status = status
            state.available = True
            self.async_set_updated_data(state)
            # Fetch times and chapter numbers for the new transport state.
            self.hass.async_create_task(self.async_request_refresh())
        elif body.startswith("MST"):
            code = body.removeprefix("MST")
            disc = DISC_STATUS_MAP.get(code)
            if disc is None:
                _LOGGER.debug("Unknown disc status code: %s", code)
            if state.available and disc == state.disc_status:
                return
            state.raw["disc"] = code
            state.disc_status = disc
            state.available = True
            self.async_set_updated_data(state)
        elif (value := strip_prefix(body, CHAPTER_PREFIXES)) is not None:
            chapter = parse_number(value)
            if state.available and chapter == state.current_chapter:
                return
            state.current_chapter = chapter
            state.available = True
            self.async_set_updated_data(state)
        elif (value := strip_prefix(body, TITLE_PREFIXES)) is not None:
            title = parse_number(value)
            if state.available and title == state.current_title:
                return
            state.current_title = title
            state.available = True
            self.async_set_updated_data(state)
        elif strip_prefix(body, TOTAL_PREFIXES) is not None:
            return
        else:
            # Refresh requests are debounced, so repeated notifications are cheap.
            self.hass.async_create_task(self.async_request_refresh())

    async def _query(self, command: str, *, retry: bool = True) -> str | None:
        """Send a status request, tolerating NACK (feature unavailable)."""
        try:
            answer = await self.client.async_send(command, retry=retry)
        except TascamNackError:
            # The device NACKs requests that do not apply to the current
            # mode (e.g. remaining time while stopped), and answers busy when
            # it has no room for the request. Treat both as unknown.
            _LOGGER.debug("Request %s not answered right now", command)
            return None
        if answer is None:
            return None
        return answer.removeprefix("!7")

    async def _async_update_data(self) -> TascamState:
        """Fetch the current state from the device."""
        state = TascamState()
        # What the last poll or notification showed, while the player was reachable.
        previous = self.data if self.data is not None and self.data.available else None
        # A player that was already unreachable is most likely in standby. Try it
        # once per poll instead of retrying, so Home Assistant does not keep
        # knocking on its door; it is still picked up at the next poll once it is on.
        offline = self.data is not None and not self.data.available
        try:
            status = await self._query(REQ_STATUS, retry=not offline)
        except TascamConnectionError as err:
            if offline:
                _LOGGER.debug("Device still unreachable: %s", err)
                state.available = False
                return state
            # The player occasionally drops the connection; reconnect and
            # retry once before declaring the device unavailable.
            await self.client.async_disconnect()
            try:
                status = await self._query(REQ_STATUS)
            except TascamConnectionError as err:
                _LOGGER.debug("Device unreachable: %s", err)
                state.available = False
                return state

        state.available = True
        if status is not None and status.startswith("SST"):
            code = status.removeprefix("SST")
            state.raw["status"] = code
            state.playback_status = PLAYBACK_STATUS_MAP.get(code)
            if state.playback_status is None:
                _LOGGER.debug("Unknown playback status code: %s", code)
        elif previous is not None:
            # Not answered, for example while the player is busy right after a
            # notification: keep the last known status instead of showing unknown.
            state.raw["status"] = previous.raw.get("status", "")
            state.playback_status = previous.playback_status

        try:
            disc = await self._query(REQ_DISC)
            if disc is not None and disc.startswith("MST"):
                code = disc.removeprefix("MST")
                state.raw["disc"] = code
                state.disc_status = DISC_STATUS_MAP.get(code)
                if state.disc_status is None:
                    _LOGGER.debug("Unknown disc status code: %s", code)
            elif previous is not None:
                state.raw["disc"] = previous.raw.get("disc", "")
                state.disc_status = previous.disc_status

            if state.playback_status in ("playing", "paused"):
                elapsed = await self._query(REQ_ELAPSED)
                if elapsed is not None and elapsed.startswith("SET"):
                    state.elapsed = parse_hms(elapsed.removeprefix("SET"))
                    state.position_updated_at = dt_util.utcnow()

                remaining = await self._query(REQ_REMAIN)
                if remaining is not None and remaining.startswith("SRT"):
                    value = remaining.removeprefix("SRT")
                    state.remaining = parse_hms(value)

                chapter = await self._query(REQ_CURRENT_CHAPTER)
                if chapter is not None:
                    value = strip_prefix(chapter, CHAPTER_PREFIXES)
                    if value is not None:
                        state.current_chapter = parse_number(value)

                title = await self._query(REQ_CURRENT_TITLE)
                if title is not None:
                    value = strip_prefix(title, TITLE_PREFIXES)
                    if value is not None:
                        state.current_title = parse_number(value)
        except TascamConnectionError as err:
            _LOGGER.debug("Lost connection during poll: %s", err)

        return state
