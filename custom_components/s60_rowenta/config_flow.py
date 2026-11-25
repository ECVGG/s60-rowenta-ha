"""Config flow for Rowenta Series 60."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    CountrySelector,
    CountrySelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .auth import async_get_market, async_login
from .const import CONF_COUNTRY, CONF_MARKET, CONF_PERIMETER, CONF_REFRESH_TOKEN, DOMAIN
from .exceptions import AuthFailed, CloudUnreachable, ProtocolMismatch
from .options_flow import S60OptionsFlow

_LOGGER = logging.getLogger(__name__)

PASSWORD_SEL = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
EMAIL_SEL = TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username"))


class S60ConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return S60OptionsFlow()

    async def _try_login(
        self, email: str, password: str, country: str
    ) -> tuple[dict[str, Any] | None, list[str], dict[str, str]]:
        session = async_get_clientsession(self.hass)
        try:
            market = await async_get_market(session, country)
        except CloudUnreachable:
            _LOGGER.exception("Market config failed")
            return None, [], {"base": "no_connection"}
        except ProtocolMismatch:
            return None, [], {CONF_COUNTRY: "bad_country"}

        try:
            tokens = await async_login(email, password)
            from .auth import SebCloud
            cloud = SebCloud(session, tokens["refresh_token"], market.perimeter)
            devices = await cloud.async_get_devices()
        except AuthFailed:
            return None, [], {"base": "bad_auth"}
        except CloudUnreachable:
            _LOGGER.exception("Cloud login failed")
            return None, [], {"base": "no_connection"}
        except ProtocolMismatch:
            _LOGGER.exception("Protocol error")
            return None, [], {"base": "no_connection"}

        if not devices:
            return None, [], {"base": "no_device"}

        if not cloud.user_id:
            return None, [], {"base": "no_connection"}

        await self.async_set_unique_id(f"{cloud.user_id}_{market.perimeter}")

        data = {
            CONF_EMAIL: email,
            CONF_COUNTRY: country,
            CONF_MARKET: market.name,
            CONF_PERIMETER: market.perimeter,
            CONF_REFRESH_TOKEN: cloud.refresh_token,
        }
        return data, [d["name"] for d in devices], {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip().lower()
            for entry in self._async_current_entries():
                if (str(entry.data.get(CONF_EMAIL, "")).strip().lower() == email
                        and entry.data.get(CONF_COUNTRY) == user_input[CONF_COUNTRY]):
                    return self.async_abort(reason="already_set")

            data, names, errors = await self._try_login(
                user_input[CONF_EMAIL], user_input[CONF_PASSWORD], user_input[CONF_COUNTRY]
            )
            if data:
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Rowenta X-Plorer ({', '.join(names)})",
                    data=data,
                )

        country_def = {"default": self.hass.config.country} if self.hass.config.country else {}
        schema = vol.Schema({
            vol.Required(CONF_EMAIL): EMAIL_SEL,
            vol.Required(CONF_PASSWORD): PASSWORD_SEL,
            vol.Required(CONF_COUNTRY, **country_def): CountrySelector(CountrySelectorConfig()),
        })
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        email = entry.data.get(CONF_EMAIL, "")
        errors: dict[str, str] = {}
        if user_input is not None:
            email = user_input.get(CONF_EMAIL, email)
            data, _names, errors = await self._try_login(
                email, user_input[CONF_PASSWORD], entry.data[CONF_COUNTRY]
            )
            if data:
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(entry, data=data)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({
                vol.Required(CONF_EMAIL, default=email): EMAIL_SEL,
                vol.Required(CONF_PASSWORD): PASSWORD_SEL,
            }),
            errors=errors,
        )