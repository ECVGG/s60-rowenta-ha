"""Options flow: schedule management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState, ConfigFlowResult, OptionsFlow
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    BooleanSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TimeSelector,
)

from .const import DAY_TO_CODE, SCHEDULE_MODES, SCHEDULE_POWERS
from .schedules import apply_changes, find_idx, to_dict

if TYPE_CHECKING:
    from .coordinator import VacuumCoordinator

DAY_LABEL = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu", "fri": "Fri", "sat": "Sat", "sun": "Sun"}
DEFAULTS = {
    "name": "Schedule",
    "start": "09:00:00",
    "days": ["mon", "tue", "wed", "thu", "fri"],
    "mode": "smart_cleaning",
    "power": "normal",
    "enabled": True,
}


def _sel(opts: list[str], key: str, multi: bool = False) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=opts,
            translation_key=key,
            multiple=multi,
            mode=SelectSelectorMode.LIST if multi else SelectSelectorMode.DROPDOWN,
        )
    )


def _schema(defs: dict[str, Any]) -> vol.Schema:
    return vol.Schema({
        vol.Required("name", default=defs["name"]): TextSelector(),
        vol.Required("start", default=defs["start"]): TimeSelector(),
        vol.Required("days", default=defs["days"]): _sel(list(DAY_TO_CODE.values()), "day", True),
        vol.Required("mode", default=defs["mode"]): _sel(SCHEDULE_MODES, "sched_mode"),
        vol.Required("power", default=defs["power"]): _sel(SCHEDULE_POWERS, "sched_power"),
        vol.Required("enabled", default=defs["enabled"]): BooleanSelector(),
    })


def _label(sch: dict[str, Any]) -> str:
    d = to_dict(sch)
    days = ", ".join(DAY_LABEL.get(x, x) for x in d["days"])
    return f"{d['name']} – {d['start']} {days}{'' if d['enabled'] else ' (off)'}"


class S60OptionsFlow(OptionsFlow):
    def __init__(self) -> None:
        self._dev_id: str | None = None
        self._sched_id: str | None = None

    def _coords(self) -> dict[str, VacuumCoordinator]:
        return self.config_entry.runtime_data.coordinators

    def _coord(self) -> VacuumCoordinator:
        assert self._dev_id
        return self._coords()[self._dev_id]

    async def _save(self, scheds: list[dict[str, Any]]) -> dict[str, str]:
        try:
            await self._coord().write_schedules(scheds)
        except HomeAssistantError as err:
            return {"base": err.translation_key or "no_connection"}
        return {}

    def _done(self) -> ConfigFlowResult:
        return self.async_create_entry(data=dict(self.config_entry.options))

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self.config_entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_ready")
        coords = self._coords()
        if len(coords) == 1:
            self._dev_id = next(iter(coords))
            return await self.async_step_menu()
        if user_input is not None:
            self._dev_id = user_input["device"]
            return await self.async_step_menu()
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required("device"): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=did, label=c.device.name)
                            for did, c in coords.items()
                        ]
                    )
                )
            }),
        )

    async def async_step_menu(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        opts = ["add"]
        if self._coord().data.schedules:
            opts += ["edit", "delete"]
        return self.async_show_menu(step_id="menu", menu_options=opts)

    async def async_step_add(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errs: dict[str, str] = {}
        if user_input is not None:
            if not user_input["days"]:
                errs["days"] = "no_days"
            else:
                scheds = list(self._coord().data.schedules)
                scheds.append(apply_changes(None, **user_input))
                if not (errs := await self._save(scheds)):
                    return self._done()
        return self.async_show_form(
            step_id="add",
            data_schema=self.add_suggested_values_to_schema(_schema(DEFAULTS), user_input or {}),
            errors=errs,
        )

    def _pick(self, multi: bool = False) -> vol.Schema:
        opts = [
            SelectOptionDict(value=s["id"], label=_label(s))
            for s in self._coord().data.schedules if s.get("id")
        ]
        return vol.Schema({
            vol.Required("schedule"): SelectSelector(
                SelectSelectorConfig(options=opts, multiple=multi, mode=SelectSelectorMode.LIST)
            )
        })

    async def async_step_edit(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._sched_id = user_input["schedule"]
            return await self.async_step_edit_form()
        return self.async_show_form(step_id="edit", data_schema=self._pick())

    async def async_step_edit_form(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        scheds = list(self._coord().data.schedules)
        idx = find_idx(scheds, self._sched_id or "")
        if idx is None:
            return self.async_abort(reason="sched_gone")

        errs: dict[str, str] = {}
        if user_input is not None:
            if not user_input["days"]:
                errs["days"] = "no_days"
            else:
                scheds[idx] = apply_changes(scheds[idx], **user_input)
                if not (errs := await self._save(scheds)):
                    return self._done()

        cur = to_dict(scheds[idx])
        defs = {
            "name": cur["name"] or "",
            "start": f"{cur['start'] or '09:00'}:00",
            "days": cur["days"],
            "mode": cur["mode"] if cur["mode"] in SCHEDULE_MODES else "smart_cleaning",
            "power": cur["power"] if cur["power"] in SCHEDULE_POWERS else "normal",
            "enabled": cur["enabled"],
        }
        return self.async_show_form(
            step_id="edit_form",
            data_schema=self.add_suggested_values_to_schema(_schema(defs), user_input or {}),
            description_placeholders={"schedule": _label(scheds[idx])},
            errors=errs,
        )

    async def async_step_delete(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errs: dict[str, str] = {}
        if user_input is not None:
            drop = set(user_input["schedule"])
            scheds = [s for s in self._coord().data.schedules if s.get("id") not in drop]
            if not (errs := await self._save(scheds)):
                return self._done()
        return self.async_show_form(step_id="delete", data_schema=self._pick(multi=True), errors=errs)