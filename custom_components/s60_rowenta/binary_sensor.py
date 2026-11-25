"""Binary sensors for Rowenta Series 60."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import S60ConfigEntry
from .coordinator import VacuumCoordinator
from .entity import S60Entity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: S60ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        S60CloudUp(c) for c in entry.runtime_data.coordinators.values()
    )


class S60CloudUp(S60Entity, BinarySensorEntity):
    _attr_translation_key = "cloud_up"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: VacuumCoordinator) -> None:
        super().__init__(coordinator, "cloud_up")

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self.coordinator.data.mqtt_ok

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.online