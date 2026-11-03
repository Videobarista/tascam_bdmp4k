"""Sensor entities for the Tascam BD-MP4K."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DISC_STATUS_MAP, PLAYBACK_STATUS_MAP
from .coordinator import TascamConfigEntry, TascamCoordinator, TascamState
from .entity import TascamEntity


@dataclass(frozen=True, kw_only=True)
class TascamSensorDescription(SensorEntityDescription):
    """Describes a Tascam sensor."""

    value_fn: Callable[[TascamState], str | int | None]


SENSORS: tuple[TascamSensorDescription, ...] = (
    TascamSensorDescription(
        key="disc_status",
        translation_key="disc_status",
        device_class=SensorDeviceClass.ENUM,
        options=list(DISC_STATUS_MAP.values()),
        value_fn=lambda data: data.disc_status,
    ),
    TascamSensorDescription(
        key="playback_status",
        translation_key="playback_status",
        device_class=SensorDeviceClass.ENUM,
        options=list(PLAYBACK_STATUS_MAP.values()),
        value_fn=lambda data: data.playback_status,
    ),
    TascamSensorDescription(
        key="elapsed_time",
        translation_key="elapsed_time",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        value_fn=lambda data: data.elapsed,
    ),
    TascamSensorDescription(
        key="remaining_time",
        translation_key="remaining_time",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        value_fn=lambda data: data.remaining,
    ),
    TascamSensorDescription(
        key="current_chapter",
        translation_key="current_chapter",
        value_fn=lambda data: data.current_chapter,
    ),
    TascamSensorDescription(
        key="current_title",
        translation_key="current_title",
        value_fn=lambda data: data.current_title,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TascamConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors from a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(TascamSensor(coordinator, description) for description in SENSORS)


class TascamSensor(TascamEntity, SensorEntity):
    """A read-only status value from the BD-MP4K."""

    entity_description: TascamSensorDescription

    def __init__(
        self,
        coordinator: TascamCoordinator,
        description: TascamSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> str | int | None:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)
