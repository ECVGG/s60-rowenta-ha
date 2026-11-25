"""Downloadable diagnostics, with personal data removed."""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant

from . import S60ConfigEntry

REDACTED = "**REDACTED**"

# Keys containing any of these are hidden
_SECRET_PARTS = (
    "token", "mail", "password", "secret", "serial", "ssid", "user", "owner",
    "uuid", "thingname", "deviceid", "device_id", "functionalid", "clientid",
    "address", "location", "household", "wifi",
)
# Keys hidden only on exact match
_SECRET_KEYS = {"id", "uid", "ip", "mac", "lat", "lon", "latitude", "longitude"}
# "name" is also used for technical values that are needed for debugging
_SAFE_NAMES = {"method", "power", "side-brush", "main-brush", "filter"}
_SECRET_VALUES = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.]+"  # email
    r"|\b(?:\d{1,3}\.){3}\d{1,3}\b"  # IPv4
    r"|\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b"  # MAC
    r"|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


def redact(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    """Recursively remove personal data."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            low = str(key).lower()
            hide = low in _SECRET_KEYS or any(p in low for p in _SECRET_PARTS)
            if low == "name":
                hide = str(item).lower() not in _SAFE_NAMES
            # Keys can themselves be identifiers
            result[redact(str(key), secrets)] = REDACTED if hide else redact(item, secrets)
        return result
    if isinstance(value, (list, tuple)):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, REDACTED)
        return _SECRET_VALUES.sub(REDACTED, value)
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: S60ConfigEntry
) -> dict[str, Any]:
    coordinators = entry.runtime_data.coordinators
    secrets = tuple(coordinators)
    robots = []
    for coordinator in coordinators.values():
        data = asdict(coordinator.data)
        if data["map_updated"]:
            data["map_updated"] = data["map_updated"].isoformat()
        robots.append(
            {"thing_type": coordinator.device.thing_type, "data": redact(data, secrets)}
        )
    return {"mqtt_connected": entry.runtime_data.mqtt.can_pub, "robots": robots}
