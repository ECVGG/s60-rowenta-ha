"""Vacuum state coordinator (MQTT-driven)."""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .auth import SebCloud
from .const import DEFAULT_START_METHOD, DOMAIN, MAP_REFRESH_INTERVAL
from .exceptions import NotConnected, SchedulesUnavailable
from .history import parse_history, job_to_dict
from .map_renderer import MapStore
from .mqtt import MqttBroker
from .models import DeviceInfo, VacuumState
from .schedules import to_dict

if TYPE_CHECKING:
    from . import S60ConfigEntry

_LOGGER = logging.getLogger(__name__)

ACTIVE_STATES = {"CLEANING", "DOCKING"}


class VacuumCoordinator(DataUpdateCoordinator[VacuumState]):
    """Holds state for one vacuum; data pushed via MQTT."""

    config_entry: S60ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: S60ConfigEntry,
        device: DeviceInfo,
        cache_dir: Path,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {device.name}",
            update_interval=None,
        )
        self.device = device
        self.mqtt: MqttBroker | None = None
        self.cloud: SebCloud | None = None
        self.start_mode = DEFAULT_START_METHOD
        self.data = VacuumState()
        self._map_store = MapStore(cache_dir)
        self._map_fetching = False
        self._map_force = False
        self._map_fetched = 0.0
        self._pinned_map: str | None = None
        self._fw_ver: str | None = None

    async def _async_update_data(self) -> VacuumState:
        if self.mqtt and self.mqtt.can_pub:
            try:
                await self.mqtt._get_status(self.device)
            except Exception:
                pass
        return self.data

    @callback
    def handle_mqtt(self, kind: str, payload: dict[str, Any]) -> None:
        if not isinstance(payload, dict):
            return

        data = self.data

        if kind == "status":
            data = replace(data, status=payload)

        elif kind == "history":
            cleanings = [job_to_dict(c) for c in parse_history(payload)]
            data = replace(data, history=payload, cleanings=cleanings)

        elif kind in ("shadow/get/accepted", "shadow/update/documents"):
            state = payload.get("state") or {}
            if kind == "shadow/update/documents":
                current = payload.get("current", {}).get("state", {})
                if current:
                    state = current

            reported = state.get("reported") or {}
            desired = state.get("desired") or {}
            if kind == "shadow/update/documents" and "desired" not in state:
                desired = {}

            data = replace(data, shadow_ready=True, reported=reported, desired=desired)

        else:
            return

        old = self.data
        self._update_fw(data.reported)

        if kind == "history" and self._pinned_map and not any(
            str(c.get("map_id")) == self._pinned_map for c in data.cleanings
        ):
            self._pinned_map = None

        self.async_set_updated_data(data)

        if kind == "history":
            self._request_map()
        if kind == "status":
            if old.active and not data.active and self.mqtt and self.mqtt.can_pub:
                self.hass.async_create_background_task(
                    self.hass, self.mqtt._get_history(self.device), f"{DOMAIN}_hist_{self.device.device_id}"
                )
            self._maybe_refresh_map(old, data)

    @property
    def current_map_id(self) -> str | None:
        mid = self.data.status.get("mapId")
        return str(mid) if mid else None

    @property
    def display_map_id(self) -> str | None:
        return self._pinned_map or self.current_map_id

    @callback
    def pin_map(self, map_id: str | None) -> None:
        self._pinned_map = map_id
        self._request_map(force=True)

    @callback
    def _maybe_refresh_map(self, old: VacuumState, new: VacuumState) -> None:
        following = self._pinned_map is None
        due = following and (
            (new.active and time.monotonic() - self._map_fetched >= MAP_REFRESH_INTERVAL.total_seconds())
            or (old.active and not new.active)
        )
        self._request_map(force=due)

    @callback
    def _request_map(self, force: bool = False) -> None:
        mid = self.display_map_id
        if not mid or self.cloud is None:
            return
        if self._map_fetching:
            self._map_force |= force
            return
        if not force and mid == self.data.map_id:
            cached = self._map_store.get(self.device.device_id, mid)
            if cached and self.data.map_updated:
                return
        self._map_fetching = True
        self.config_entry.async_create_background_task(
            self.hass, self._fetch_map(mid), f"{DOMAIN}_map_{self.device.device_id}"
        )

    async def _fetch_map(self, map_id: str) -> None:
        assert self.cloud is not None
        try:
            result = await self.cloud.async_get_map(self.device.thing_type, self.device.device_id, map_id)
        except Exception as err:
            _LOGGER.debug("Map fetch failed: %s", err)
            result = None
        finally:
            self._map_fetching = False
            self._map_fetched = time.monotonic()

        if result is not None:
            pts = result.get("map") if isinstance(result.get("map"), list) else []
            self.async_set_updated_data(
                replace(self.data, map_points=pts, map_id=map_id, map_updated=dt_util.utcnow())
            )

        force, self._map_force = self._map_force, False
        if force or self.display_map_id != map_id:
            self._request_map(force=force)

    @callback
    def _update_fw(self, reported: dict[str, Any]) -> None:
        fw = (reported.get("firmware") or {}).get("version")
        if not fw or fw == self._fw_ver:
            return
        dev_reg = dr.async_get(self.hass)
        dev = next(
            (d for d in dr.async_entries_for_config_entry(dev_reg, self.config_entry.entry_id)
             if (DOMAIN, self.device.device_id) in d.identifiers),
            None,
        )
        if dev is None:
            return
        self._fw_ver = fw
        if dev.sw_version != fw:
            dev_reg.async_update_device(dev.id, sw_version=fw)

    @callback
    def handle_conn(self, up: bool) -> None:
        self.async_set_updated_data(replace(self.data, mqtt_ok=up))

    def _need_mqtt(self) -> MqttBroker:
        if self.mqtt is None or not self.mqtt.can_pub:
            raise NotConnected()
        return self.mqtt

    async def write_schedules(self, schedules: list[dict[str, Any]]) -> None:
        mqtt = self._need_mqtt()
        if not self.data.shadow_ready:
            raise SchedulesUnavailable()
        try:
            await mqtt.update_shadow(self.device, {"schedules": schedules})
        except Exception as err:
            raise NotConnected() from err
        self.async_set_updated_data(replace(self.data, desired={**self.data.desired, "schedules": schedules}))

    def send_cmd(self, cmd: dict[str, Any]) -> None:
        mqtt = self._need_mqtt()
        self.hass.async_create_background_task(
            self.hass, mqtt.send_cmd(self.device, cmd), f"{DOMAIN}_cmd_{self.device.device_id}"
        )