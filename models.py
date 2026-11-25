"""Data models for Rowenta Series 60 integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass(slots=True, frozen=True)
class DeviceInfo:
    """Paired device from user profile."""
    device_id: str
    thing_type: str
    name: str
    model_code: str | None = None

    @property
    def mqtt_base(self) -> str:
        return f"{self.thing_type}/{self.device_id}"

    @property
    def shadow_base(self) -> str:
        return f"$aws/things/{self.thing_type}-{self.device_id}/shadow"


@dataclass(slots=True, frozen=True)
class AWSCreds:
    """Temporary AWS credentials from Cognito."""
    access_key: str
    secret_key: str
    session_token: str
    expiration: float

    @property
    def expired(self) -> bool:
        import time
        return time.time() >= self.expiration - 60


@dataclass(slots=True, frozen=True)
class Market:
    """Market/perimeter for a country."""
    name: str
    perimeter: str


@dataclass(slots=True)
class VacuumState:
    """Current vacuum state (updated via MQTT)."""
    mqtt_ok: bool = False
    shadow_ready: bool = False

    status: dict[str, Any] = field(default_factory=dict)
    reported: dict[str, Any] = field(default_factory=dict)
    desired: dict[str, Any] = field(default_factory=dict)
    history: dict[str, Any] = field(default_factory=dict)
    cleanings: list[dict[str, Any]] = field(default_factory=list)

    map_points: list[dict[str, Any]] = field(default_factory=list)
    map_id: str | None = None
    map_updated: datetime | None = None

    @property
    def active(self) -> bool:
        st = self.status.get("status")
        method = self.status.get("method")
        return st in {"CLEANING", "DOCKING"} and method != "PAUSE"

    @property
    def battery(self) -> int | None:
        return self.status.get("battery")

    @property
    def mode(self) -> str | None:
        return self.status.get("method")

    @property
    def power(self) -> str | None:
        return self.status.get("power")

    @property
    def error(self) -> str | None:
        return self.status.get("errorCode")

    @property
    def schedules(self) -> list[dict[str, Any]]:
        desired = self.desired.get("schedules")
        if isinstance(desired, list):
            return desired
        return list(self.reported.get("schedules") or [])

    @property
    def online(self) -> bool | None:
        return (self.reported.get("status") or {}).get("connected")

    @property
    def available(self) -> bool:
        return self.mqtt_ok and bool(self.status) and self.online is not False


@dataclass(slots=True, frozen=True)
class CleaningJob:
    """Single cleaning session from history."""
    map_id: str
    start: datetime | None
    end: datetime | None
    area: float | None
    duration: int | None
    mode: str | None
    power: str | None
    error: str | None
    battery: int | None

    @classmethod
    def from_raw(cls, item: dict[str, Any]) -> CleaningJob:
        from .history import ms_to_dt, lower
        status = item.get("status") or {}
        return cls(
            map_id=str(item.get("mapId", "")),
            start=ms_to_dt(item.get("startTimestamp")),
            end=ms_to_dt(item.get("endTimestamp")),
            area=item.get("cleaningArea"),
            duration=item.get("cleaningDuration"),
            mode=lower(status.get("method")),
            power=lower(status.get("power")),
            error=lower(status.get("errorCode")),
            battery=status.get("battery"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "map_id": self.map_id,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "area": self.area,
            "duration": self.duration,
            "mode": self.mode,
            "power": self.power,
            "error": self.error,
            "battery": self.battery,
        }


@dataclass(slots=True, frozen=True)
class ScheduleEntry:
    """Cleaning schedule from AWS shadow."""
    uid: str
    name: str
    enabled: bool
    start: str
    days: list[str]
    mode: str | None
    power: str | None

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> ScheduleEntry:
        from .const import DAY_TO_CODE
        feats = {
            str(f.get("name", "")).lower(): str(f.get("value", ""))
            for f in raw.get("features") or []
            if isinstance(f, dict)
        }
        return cls(
            uid=raw.get("id", ""),
            name=raw.get("name", ""),
            enabled=bool(raw.get("enabled", True)),
            start=raw.get("start", "09:00")[:5],
            days=[DAY_TO_CODE[d] for d in sorted(raw.get("days") or []) if d in DAY_TO_CODE],
            mode=feats.get("method", "").lower() or None,
            power=feats.get("power", "").lower() or None,
        )

    def to_raw(self) -> dict[str, Any]:
        from .const import CODE_TO_DAY
        return {
            "id": self.uid,
            "name": self.name,
            "enabled": self.enabled,
            "start": self.start,
            "days": [CODE_TO_DAY[d] for d in self.days if d in CODE_TO_DAY],
            "features": [
                {"name": "method", "value": (self.mode or "SMART_CLEANING").upper()},
                {"name": "power", "value": (self.power or "NORMAL").upper()},
            ],
        }