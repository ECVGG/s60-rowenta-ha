"""Map image entity for Rowenta Series 60."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.image import ImageEntity
from homeassistant.components.vacuum import VacuumActivity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import S60ConfigEntry
from .activity import activity
from .const import MAP_ORIGIN
from .coordinator import VacuumCoordinator
from .entity import S60Entity
from .map_renderer import render_map

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: S60ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(S60Map(c) for c in entry.runtime_data.coordinators.values())


class S60Map(S60Entity, ImageEntity):
    _attr_translation_key = "map"
    _attr_content_type = "image/png"

    def __init__(self, coordinator: VacuumCoordinator) -> None:
        S60Entity.__init__(self, coordinator, "map")
        ImageEntity.__init__(self, coordinator.hass)
        self._cache_ts: datetime | None = None
        self._cache_img: bytes | None = None
        self._docked = self._is_docked()
        self._dock_changed: datetime | None = None

    def _is_docked(self) -> bool:
        return activity(self.coordinator.data.status) == VacuumActivity.DOCKED

    @callback
    def _handle_coordinator_update(self) -> None:
        # Docking moves the robot without new map data: the image must refresh
        if (docked := self._is_docked()) != self._docked:
            self._docked = docked
            self._dock_changed = dt_util.utcnow()
            self._cache_img = None
        super()._handle_coordinator_update()

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self.coordinator.data.map_updated is not None

    @property
    def image_last_updated(self) -> datetime | None:
        updated = self.coordinator.data.map_updated
        if updated and self._dock_changed:
            return max(updated, self._dock_changed)
        return updated

    @property
    def extra_state_attributes(self) -> dict[str, int]:
        return {"points": len(self.coordinator.data.map_points)}

    async def async_image(self) -> bytes | None:
        data = self.coordinator.data
        if data.map_updated is None:
            return None

        if data.map_updated == self._cache_ts and self._cache_img:
            return self._cache_img

        # The trip back is not recorded, so a docked robot is drawn on the dock
        robot_pos = (MAP_ORIGIN, MAP_ORIGIN) if self._docked else None
        if robot_pos is None:
            for p in reversed(data.map_points):
                if p.get("type") in {3, 8, 12}:
                    robot_pos = (p["x"], p["y"])
                    break

        self._cache_img = await self.hass.async_add_executor_job(
            render_map, list(data.map_points), robot_pos
        )
        self._cache_ts = data.map_updated
        return self._cache_img