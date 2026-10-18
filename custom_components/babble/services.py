from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .const import DOMAIN

ATTR_DEVICE_ID = "device_id"

SIDES = vol.In(["left", "right"])
SIZES = vol.In(["tiny", "little", "medium", "large", "massive"])
COLOURS = vol.In(
    ["yellow", "mustard", "green", "dark_green", "brown", "orange", "black", "red", "white_grey"]
)
TEXTURES = vol.In(["runny", "loose", "seedy", "pasty", "formed", "mucousy", "solid", "pebbles", "diarrhea"])
AMOUNT = vol.All(vol.Coerce(float), vol.Range(min=0))

STARTED = {vol.Optional("started_at"): cv.datetime}
ENDED = {vol.Optional("ended_at"): cv.datetime}

SERVICES: dict[str, dict[Any, Any]] = {
    "start_sleep": STARTED,
    "pause_sleep": {},
    "resume_sleep": {},
    "end_sleep": ENDED,
    "cancel_sleep": {},
    "start_nursing": {vol.Optional("side", default="left"): SIDES, **STARTED},
    "pause_nursing": {},
    "resume_nursing": {vol.Optional("side"): SIDES},
    "switch_nursing_side": {},
    "end_nursing": ENDED,
    "cancel_nursing": {},
    "log_bottle": {
        vol.Required("amount_ml"): AMOUNT,
        vol.Optional("content"): vol.In(["breast_milk", "formula", "mixed", "other"]),
        vol.Optional("left_over_ml"): AMOUNT,
        **STARTED,
    },
    "log_nappy": {
        vol.Optional("wet"): cv.boolean,
        vol.Optional("dirty"): cv.boolean,
        vol.Optional("wet_size"): SIZES,
        vol.Optional("poo_size"): SIZES,
        vol.Optional("colours"): vol.All(cv.ensure_list, [COLOURS]),
        vol.Optional("textures"): vol.All(cv.ensure_list, [TEXTURES]),
        vol.Optional("rash"): cv.boolean,
        vol.Optional("notes"): cv.string,
        **STARTED,
    },
    "log_solids": {
        vol.Required("foods"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("amount"): vol.In(["taste", "some", "lots"]),
        vol.Optional("reaction"): vol.In(["loved", "liked", "unsure", "disliked"]),
        vol.Optional("notes"): cv.string,
        **STARTED,
    },
    "log_pump": {
        vol.Optional("left_ml"): AMOUNT,
        vol.Optional("right_ml"): AMOUNT,
        vol.Optional("total_ml"): AMOUNT,
        vol.Optional("duration_min"): AMOUNT,
        **ENDED,
    },
    "log_growth": {
        vol.Optional("weight_kg"): AMOUNT,
        vol.Optional("length_cm"): AMOUNT,
        vol.Optional("head_cm"): AMOUNT,
        **STARTED,
    },
}


def _payload(data: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in data.items():
        if key == ATTR_DEVICE_ID:
            continue
        if isinstance(value, datetime):
            local = value if value.tzinfo else value.replace(tzinfo=dt_util.get_default_time_zone())
            value = dt_util.as_utc(local).isoformat()
        payload[key] = value
    return payload


def _resolve(hass: HomeAssistant, device_id: str):
    device = dr.async_get(hass).async_get(device_id)
    baby_id = next((key for domain, key in device.identifiers if domain == DOMAIN), None) if device else None
    if device is None or baby_id is None:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="invalid_device")
    for entry_id in device.config_entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry and entry.domain == DOMAIN and entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data, baby_id
    raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    async def handle(call: ServiceCall) -> None:
        coordinator, baby_id = _resolve(hass, call.data[ATTR_DEVICE_ID])
        await coordinator.async_action(baby_id, call.service, _payload(dict(call.data)))

    for name, fields in SERVICES.items():
        hass.services.async_register(
            DOMAIN, name, handle, schema=vol.Schema({vol.Required(ATTR_DEVICE_ID): cv.string, **fields})
        )
