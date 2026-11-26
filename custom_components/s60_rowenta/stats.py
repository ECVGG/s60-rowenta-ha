"""Weekly figures computed from the cleaning history."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.util import dt as dt_util


def _start(job: dict[str, Any]) -> datetime | None:
    return dt_util.parse_datetime(job["start"]) if job.get("start") else None


def weekly(jobs: list[dict[str, Any]], now: datetime | None = None) -> dict[str, Any]:
    """Totals of the last seven days."""
    since = (now or dt_util.utcnow()) - timedelta(days=7)
    recent = [j for j in jobs if (start := _start(j)) and start >= since]
    return {
        "cleanings": len(recent),
        "area": sum(j.get("area") or 0 for j in recent),
        "duration": sum(j.get("duration") or 0 for j in recent),
        "errors": sum(1 for j in recent if j.get("error") not in (None, "normal")),
    }


def days_since_last(jobs: list[dict[str, Any]], now: datetime | None = None) -> int | None:
    """Calendar days (local time) since the last cleaning."""
    starts = [s for j in jobs if (s := _start(j))]
    if not starts:
        return None
    today = dt_util.as_local(now or dt_util.utcnow()).date()
    return (today - dt_util.as_local(max(starts)).date()).days
