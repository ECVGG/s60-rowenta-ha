"""Websocket API used by the map card."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.vacuum import VacuumActivity
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .activity import activity
from .const import DOMAIN, MAP_ORIGIN, MAP_POINT_TYPES
from .library import compact


@callback
def async_register(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_map)


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/map", vol.Required("entity_id"): str}
)
@callback
def ws_map(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    registered = er.async_get(hass).async_get(msg["entity_id"])
    entry = None
    if registered and registered.platform == DOMAIN and registered.config_entry_id:
        entry = hass.config_entries.async_get_entry(registered.config_entry_id)
    coordinator = None
    if entry and entry.state is ConfigEntryState.LOADED:
        coordinator = next(
            (c for did, c in entry.runtime_data.coordinators.items()
             if registered.unique_id.startswith(f"{did}_")),
            None,
        )
    if coordinator is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "Robot not found")
        return

    library = coordinator.library
    device_id = coordinator.device.device_id
    jobs = {job["map_id"]: job for job in coordinator.data.cleanings}
    sessions = [
        {"id": map_id, "start": (jobs.get(map_id) or {}).get("start") or s["updated"], "points": s["points"]}
        for map_id, s in library.sessions(device_id).items()
    ]
    sessions.sort(key=lambda s: s["start"], reverse=True)
    data = coordinator.data
    connection.send_result(
        msg["id"],
        {
            "origin": [MAP_ORIGIN, MAP_ORIGIN],
            "types": {name: sorted(values) for name, values in MAP_POINT_TYPES.items()},
            "active": data.active,
            "docked": activity(data.status) == VacuumActivity.DOCKED,
            "current": {"id": data.map_id, "points": compact(data.map_points)},
            "sessions": sessions,
            "incidents": library.incidents(device_id),
        },
    )
