"""Switch entities for Rowenta Series 60 (schedule toggles)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import S60ConfigEntry
from .const import DOMAIN
from .coordinator import VacuumCoordinator
from .entity import S60Entity
from .schedules import apply_changes, find_idx, to_dict

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: S60ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    for coord in entry.runtime_data.coordinators.values():
        seen: set[str] = set()

        @callback
        def _sync(coord: VacuumCoordinator = coord, seen: set[str] = seen) -> None:
            ids = {s["id"] for s in coord.data.schedules if s.get("id")}
            if new := ids - seen:
                seen |= new
                async_add_entities(S60SchedSwitch(coord, sid) for sid in sorted(new))
            if gone := seen - ids:
                reg = er.async_get(hass)
                for sid in gone:
                    uid = f"{coord.device.device_id}_sched_{sid}"
                    if eid := reg.async_get_entity_id("switch", DOMAIN, uid):
                        reg.async_remove(eid)
                seen -= gone

        _sync()
        entry.async_on_unload(coord.async_add_listener(_sync))


class S60SchedSwitch(S60Entity, SwitchEntity):
    _attr_translation_key = "schedule"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: VacuumCoordinator, sched_id: str) -> None:
        super().__init__(coordinator, f"sched_{sched_id}")
        self._sid = sched_id

    @property
    def _raw(self) -> dict[str, Any] | None:
        idx = find_idx(self.coordinator.data.schedules, self._sid)
        return self.coordinator.data.schedules[idx] if idx is not None else None

    @property
    def translation_placeholders(self) -> dict[str, str]:
        r = self._raw or {}
        return {"name": str(r.get("name") or self._sid[:8]), "start": str(r.get("start") or "")}

    @property
    def available(self) -> bool:
        return super().available and self._raw is not None

    @property
    def is_on(self) -> bool | None:
        r = self._raw
        return bool(r.get("enabled")) if r else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        r = self._raw
        return to_dict(r) if r else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, on: bool) -> None:
        scheds = list(self.coordinator.data.schedules)
        idx = find_idx(scheds, self._sid)
        if idx is None:
            return
        scheds[idx] = apply_changes(scheds[idx], enabled=on)
        await self.coordinator.write_schedules(scheds)