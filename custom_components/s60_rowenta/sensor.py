"""Sensors for Rowenta Series 60."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfArea, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import S60ConfigEntry
from .const import ACCESSORY_MAP, CLEAN_MODES, RobotError, RobotState
from .coordinator import VacuumCoordinator
from .entity import S60Entity
from .history import lower, ms_to_dt
from .schedules import to_dict

PARALLEL_UPDATES = 0


def _acc(data: VacuumCoordinator, name: str) -> dict[str, Any] | None:
    items = data.data.status.get("accessories") or data.data.reported.get("accessories") or []
    return next((a for a in items if a.get("name") == name), None)


def _acc_wear(name: str) -> Callable[[VacuumCoordinator], Any]:
    def _get(coord: VacuumCoordinator) -> Any:
        acc = _acc(coord, name)
        if not acc or not acc.get("limit"):
            return None
        return round(100 * acc.get("current", 0) / acc["limit"])
    return _get


@dataclass(frozen=True, kw_only=True)
class S60SensorDesc(SensorEntityDescription):
    value_fn: Callable[[VacuumCoordinator], Any]
    attrs_fn: Callable[[VacuumCoordinator], dict[str, Any] | None] | None = None


SENSORS: tuple[S60SensorDesc, ...] = (
    S60SensorDesc(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.data.status.get("battery"),
    ),
    S60SensorDesc(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=[s.value.lower() for s in RobotState],
        value_fn=lambda c: lower(c.data.status.get("status")),
    ),
    S60SensorDesc(
        key="error",
        translation_key="error",
        device_class=SensorDeviceClass.ENUM,
        options=[e.value.lower() for e in RobotError],
        value_fn=lambda c: lower(c.data.status.get("errorCode")),
    ),
    S60SensorDesc(
        key="mode",
        translation_key="mode",
        device_class=SensorDeviceClass.ENUM,
        options=[m.value.lower() for m in CLEAN_MODES],
        value_fn=lambda c: lower(c.data.status.get("method")),
    ),
    S60SensorDesc(
        key="area",
        translation_key="area",
        device_class=SensorDeviceClass.AREA,
        native_unit_of_measurement=UnitOfArea.SQUARE_METERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.data.status.get("cleaningArea"),
    ),
    S60SensorDesc(
        key="duration",
        translation_key="duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.data.status.get("cleaningTime"),
    ),
    S60SensorDesc(
        key="started",
        translation_key="started",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c: ms_to_dt(c.data.status.get("startTimestamp")),
    ),
    *(
        S60SensorDesc(
            key=f"{k}_wear",
            translation_key=f"{k}_wear",
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=_acc_wear(n),
            attrs_fn=lambda c, n=n: _acc(c, n),
        )
        for n, k in ACCESSORY_MAP.items()
    ),
    S60SensorDesc(
        key="total_area",
        translation_key="total_area",
        device_class=SensorDeviceClass.AREA,
        native_unit_of_measurement=UnitOfArea.SQUARE_METERS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.data.history.get("totalCleaningArea"),
    ),
    S60SensorDesc(
        key="total_time",
        translation_key="total_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.data.history.get("totalCleaningDuration"),
    ),
    S60SensorDesc(
        key="total_jobs",
        translation_key="total_jobs",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.data.history.get("totalNumberOfClean"),
    ),
    S60SensorDesc(
        key="last_job",
        translation_key="last_job",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c: (
            dt_util.parse_datetime(c.data.cleanings[0]["end"])
            if c.data.cleanings and c.data.cleanings[0]["end"]
            else None
        ),
        attrs_fn=lambda c: _last_attrs(c),
    ),
    S60SensorDesc(
        key="sched_count",
        translation_key="sched_count",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: sum(1 for s in c.data.schedules if s.get("enabled")),
        attrs_fn=lambda c: {"schedules": [to_dict(s) for s in c.data.schedules]},
    ),
    S60SensorDesc(
        key="mqtt",
        translation_key="mqtt",
        device_class=SensorDeviceClass.ENUM,
        options=["up", "down"],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: "up" if c.data.mqtt_ok else "down",
    ),
)


def _last_attrs(coord: VacuumCoordinator) -> dict[str, Any] | None:
    items = coord.data.cleanings
    if not items:
        return None
    last = items[0]
    return {"start": last["start"], "area": last["area"], "duration": last["duration"],
            "mode": last["mode"], "error": last["error"], "history": items}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: S60ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(
        S60Sensor(c, d) for c in entry.runtime_data.coordinators.values() for d in SENSORS
    )


class S60Sensor(S60Entity, SensorEntity):
    entity_description: S60SensorDesc
    _unrecorded_attributes = frozenset({"history", "schedules"})

    def __init__(self, coordinator: VacuumCoordinator, desc: S60SensorDesc) -> None:
        super().__init__(coordinator, desc.key)
        self.entity_description = desc

    @property
    def native_value(self) -> Any:
        val = self.entity_description.value_fn(self.coordinator)
        if self.entity_description.device_class == SensorDeviceClass.ENUM:
            opts = self.entity_description.options or []
            if val not in opts:
                return None
        return val

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator)