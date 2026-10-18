from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import BabbleAuthError, BabbleClient, BabbleError, Tokens, token_data
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ANON_KEY,
    CONF_EXPIRES_AT,
    CONF_REFRESH_TOKEN,
    CONF_SUPABASE_URL,
    CONF_URL,
    DOMAIN,
)
from .coordinator import BabbleConfigEntry, BabbleCoordinator
from .services import async_setup_services

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: BabbleConfigEntry) -> bool:
    def save_tokens(tokens: Tokens) -> None:
        hass.config_entries.async_update_entry(entry, data={**entry.data, **token_data(tokens)})

    client = BabbleClient(
        async_get_clientsession(hass),
        entry.data[CONF_URL],
        entry.data[CONF_SUPABASE_URL],
        entry.data[CONF_ANON_KEY],
        Tokens(
            access_token=entry.data[CONF_ACCESS_TOKEN],
            refresh_token=entry.data[CONF_REFRESH_TOKEN],
            expires_at=entry.data[CONF_EXPIRES_AT],
            user_id=entry.unique_id or "",
            email=None,
        ),
        save_tokens,
    )
    try:
        babies = await client.babies()
    except BabbleAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except BabbleError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = BabbleCoordinator(hass, entry, client, babies)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    devices = dr.async_get(hass)
    current = {(DOMAIN, baby["id"]) for baby in babies}
    for device in dr.async_entries_for_config_entry(devices, entry.entry_id):
        if not device.identifiers & current:
            devices.async_update_device(device.id, remove_config_entry_id=entry.entry_id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.async_start_ticking()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BabbleConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
