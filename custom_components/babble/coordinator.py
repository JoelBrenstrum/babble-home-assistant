from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BabbleAuthError, BabbleClient, BabbleError
from .const import DOMAIN, TICK_INTERVAL, UPDATE_INTERVAL
from .model import Snapshot

_LOGGER = logging.getLogger(__name__)

type BabbleConfigEntry = ConfigEntry[BabbleCoordinator]


class BabbleCoordinator(DataUpdateCoordinator[dict[str, Snapshot]]):
    config_entry: BabbleConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: BabbleConfigEntry,
        client: BabbleClient,
        babies: list[dict[str, Any]],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.client = client
        self.babies = babies

    async def _async_update_data(self) -> dict[str, Snapshot]:
        try:
            states = await asyncio.gather(*(self.client.state(baby["id"]) for baby in self.babies))
        except BabbleAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except BabbleError as err:
            raise UpdateFailed(str(err)) from err
        return {baby["id"]: state for baby, state in zip(self.babies, states, strict=True)}

    async def async_action(self, baby_id: str, name: str, data: dict[str, Any] | None = None) -> None:
        try:
            state = await self.client.action(baby_id, name, data)
        except BabbleAuthError as err:
            self.config_entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                "babble signed Home Assistant out. Sign in again from Devices & services."
            ) from err
        except BabbleError as err:
            raise HomeAssistantError(str(err)) from err
        self.async_set_updated_data({**(self.data or {}), baby_id: state})

    @callback
    def async_start_ticking(self) -> None:
        @callback
        def tick(_now: Any) -> None:
            self.async_update_listeners()

        self.config_entry.async_on_unload(async_track_time_interval(self.hass, tick, TICK_INTERVAL))
