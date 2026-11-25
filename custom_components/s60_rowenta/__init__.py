"""Rowenta X-Plorer Series 60 (Groupe SEB Cloud, AWS IoT)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import voluptuous as vol
from homeassistant.components.vacuum import DOMAIN as VACUUM_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, SupportsResponse, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from .auth import SebCloud
from .const import (
    CONF_PERIMETER,
    CONF_REFRESH_TOKEN,
    DAY_TO_CODE,
    DOMAIN,
    HISTORY_POLL_INTERVAL,
    SCHEDULE_MODES,
    SCHEDULE_POWERS,
    STATUS_POLL_ACTIVE,
    STATUS_POLL_IDLE,
)
from .coordinator import VacuumCoordinator
from .exceptions import AuthFailed
from .models import DeviceInfo
from .mqtt import MqttBroker

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.IMAGE,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.VACUUM,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_SCHED_FIELDS = {
    vol.Optional("name"): cv.string,
    vol.Optional("start"): cv.time,
    vol.Optional("days"): vol.All(cv.ensure_list, [vol.In(list(DAY_TO_CODE.values()))], vol.Length(min=1)),
    vol.Optional("mode"): vol.In(SCHEDULE_MODES),
    vol.Optional("power"): vol.In(SCHEDULE_POWERS),
    vol.Optional("enabled"): cv.boolean,
}


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    for name, schema, func, resp in (
        ("get_schedules", {}, "async_get_schedules", SupportsResponse.ONLY),
        ("set_schedule", {vol.Optional("schedule"): cv.string, **_SCHED_FIELDS}, "async_set_schedule", SupportsResponse.OPTIONAL),
        ("delete_schedule", {vol.Required("schedule"): cv.string}, "async_delete_schedule", SupportsResponse.NONE),
    ):
        service.async_register_platform_entity_service(
            hass, DOMAIN, name, entity_domain=VACUUM_DOMAIN, schema=schema, func=func, supports_response=resp
        )
    return True


@dataclass
class S60Data:
    cloud: SebCloud
    mqtt: MqttBroker
    coordinators: dict[str, VacuumCoordinator]


type S60ConfigEntry = ConfigEntry[S60Data]


async def async_setup_entry(hass: HomeAssistant, entry: S60ConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    cloud = SebCloud(session, entry.data[CONF_REFRESH_TOKEN], entry.data[CONF_PERIMETER])

    try:
        devices = await cloud.async_get_devices()
    except AuthFailed as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except Exception as err:
        raise ConfigEntryNotReady(str(err)) from err

    device_infos = [
        DeviceInfo(device_id=d["device_id"], thing_type=d["thing_type"], name=d["name"], model_code=d.get("model_code"))
        for d in devices
    ]

    @callback
    def _save_token(tok: str) -> None:
        if tok != entry.data.get(CONF_REFRESH_TOKEN):
            hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_REFRESH_TOKEN: tok})

    cloud.set_refresh_callback(_save_token)
    _save_token(cloud.refresh_token)

    coords = {d.device_id: VacuumCoordinator(hass, entry, d) for d in device_infos}

    @callback
    def _on_msg(dev: DeviceInfo, kind: str, payload: Any) -> None:
        if c := coords.get(dev.device_id):
            c.handle_mqtt(kind, payload)

    @callback
    def _on_conn(up: bool) -> None:
        for c in coords.values():
            c.handle_conn(up)

    @callback
    def _on_auth_fail() -> None:
        entry.async_start_reauth(hass)

    mqtt = MqttBroker(hass, cloud, device_infos, _on_msg, _on_conn, _on_auth_fail)
    for c in coords.values():
        c.mqtt = mqtt
        c.cloud = cloud

    entry.runtime_data = S60Data(cloud, mqtt, coords)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # The MQTT loop runs for the lifetime of the entry: never await it here
    entry.async_create_background_task(hass, mqtt.run(), f"{DOMAIN}_mqtt")
    entry.async_on_unload(mqtt.stop)

    last_poll = 0.0

    @callback
    def _poll_status(_now: datetime) -> None:
        nonlocal last_poll
        if not mqtt.can_pub:
            return
        cleaning = any(c.data.active for c in coords.values())
        if not cleaning and time.monotonic() - last_poll < STATUS_POLL_IDLE.total_seconds():
            return
        last_poll = time.monotonic()
        try:
            for c in coords.values():
                if not c.data.shadow_ready:
                    entry.async_create_background_task(hass, mqtt._get_shadow(c.device), f"{DOMAIN}_shadow_{c.device.device_id}")
                entry.async_create_background_task(hass, mqtt._get_status(c.device, True), f"{DOMAIN}_status_{c.device.device_id}")
        except Exception as err:
            _LOGGER.debug("Status poll error: %s", err)

    @callback
    def _poll_hist(_now: datetime) -> None:
        if not mqtt.can_pub:
            return
        try:
            for c in coords.values():
                entry.async_create_background_task(hass, mqtt._get_history(c.device), f"{DOMAIN}_hist_{c.device.device_id}")
        except Exception as err:
            _LOGGER.debug("History poll error: %s", err)

    entry.async_on_unload(async_track_time_interval(hass, _poll_status, STATUS_POLL_ACTIVE))
    entry.async_on_unload(async_track_time_interval(hass, _poll_hist, HISTORY_POLL_INTERVAL))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: S60ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)