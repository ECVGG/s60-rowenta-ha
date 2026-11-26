"""Robot state shared by platforms and the card API."""

from __future__ import annotations

from typing import Any

from homeassistant.components.vacuum import VacuumActivity

from .const import CleanMode

RETURNING = {CleanMode.RETURN_HOME.value, CleanMode.RECHARGE_RESUME.value}


def activity(state: dict[str, Any]) -> VacuumActivity | None:
    st = state.get("status")
    method = state.get("method")
    if st is None:
        return None
    if st == "ERROR":
        return VacuumActivity.ERROR
    if st == "CLEANING":
        if method in RETURNING:
            return VacuumActivity.RETURNING
        if method == "PAUSE":
            return VacuumActivity.PAUSED
        return VacuumActivity.CLEANING
    if st == "DOCKING":
        return VacuumActivity.RETURNING
    if st == "CHARGING":
        return VacuumActivity.DOCKED
    return VacuumActivity.IDLE
