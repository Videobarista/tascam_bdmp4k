"""The Tascam BD-MP4K integration."""

from __future__ import annotations

from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant

from .coordinator import TascamConfigEntry, TascamCoordinator
from .protocol import TascamClient

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: TascamConfigEntry) -> bool:
    """Set up Tascam BD-MP4K from a config entry.

    The player drops off the network in standby, so setup does not require a
    connection: an unreachable player loads as "off" and can be woken with
    Wake-on-LAN, instead of failing setup and retrying.
    """
    client = TascamClient(entry.data[CONF_HOST], entry.data[CONF_PORT])
    coordinator = TascamCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TascamConfigEntry) -> bool:
    """Unload a config entry and close the connection to the player."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.client.async_disconnect()
    return unload_ok
