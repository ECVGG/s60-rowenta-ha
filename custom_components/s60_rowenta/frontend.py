"""Serve and load the bundled map card."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import DOMAIN

CARD_FILE = "s60-rowenta-map-card.js"
CARD_URL = f"/{DOMAIN}/{CARD_FILE}"


async def async_register_card(hass: HomeAssistant) -> None:
    if hass.http is None:
        return
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(Path(__file__).parent / "www" / CARD_FILE), False)]
    )
    if "frontend" in hass.config.components:
        from homeassistant.components.frontend import add_extra_js_url

        version = (await async_get_integration(hass, DOMAIN)).version
        add_extra_js_url(hass, f"{CARD_URL}?v={version}")
