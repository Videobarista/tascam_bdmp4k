"""Button entities for the Tascam BD-MP4K."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.components.button import (
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CMD_DISPLAY,
    CMD_ENTER,
    CMD_HOME,
    CMD_MUTE_OFF,
    CMD_MUTE_ON,
    CMD_POPUP_MENU,
    CMD_POWER_OFF,
    CMD_RETURN,
    CMD_SETUP_MENU,
    CMD_SUBTITLE,
    CMD_TOP_MENU,
    CMD_TRAY_CLOSE,
    CMD_TRAY_OPEN,
)
from .coordinator import TascamConfigEntry, TascamCoordinator
from .entity import TascamEntity
from .protocol import TascamError

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class TascamButtonDescription(ButtonEntityDescription):
    """Describes a Tascam button."""

    command: str


BUTTONS: tuple[TascamButtonDescription, ...] = (
    TascamButtonDescription(
        key="tray_open",
        translation_key="tray_open",
        command=CMD_TRAY_OPEN,
    ),
    TascamButtonDescription(
        key="tray_close",
        translation_key="tray_close",
        command=CMD_TRAY_CLOSE,
    ),
    TascamButtonDescription(
        key="home",
        translation_key="home",
        command=CMD_HOME,
    ),
    TascamButtonDescription(
        key="enter",
        translation_key="enter",
        command=CMD_ENTER,
    ),
    TascamButtonDescription(
        key="return",
        translation_key="return",
        command=CMD_RETURN,
    ),
    TascamButtonDescription(
        key="top_menu",
        translation_key="top_menu",
        command=CMD_TOP_MENU,
    ),
    TascamButtonDescription(
        key="popup_menu",
        translation_key="popup_menu",
        command=CMD_POPUP_MENU,
    ),
    TascamButtonDescription(
        key="setup_menu",
        translation_key="setup_menu",
        command=CMD_SETUP_MENU,
    ),
    TascamButtonDescription(
        key="display_info",
        translation_key="display_info",
        command=CMD_DISPLAY,
    ),
    TascamButtonDescription(
        key="subtitle_next",
        translation_key="subtitle_next",
        command=CMD_SUBTITLE,
    ),
    TascamButtonDescription(
        key="mute_on",
        translation_key="mute_on",
        command=CMD_MUTE_ON,
    ),
    TascamButtonDescription(
        key="mute_off",
        translation_key="mute_off",
        command=CMD_MUTE_OFF,
    ),
    TascamButtonDescription(
        key="power_off",
        translation_key="power_off",
        command=CMD_POWER_OFF,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TascamConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the buttons from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(TascamButton(coordinator, description) for description in BUTTONS)


class TascamButton(TascamEntity, ButtonEntity):
    """A button that sends a single command to the BD-MP4K."""

    entity_description: TascamButtonDescription

    def __init__(
        self,
        coordinator: TascamCoordinator,
        description: TascamButtonDescription,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        """Send the command to the device."""
        command = self.entity_description.command
        try:
            await self.coordinator.client.async_send(command)
        except TascamError as err:
            if not self.coordinator.data.available:
                _LOGGER.debug("Command %s skipped, off: %s", command, err)
            else:
                _LOGGER.warning("Command %s failed: %s", command, err)
        await self.coordinator.async_request_refresh()
