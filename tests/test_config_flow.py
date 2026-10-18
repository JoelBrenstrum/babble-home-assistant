from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
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

from .conftest import SUPABASE_URL, URL

LINK = {"id": "link-1", "code": "ABCD2345", "secret": "s" * 64, "expiresAt": "soon"}
SESSION = {
    "access_token": "access-1",
    "refresh_token": "refresh-1",
    "expires_at": 1_900_000_000,
    "user": {"id": "user-1", "email": "joel@example.com"},
}


@pytest.fixture(autouse=True)
def fast_polling():
    with (
        patch("custom_components.babble.config_flow.LINK_POLL_SECONDS", 0.01),
        patch("custom_components.babble.async_setup_entry", return_value=True),
    ):
        yield


def mock_server(
    aioclient_mock: AiohttpClientMocker, poll_status: str = "approved", sign_in: bool = True
) -> None:
    aioclient_mock.get(
        f"{URL}/api/ha/v1/config",
        json={
            "public_url": URL,
            "supabase_url": SUPABASE_URL,
            "supabase_anon_key": "anon",
            "device_sign_in": sign_in,
        },
    )
    aioclient_mock.post(f"{URL}/api/device-link", json=LINK)
    poll = (
        {"status": poll_status, "tokenHash": "hash-1"}
        if poll_status == "approved"
        else {"status": poll_status}
    )
    aioclient_mock.post(f"{URL}/api/device-link/poll", json=poll)
    aioclient_mock.post(f"{SUPABASE_URL}/auth/v1/verify", json=SESSION)


async def settle(hass: HomeAssistant, result):
    if result["type"] is FlowResultType.SHOW_PROGRESS:
        await hass.async_block_till_done()
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
    return result


async def start(hass: HomeAssistant, url: str = "babble.example/"):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    return await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_URL: url})


async def test_signs_in_by_approving_a_code(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    mock_server(aioclient_mock, poll_status="pending")
    result = await start(hass)

    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["description_placeholders"] == {"code": "ABCD-2345", "url": f"{URL}/link/ABCD2345"}

    aioclient_mock.clear_requests()
    mock_server(aioclient_mock)
    result = await settle(hass, result)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "joel@example.com"
    assert result["result"].unique_id == "user-1"
    assert result["data"] == {
        CONF_URL: URL,
        CONF_SUPABASE_URL: SUPABASE_URL,
        CONF_ANON_KEY: "anon",
        CONF_ACCESS_TOKEN: "access-1",
        CONF_REFRESH_TOKEN: "refresh-1",
        CONF_EXPIRES_AT: 1_900_000_000,
    }
    verify = next(call for call in aioclient_mock.mock_calls if str(call[1]).endswith("/auth/v1/verify"))
    assert verify[2] == {"type": "magiclink", "token_hash": "hash-1"}
    assert verify[3]["apikey"] == "anon"


async def test_offers_a_new_code_when_one_expires(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    mock_server(aioclient_mock, poll_status="expired")
    result = await settle(hass, await start(hass))
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "retry"

    aioclient_mock.clear_requests()
    mock_server(aioclient_mock)
    result = await settle(hass, await hass.config_entries.flow.async_configure(result["flow_id"], {}))
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_reports_an_unreachable_server(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    aioclient_mock.get(f"{URL}/api/ha/v1/config", status=404)
    result = await start(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_needs_device_sign_in_on_the_server(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    mock_server(aioclient_mock, sign_in=False)
    result = await start(hass)
    assert result["errors"] == {"base": "no_device_sign_in"}


async def test_refuses_the_same_account_twice(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker):
    MockConfigEntry(domain=DOMAIN, unique_id="user-1", data={}).add_to_hass(hass)
    mock_server(aioclient_mock)
    result = await settle(hass, await start(hass))
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_signs_in_again_after_being_signed_out(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="user-1",
        data={
            CONF_URL: URL,
            CONF_SUPABASE_URL: SUPABASE_URL,
            CONF_ANON_KEY: "anon",
            CONF_ACCESS_TOKEN: "old",
            CONF_REFRESH_TOKEN: "old",
            CONF_EXPIRES_AT: 0,
        },
    )
    entry.add_to_hass(hass)
    mock_server(aioclient_mock)

    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await settle(hass, await hass.config_entries.flow.async_configure(result["flow_id"], {}))

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_REFRESH_TOKEN] == "refresh-1"
