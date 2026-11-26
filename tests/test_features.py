import asyncio
import json
import time
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from homeassistant.util.yaml import load_yaml_dict
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.s60_rowenta.library import MapLibrary
from custom_components.s60_rowenta.map_renderer import render_map
from custom_components.s60_rowenta.stats import days_since_last, weekly

from . import test_integration as base

DATA = {"refresh_token": "r", "profile_perimeter": "p"}
STATUS = {"status": "CLEANING", "method": "SMART_CLEANING", "errorCode": "NORMAL", "mapId": "5"}


def test_stats():
    now = dt_util.utcnow()
    jobs = [
        {"start": (now - timedelta(days=1)).isoformat(), "area": 10, "duration": 5, "error": "normal"},
        {"start": (now - timedelta(days=9)).isoformat(), "area": 99, "duration": 9, "error": "bumper_error"},
    ]
    assert weekly(jobs, now) == {"cleanings": 1, "area": 10, "duration": 5, "errors": 0}
    assert days_since_last(jobs, now) in (1, 2)
    assert days_since_last([], now) is None


def test_render():
    points = [{"x": 128 + i, "y": 128, "type": 3, "index": i} for i in range(30)]
    assert render_map(points, (157, 128))[:4] == b"\x89PNG"
    assert render_map([], None)[:4] == b"\x89PNG"


async def test_library_limits_and_persists(hass, hass_storage):
    library = MapLibrary(hass, "e")
    await library.async_load()
    for i in range(35):
        library.save_map("d", str(i), [{"x": i, "y": 1, "type": 1}])
    library.save_map("d", "empty", [])
    await library.async_flush()
    again = MapLibrary(hass, "e")
    await again.async_load()
    assert len(again.sessions("d")) == 30 and "34" in again.sessions("d")


@pytest.mark.parametrize("name", ["smart_cleaning", "weekly_report"])
async def test_blueprints(hass, name):
    from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
    from homeassistant.components.blueprint.models import Blueprint

    path = Path(__file__).parent.parent / "blueprints/automation/s60_rowenta" / f"{name}.yaml"
    data = await hass.async_add_executor_job(load_yaml_dict, str(path))
    Blueprint(data, expected_domain="automation", schema=AUTOMATION_BLUEPRINT_SCHEMA)


async def test_card_api_incidents_and_restart(hass, hass_ws_client, hass_client):
    await async_setup_component(hass, "http", {})
    with patch("custom_components.s60_rowenta.SebCloud", base.FakeCloud), patch(
        "custom_components.s60_rowenta.mqtt.AsyncMQTT", base.FakeMQTT
    ):
        entry = MockConfigEntry(domain="s60_rowenta", data=DATA)
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await asyncio.sleep(0.2)
        await base.send(hass, "VAC001/abc/status", STATUS)
        await base.send(hass, "VAC001/abc/status", {**STATUS, "errorCode": "BUMPER_ERROR"})
        await base.send(hass, "VAC001/abc/status", {**STATUS, "errorCode": "BUMPER_ERROR"})

        ws = await hass_ws_client(hass)
        await ws.send_json({"id": 1, "type": "s60_rowenta/map", "entity_id": "vacuum.robo"})
        result = (await ws.receive_json())["result"]
        assert result["current"]["id"] == "5" and len(result["current"]["points"]) == 2
        assert len(result["sessions"]) == 1
        assert [i["code"] for i in result["incidents"]] == ["bumper_error"]
        assert result["incidents"][0]["position"] == [129, 128]
        await ws.send_json({"id": 2, "type": "s60_rowenta/map", "entity_id": "vacuum.nope"})
        assert not (await ws.receive_json())["success"]

        client = await hass_client()
        card = await client.get("/s60_rowenta/s60-rowenta-map-card.js")
        assert card.status == 200 and "customElements.define" in await card.text()

        # After a reload the map is there before the robot says anything
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        image = hass.states.get("image.robo_map")
        assert image.state not in ("unavailable", "unknown")
        assert await hass.config_entries.async_unload(entry.entry_id)
