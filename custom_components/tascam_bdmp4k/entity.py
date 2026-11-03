"""Base entity for the Tascam BD-MP4K integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_NAME, DOMAIN, MANUFACTURER, MODEL
from .coordinator import TascamCoordinator


class TascamEntity(CoordinatorEntity[TascamCoordinator]):
    """Base class for all Tascam BD-MP4K entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TascamCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEFAULT_NAME,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @property
    def available(self) -> bool:
        """Return True if the device responded to the last poll."""
        return super().available and self.coordinator.data.available
