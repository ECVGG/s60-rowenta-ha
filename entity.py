"""Base entity for Rowenta Series 60."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import VacuumCoordinator


class S60Entity(CoordinatorEntity[VacuumCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: VacuumCoordinator, key: str) -> None:
        super().__init__(coordinator)
        dev = coordinator.device
        self._attr_unique_id = f"{dev.device_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, dev.device_id)},
            manufacturer="Rowenta",
            name=dev.name,
            model="X-Plorer Series 60",
            model_id=dev.thing_type,
        )

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.available