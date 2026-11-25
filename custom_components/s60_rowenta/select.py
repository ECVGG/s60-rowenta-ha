"""Select entities for Rowenta Series 60."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import S60ConfigEntry
from .const import START_MODES
from .coordinator import VacuumCoordinator
from .entity import S60Entity
from .history import job_label

PARALLEL_UPDATES = 0

LATEST = "latest"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: S60ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coords = entry.runtime_data.coordinators.values()
    async_add_entities(
        [S60StartMode(c) for c in coords] + [S60MapPick(c) for c in coords]
    )


class S60StartMode(S60Entity, SelectEntity, RestoreEntity):
    _attr_translation_key = "start_mode"
    _attr_options = [m.value.lower() for m in START_MODES]
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: VacuumCoordinator) -> None:
        super().__init__(coordinator, "start_mode")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) and last.state in self._attr_options:
            self.coordinator.start_mode = last.state

    @property
    def available(self) -> bool:
        return True

    @property
    def current_option(self) -> str:
        return self.coordinator.start_mode

    async def async_select_option(self, option: str) -> None:
        self.coordinator.start_mode = option
        self.async_write_ha_state()


class S60MapPick(S60Entity, SelectEntity):
    _attr_translation_key = "map_pick"

    def __init__(self, coordinator: VacuumCoordinator) -> None:
        super().__init__(coordinator, "map_pick")

    def _opts(self) -> dict[str, str]:
        res: dict[str, str] = {}
        for item in self.coordinator.data.cleanings:
            lbl = job_label(item)
            orig = lbl
            n = 1
            while lbl in res:
                n += 1
                lbl = f"{orig} ({n})"
            res[lbl] = str(item["mapId"])
        return res

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success

    @property
    def options(self) -> list[str]:
        return [LATEST, *self._opts()]

    @property
    def current_option(self) -> str:
        sel = self.coordinator._pinned_map
        if sel is None:
            return LATEST
        for lbl, mid in self._opts().items():
            if mid == sel:
                return lbl
        return LATEST

    async def async_select_option(self, option: str) -> None:
        if option == LATEST:
            self.coordinator.pin_map(None)
        else:
            self.coordinator.pin_map(self._opts().get(option))
        self.async_write_ha_state()