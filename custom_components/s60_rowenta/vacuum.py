"""Vacuum entity for Rowenta Series 60."""

from __future__ import annotations

from typing import Any

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.core import HomeAssistant, ServiceResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import S60ConfigEntry
from .const import CLEAN_MODES, DOMAIN, SUCTION_POWER, CleanMode
from .coordinator import VacuumCoordinator
from .entity import S60Entity
from .schedules import apply_changes, find_idx, to_dict

PARALLEL_UPDATES = 0

RETURNING = {CleanMode.RETURN_HOME.value, CleanMode.RECHARGE_RESUME.value}


def activity(state: dict[str, Any]) -> VacuumActivity | None:
    st = state.get("status")
    method = state.get("method")
    if st is None:
        return None
    if st == "ERROR":
        return VacuumActivity.ERROR
    if st == "CLEANING":
        if method in RETURNING:
            return VacuumActivity.RETURNING
        if method == "PAUSE":
            return VacuumActivity.PAUSED
        return VacuumActivity.CLEANING
    if st == "DOCKING":
        return VacuumActivity.RETURNING
    if st == "CHARGING":
        return VacuumActivity.DOCKED
    return VacuumActivity.IDLE


async def async_setup_entry(
    hass: HomeAssistant,
    entry: S60ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(S60Vacuum(c) for c in entry.runtime_data.coordinators.values())


class S60Vacuum(S60Entity, StateVacuumEntity):
    _attr_name = None
    _attr_translation_key = "vacuum"
    _attr_fan_speed_list = [p.value.lower() for p in SUCTION_POWER]
    _attr_supported_features = (
        VacuumEntityFeature.START
        | VacuumEntityFeature.PAUSE
        | VacuumEntityFeature.STOP
        | VacuumEntityFeature.RETURN_HOME
        | VacuumEntityFeature.CLEAN_SPOT
        | VacuumEntityFeature.LOCATE
        | VacuumEntityFeature.FAN_SPEED
        | VacuumEntityFeature.SEND_COMMAND
        | VacuumEntityFeature.STATE
    )

    def __init__(self, coordinator: VacuumCoordinator) -> None:
        super().__init__(coordinator, "vacuum")

    @property
    def _st(self) -> dict[str, Any]:
        return self.coordinator.data.status

    @property
    def activity(self) -> VacuumActivity | None:
        return activity(self._st)

    @property
    def fan_speed(self) -> str | None:
        p = self._st.get("power")
        return p.lower() if isinstance(p, str) else None

    def _cur_power(self) -> str:
        return (self.fan_speed or "normal").upper()

    async def async_start(self) -> None:
        mode = self.coordinator.start_mode.upper()
        self.coordinator.send_cmd({"method": mode, "power": self._cur_power()})

    async def async_pause(self) -> None:
        self.coordinator.send_cmd({"method": "PAUSE"})

    async def async_stop(self, **kwargs: Any) -> None:
        self.coordinator.send_cmd({"method": "PAUSE"})

    async def async_return_to_base(self, **kwargs: Any) -> None:
        self.coordinator.send_cmd({"method": CleanMode.RETURN_HOME.value})

    async def async_clean_spot(self, **kwargs: Any) -> None:
        self.coordinator.send_cmd({"method": CleanMode.SPOT.value, "power": self._cur_power()})

    async def async_locate(self, **kwargs: Any) -> None:
        self.coordinator.send_cmd({"beep": "ON"})

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        if fan_speed.upper() not in [p.value for p in SUCTION_POWER]:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="bad_power",
                translation_placeholders={"fan_speed": fan_speed},
            )
        self.coordinator.send_cmd({"power": fan_speed.upper()})

    async def async_get_schedules(self) -> ServiceResponse:
        return {"schedules": [to_dict(s) for s in self.coordinator.data.schedules]}

    async def async_set_schedule(self, schedule: str | None = None, **changes: Any) -> ServiceResponse:
        scheds = list(self.coordinator.data.schedules)
        if schedule is None or not schedule.strip():
            raw = apply_changes(None, **changes)
            scheds.append(raw)
        else:
            idx = find_idx(scheds, schedule)
            if idx is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="sched_not_found",
                    translation_placeholders={"schedule": schedule},
                )
            raw = scheds[idx] = apply_changes(scheds[idx], **changes)
        await self.coordinator.write_schedules(scheds)
        return {"schedule": to_dict(raw)}

    async def async_delete_schedule(self, schedule: str) -> None:
        scheds = list(self.coordinator.data.schedules)
        idx = find_idx(scheds, schedule)
        if idx is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="sched_not_found",
                translation_placeholders={"schedule": schedule},
            )
        del scheds[idx]
        await self.coordinator.write_schedules(scheds)

    async def async_send_command(
        self, command: str, params: dict[str, Any] | list[Any] | None = None, **kwargs: Any
    ) -> None:
        if command == "raw":
            if not isinstance(params, dict):
                raise ServiceValidationError(
                    translation_domain=DOMAIN, translation_key="raw_dict"
                )
            self.coordinator.send_cmd(params)
            return
        if command.lower() not in [m.value.lower() for m in CLEAN_MODES]:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_cmd",
                translation_placeholders={"command": command},
            )
        payload: dict[str, Any] = {"method": command.upper()}
        if isinstance(params, dict) and "power" in params:
            payload["power"] = str(params["power"]).upper()
        self.coordinator.send_cmd(payload)