"""Schedule management for device shadow."""

from __future__ import annotations

import copy
import uuid
from datetime import time
from typing import Any

from .const import DAY_TO_CODE, CODE_TO_DAY, SCHEDULE_MODES, SCHEDULE_POWERS


def extract_feats(raw: dict[str, Any]) -> dict[str, str]:
    return {
        str(f.get("name", "")).lower(): str(f.get("value", ""))
        for f in raw.get("features") or []
        if isinstance(f, dict)
    }


def to_dict(raw: dict[str, Any]) -> dict[str, Any]:
    feats = extract_feats(raw)
    return {
        "uid": raw.get("id"),
        "name": raw.get("name"),
        "enabled": bool(raw.get("enabled", True)),
        "start": raw.get("start", "09:00")[:5],
        "days": [DAY_TO_CODE[d] for d in sorted(raw.get("days") or []) if d in DAY_TO_CODE],
        "mode": feats.get("method", "").lower() or None,
        "power": feats.get("power", "").lower() or None,
    }


def find_idx(schedules: list[dict[str, Any]], key: str) -> int | None:
    for i, s in enumerate(schedules):
        if s.get("id") == key:
            return i
    matches = [i for i, s in enumerate(schedules) if s.get("name") == key]
    return matches[0] if len(matches) == 1 else None


def apply_changes(
    base: dict[str, Any] | None,
    *,
    name: str | None = None,
    start: time | str | None = None,
    days: list[str] | None = None,
    mode: str | None = None,
    power: str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    raw = copy.deepcopy(base) if base else {
        "id": str(uuid.uuid4()),
        "name": "Schedule",
        "start": "09:00",
        "days": [1, 2, 3, 4, 5],
        "features": [
            {"name": "method", "value": "SMART_CLEANING"},
            {"name": "power", "value": "NORMAL"},
        ],
        "enabled": True,
    }
    if name is not None:
        raw["name"] = name
    if start is not None:
        raw["start"] = start.strftime("%H:%M") if isinstance(start, time) else str(start)[:5]
    if days is not None:
        raw["days"] = sorted({CODE_TO_DAY[d] for d in days if d in CODE_TO_DAY})
    if enabled is not None:
        raw["enabled"] = enabled
    for k, v in (("method", mode), ("power", power)):
        if v is not None:
            _set_feat(raw, k, v.upper())
    return raw


def _set_feat(raw: dict[str, Any], name: str, value: str) -> None:
    feats = raw.get("features")
    if not isinstance(feats, list):
        feats = raw["features"] = []
    for f in feats:
        if isinstance(f, dict) and str(f.get("name", "")).lower() == name:
            f["value"] = value
            return
    feats.append({"name": name, "value": value})