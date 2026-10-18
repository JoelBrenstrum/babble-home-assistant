from __future__ import annotations

from datetime import timedelta
import time

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.babble.const import (
    CONF_ACCESS_TOKEN,
    CONF_ANON_KEY,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    CONF_SUPABASE_URL,
    CONF_URL,
    DOMAIN,
)

from .conftest import BABY_ID, SNAPSHOT, SUPABASE_URL, URL, snapshot

STATE_URL = f"{URL}/api/ha/v1/babies/{BABY_ID}/state"
BABIES = [{"id": BABY_ID, "name": "Olive", "family_id": "family-1", "family_name": "Brenstrums"}]


def make_entry(expires_at: float | None = None) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="user-1",
        title="joel@example.com",
        data={
            CONF_URL: URL,
            CONF_SUPABASE_URL: SUPABASE_URL,
            CONF_ANON_KEY: "anon",
            CONF_ACCESS_TOKEN: "access-1",
            CONF_REFRESH_TOKEN: "refresh-1",
            CONF_EXPIRES_AT: expires_at if expires_at is not None else time.time() + 3600,
        },
    )


async def setup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, entry: MockConfigEntry | None = None
):
    entry = entry or make_entry()
    aioclient_mock.get(f"{URL}/api/ha/v1/babies", json=BABIES)
    aioclient_mock.get(STATE_URL, json=SNAPSHOT)
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.fixture(autouse=True)
def frozen(freezer: FrozenDateTimeFactory) -> FrozenDateTimeFactory:
    freezer.move_to("2026-10-06T12:00:00+00:00")
    return freezer


async def test_creates_a_device_per_baby_with_sensors(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = await setup(hass, aioclient_mock)
    assert entry.state is ConfigEntryState.LOADED

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, BABY_ID)})
    assert device and device.name == "Olive"

    assert hass.states.get("binary_sensor.olive_asleep").state == "on"
    assert hass.states.get("binary_sensor.olive_feeding").state == "off"
    assert hass.states.get("binary_sensor.olive_feed_overdue").state == "off"
    assert hass.states.get("sensor.olive_current_sleep").state == "60"
    assert hass.states.get("sensor.olive_sleep").state == "active"
    assert hass.states.get("sensor.olive_next_feed_due").state == "2026-10-06T13:00:00+00:00"
    assert hass.states.get("sensor.olive_next_breast_side").state == "left"
    assert hass.states.get("sensor.olive_last_nappy").attributes["type"] == "both"
    assert hass.states.get("sensor.olive_weight").attributes["percentile"] == 48.3
    assert hass.states.get("sensor.olive_wet_nappies_today").state == "1"
    assert hass.states.get("sensor.olive_predicted_next_sleep").state == "unavailable"

    calls = [call for call in aioclient_mock.mock_calls if str(call[1]) == STATE_URL]
    assert calls[0][3]["authorization"] == "Bearer access-1"
    assert calls[0][3]["x-babble-device"] == "Home Assistant"


async def test_durations_and_overdue_tick_between_polls(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, frozen: FrozenDateTimeFactory
):
    await setup(hass, aioclient_mock)
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{URL}/api/ha/v1/babies", json=BABIES)
    aioclient_mock.get(STATE_URL, json=SNAPSHOT)

    frozen.tick(timedelta(minutes=61))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.olive_current_sleep").state == "121"
    assert hass.states.get("binary_sensor.olive_feed_overdue").state == "on"


async def test_actions_post_to_babble_and_update_state(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await setup(hass, aioclient_mock)
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, BABY_ID)})
    action_url = f"{URL}/api/ha/v1/babies/{BABY_ID}/actions/log_bottle"
    aioclient_mock.post(action_url, json=snapshot(bottle={"amount_ml": 90}))

    await hass.services.async_call(
        DOMAIN,
        "log_bottle",
        {"device_id": device.id, "amount_ml": 90, "content": "formula", "started_at": "2026-10-06 11:30:00"},
        blocking=True,
    )

    call = next(call for call in aioclient_mock.mock_calls if str(call[1]) == action_url)
    assert call[2]["amount_ml"] == 90
    assert call[2]["content"] == "formula"
    assert call[2]["started_at"].startswith("2026-10-")
    assert hass.states.get("sensor.olive_last_bottle").attributes["amount_ml"] == 90


async def test_action_errors_reach_the_user(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    await setup(hass, aioclient_mock)
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, BABY_ID)})
    aioclient_mock.post(
        f"{URL}/api/ha/v1/babies/{BABY_ID}/actions/pause_nursing",
        status=409,
        json={"error": "No feed is running."},
    )
    with pytest.raises(HomeAssistantError, match="No feed is running."):
        await hass.services.async_call(DOMAIN, "pause_nursing", {"device_id": device.id}, blocking=True)


async def test_switches_start_and_end_sessions(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    await setup(hass, aioclient_mock)
    end_url = f"{URL}/api/ha/v1/babies/{BABY_ID}/actions/end_sleep"
    start_url = f"{URL}/api/ha/v1/babies/{BABY_ID}/actions/start_nursing"
    aioclient_mock.post(end_url, json=snapshot(sleep={"state": "none"}))
    aioclient_mock.post(start_url, json=snapshot(nursing={"state": "active", "active_side": "right"}))

    assert hass.states.get("switch.olive_sleep_timer").state == "on"
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.olive_sleep_timer"}, blocking=True
    )
    assert hass.states.get("switch.olive_sleep_timer").state == "off"

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.olive_breastfeed_right"}, blocking=True
    )
    start = next(call for call in aioclient_mock.mock_calls if str(call[1]) == start_url)
    assert start[2] == {"side": "right"}
    assert hass.states.get("switch.olive_breastfeed_right").state == "on"
    assert hass.states.get("switch.olive_breastfeed_left").state == "off"


async def test_refreshes_an_expired_token_and_saves_it(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    aioclient_mock.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=refresh_token",
        json={
            "access_token": "access-2",
            "refresh_token": "refresh-2",
            "expires_in": 3600,
            "user": {"id": "user-1"},
        },
    )
    entry = await setup(hass, aioclient_mock, make_entry(expires_at=time.time() - 10))
    assert entry.state is ConfigEntryState.LOADED
    assert entry.data[CONF_ACCESS_TOKEN] == "access-2"
    assert entry.data[CONF_REFRESH_TOKEN] == "refresh-2"


async def test_asks_to_sign_in_again_when_signed_out(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    aioclient_mock.get(f"{URL}/api/ha/v1/babies", status=401, json={"error": "Sign in"})
    aioclient_mock.post(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=refresh_token",
        status=400,
        json={"error_description": "Invalid Refresh Token"},
    )
    entry = make_entry()
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]
