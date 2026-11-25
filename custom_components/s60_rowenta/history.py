"""History parsing utilities."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util


def ms_to_dt(value: Any) -> datetime | None:
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return dt_util.utc_from_timestamp(value / 1000)


def lower(value: Any) -> str | None:
    return value.lower() if isinstance(value, str) else None


def parse_history(raw: dict[str, Any]) -> list[dict[str, Any]]:
    items = [i for i in raw.get("datasHistory") or [] if isinstance(i, dict) and i.get("mapId")]
    items.sort(key=lambda i: i.get("startTimestamp") or 0, reverse=True)
    return items


def job_to_dict(item: dict[str, Any]) -> dict[str, Any]:
    status = item.get("status") or {}
    start = ms_to_dt(item.get("startTimestamp"))
    end = ms_to_dt(item.get("endTimestamp"))
    return {
        "map_id": str(item.get("mapId", "")),
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
        "area": item.get("cleaningArea"),
        "duration": item.get("cleaningDuration"),
        "mode": lower(status.get("method")),
        "power": lower(status.get("power")),
        "error": lower(status.get("errorCode")),
        "battery": status.get("battery"),
    }


def job_label(job: dict[str, Any]) -> str:
    """Label for a job already converted by job_to_dict."""
    start = dt_util.parse_datetime(job["start"]) if job.get("start") else None
    when = dt_util.as_local(start).strftime("%Y-%m-%d %H:%M") if start else str(job.get("map_id", "?"))
    parts = [when]
    if (area := job.get("area")) is not None:
        parts.append(f"{area} m\u00b2")
    if (dur := job.get("duration")) is not None:
        parts.append(f"{dur} min")
    if job.get("error") not in (None, "normal"):
        parts.append("!")
    return " \u00b7 ".join(parts)
