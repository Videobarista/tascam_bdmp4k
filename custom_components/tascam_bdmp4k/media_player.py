"""Media player entity for the Tascam BD-MP4K."""

from __future__ import annotations

from datetime import datetime
import logging

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CMD_PAUSE,
    CMD_PLAY,
    CMD_POWER_OFF,
    CMD_SKIP_NEXT,
    CMD_SKIP_PREV,
    CMD_STOP,
)
from .coordinator import TascamConfigEntry, TascamCoordinator
from .entity import TascamEntity
from .protocol import TascamError
from .wol import async_send_magic_packet

_LOGGER = logging.getLogger(__name__)

STATE_MAP = {
    "playing": MediaPlayerState.PLAYING,
    "paused": MediaPlayerState.PAUSED,
    "stopped": MediaPlayerState.IDLE,
    "slow_forward": MediaPlayerState.PLAYING,
    "slow_reverse": MediaPlayerState.PLAYING,
    "search_forward": MediaPlayerState.PLAYING,
    "search_reverse": MediaPlayerState.PLAYING,
    "setup": MediaPlayerState.IDLE,
    "media_center": MediaPlayerState.IDLE,
    "track_menu": MediaPlayerState.IDLE,
    "home_menu": MediaPlayerState.IDLE,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TascamConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the media player from a config entry."""
    async_add_entities([TascamMediaPlayer(entry.runtime_data)])


class TascamMediaPlayer(TascamEntity, MediaPlayerEntity):
    """Representation of the BD-MP4K as a media player."""

    _attr_name = None
    _attr_media_content_type = MediaType.VIDEO
    _attr_supported_features = (
        MediaPlayerEntityFeature.PLAY
        | MediaPlayerEntityFeature.PAUSE
        | MediaPlayerEntityFeature.STOP
        | MediaPlayerEntityFeature.NEXT_TRACK
        | MediaPlayerEntityFeature.PREVIOUS_TRACK
        | MediaPlayerEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator: TascamCoordinator) -> None:
        """Initialize the media player."""
        super().__init__(coordinator, "media_player")
        self._mac: str | None = coordinator.config_entry.data.get(CONF_MAC)
        if self._mac:
            self._attr_supported_features |= MediaPlayerEntityFeature.TURN_ON

    @property
    def available(self) -> bool:
        """Keep the player available so it can report the off state."""
        return self.coordinator.last_update_success

    @property
    def state(self) -> MediaPlayerState:
        """Return the state of the player."""
        data = self.coordinator.data
        if not data.available:
            return MediaPlayerState.OFF
        status = data.playback_status or ""
        return STATE_MAP.get(status, MediaPlayerState.IDLE)

    @property
    def media_position(self) -> int | None:
        """Return the elapsed time in seconds."""
        return self.coordinator.data.elapsed

    @property
    def media_position_updated_at(self) -> datetime | None:
        """Return when the media position was read from the player."""
        return self.coordinator.data.position_updated_at

    @property
    def media_duration(self) -> int | None:
        """Return the duration, derived from elapsed plus remaining time."""
        data = self.coordinator.data
        if data.elapsed is None or data.remaining is None:
            return None
        return data.elapsed + data.remaining

    async def _async_send(self, command: str) -> None:
        """Send a command and refresh the state."""
        try:
            await self.coordinator.client.async_send(command)
        except TascamError as err:
            if not self.coordinator.data.available:
                # The player is powered off; a failed command is expected.
                _LOGGER.debug("Command %s skipped, off: %s", command, err)
            else:
                _LOGGER.warning("Command %s failed: %s", command, err)
        await self.coordinator.async_request_refresh()

    async def async_media_play(self) -> None:
        """Send the play command."""
        await self._async_send(CMD_PLAY)

    async def async_media_pause(self) -> None:
        """Send the pause command."""
        await self._async_send(CMD_PAUSE)

    async def async_media_stop(self) -> None:
        """Send the stop command."""
        await self._async_send(CMD_STOP)

    async def async_media_next_track(self) -> None:
        """Skip to the next chapter or file."""
        await self._async_send(CMD_SKIP_NEXT)

    async def async_media_previous_track(self) -> None:
        """Skip to the previous chapter or file."""
        await self._async_send(CMD_SKIP_PREV)

    async def async_turn_off(self) -> None:
        """Put the device in standby."""
        await self._async_send(CMD_POWER_OFF)

    async def async_turn_on(self) -> None:
        """Wake the device using Wake-on-LAN."""
        if self._mac is None:
            return
        await async_send_magic_packet(self.hass, self._mac)
        await self.coordinator.async_request_refresh()
