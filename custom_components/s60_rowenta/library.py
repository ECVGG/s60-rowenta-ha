"""Persistent store of cleaning maps and incidents."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, MAP_POINT_TYPES

STORAGE_VERSION = 1
MAX_SESSIONS = 30
MAX_INCIDENTS = 50
SAVE_DELAY = 30


def library_store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    return Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}")


def compact(points: list[dict[str, Any]]) -> list[list[int]]:
    """Cloud points as [x, y, type] triplets, in drawing order."""
    valid = [
        p for p in points
        if isinstance(p, dict) and isinstance(p.get("x"), int) and isinstance(p.get("y"), int)
    ]
    valid.sort(key=lambda p: p.get("index", 0))
    return [[p["x"], p["y"], p.get("type", -1)] for p in valid]


def expand(triplets: list[list[int]]) -> list[dict[str, int]]:
    return [{"x": x, "y": y, "type": t, "index": i} for i, (x, y, t) in enumerate(triplets)]


def last_position(triplets: list[list[int]]) -> list[int] | None:
    for x, y, kind in reversed(triplets):
        if kind in MAP_POINT_TYPES["path"]:
            return [x, y]
    return None


class MapLibrary:
    """Maps and incidents of every robot of one config entry."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = library_store(hass, entry_id)
        self._data: dict[str, Any] = {}

    async def async_load(self) -> None:
        self._data = await self._store.async_load() or {}

    def _device(self, device_id: str) -> dict[str, Any]:
        return self._data.setdefault(device_id, {"sessions": {}, "incidents": []})

    def sessions(self, device_id: str) -> dict[str, dict[str, Any]]:
        return self._device(device_id)["sessions"]

    def incidents(self, device_id: str) -> list[dict[str, Any]]:
        return self._device(device_id)["incidents"]

    def latest(self, device_id: str) -> tuple[str, dict[str, Any]] | None:
        sessions = self.sessions(device_id)
        if not sessions:
            return None
        return max(sessions.items(), key=lambda item: item[1]["updated"])

    @callback
    def save_map(self, device_id: str, map_id: str, points: list[dict[str, Any]]) -> None:
        triplets = compact(points)
        if not triplets:
            return
        sessions = self.sessions(device_id)
        old = sessions.get(map_id)
        # Re-reading an unchanged old map must not make it the most recent one
        if old and old["points"] == triplets:
            return
        sessions[map_id] = {"points": triplets, "updated": dt_util.utcnow().isoformat()}
        while len(sessions) > MAX_SESSIONS:
            del sessions[min(sessions, key=lambda k: sessions[k]["updated"])]
        self._save()

    @callback
    def add_incident(self, device_id: str, code: str, map_id: str | None, position: list[int] | None) -> None:
        incidents = self.incidents(device_id)
        incidents.append(
            {"time": dt_util.utcnow().isoformat(), "code": code.lower(), "map_id": map_id, "position": position}
        )
        del incidents[:-MAX_INCIDENTS]
        self._save()

    @callback
    def _save(self) -> None:
        self._store.async_delay_save(lambda: self._data, SAVE_DELAY)

    async def async_flush(self) -> None:
        await self._store.async_save(self._data)
