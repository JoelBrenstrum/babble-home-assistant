from __future__ import annotations

import copy
from typing import Any

import pytest

URL = "https://babble.example"
SUPABASE_URL = "https://db.babble.example"
BABY_ID = "baby-1"

SNAPSHOT: dict[str, Any] = {
    "as_of": "2026-10-06T12:00:00.000Z",
    "baby": {
        "id": BABY_ID,
        "name": "Olive",
        "birth_date": "2026-09-01",
        "sex": "female",
        "age": "5w",
        "timezone": "Pacific/Auckland",
        "units": "metric",
    },
    "sleep": {
        "state": "active",
        "started_at": "2026-10-06T11:00:00Z",
        "asleep_s": 3600,
        "awake_s": 0,
        "wake_ups": 0,
        "awake_since": None,
        "previous": {
            "started_at": "2026-10-06T08:00:00Z",
            "ended_at": "2026-10-06T09:00:00Z",
            "asleep_s": 3600,
        },
    },
    "nursing": {
        "state": "none",
        "started_at": None,
        "left_s": 0,
        "right_s": 0,
        "active_side": None,
        "last_side": None,
        "next_side": "left",
        "previous": {
            "started_at": "2026-10-06T10:00:00Z",
            "ended_at": "2026-10-06T10:25:00Z",
            "left_s": 600,
            "right_s": 900,
            "last_side": "right",
        },
    },
    "pumping": {"state": "none", "started_at": None, "previous": None},
    "feed": {
        "last": {
            "type": "breast_feed",
            "started_at": "2026-10-06T10:00:00Z",
            "ended_at": "2026-10-06T10:25:00Z",
        },
        "next_due": "2026-10-06T13:00:00.000Z",
        "interval_min": 180,
        "quiet": False,
        "suppressed": None,
    },
    "bottle": {"started_at": "2026-10-06T07:00:00Z", "content": "formula", "amount_ml": 120, "drunk_ml": 100},
    "solids": None,
    "nappy": {
        "started_at": "2026-10-06T09:30:00Z",
        "wet": True,
        "dirty": True,
        "wet_size": None,
        "poo_size": "medium",
        "colours": ["yellow"],
        "textures": ["seedy"],
        "rash": False,
    },
    "growth": {
        "started_at": "2026-10-01T09:00:00Z",
        "weight_kg": 4.2,
        "length_cm": 54,
        "head_cm": None,
        "weight_percentile": 48.3,
        "length_percentile": 51.2,
        "head_percentile": None,
    },
    "today": {
        "day_started_at": "2026-10-05T11:00:00.000Z",
        "sleep_s": 7200,
        "night_sleep_s": 0,
        "nap_sleep_s": 7200,
        "naps": 2,
        "longest_sleep_s": 3600,
        "feeds": 2,
        "breast_feed_s": 1500,
        "bottles": 1,
        "bottle_ml": 100,
        "nappies": 1,
        "wet_nappies": 1,
        "dirty_nappies": 1,
        "solids": 0,
        "pumps": 0,
        "pump_ml": 0,
    },
    "predictions": None,
}


def snapshot(**sections: Any) -> dict[str, Any]:
    result = copy.deepcopy(SNAPSHOT)
    for key, value in sections.items():
        result[key] = value if not isinstance(value, dict) else {**(result[key] or {}), **value}
    return result


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    return None
