from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfLength, UnitOfMass, UnitOfTime, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import BabbleConfigEntry
from .entity import BabbleEntity
from .model import (
    Snapshot,
    current_sleep_seconds,
    minutes,
    nappy_type,
    nursing_side_seconds,
    parse_time,
)

TIMER_STATES = ["active", "paused", "none"]


@dataclass(frozen=True, kw_only=True)
class BabbleSensorDescription(SensorEntityDescription):
    value_fn: Callable[[Snapshot, datetime], Any]
    attrs_fn: Callable[[Snapshot, datetime], dict[str, Any]] | None = None
    available_fn: Callable[[Snapshot], bool] = lambda snapshot: True


def _previous(section: dict[str, Any], keys: dict[str, str]) -> dict[str, Any]:
    previous = section.get("previous") or {}
    return {f"previous_{name}": previous.get(key) for name, key in keys.items()}


def _sleep_attrs(snapshot: Snapshot, now: datetime) -> dict[str, Any]:
    sleep = snapshot["sleep"]
    return {
        "started_at": sleep["started_at"],
        "asleep_minutes": minutes(current_sleep_seconds(snapshot, now)),
        "awake_minutes": minutes(sleep["awake_s"]),
        "wake_ups": sleep["wake_ups"],
        **_previous(sleep, {"started_at": "started_at", "ended_at": "ended_at"}),
        "previous_asleep_minutes": minutes((sleep.get("previous") or {}).get("asleep_s")),
    }


def _nursing_attrs(snapshot: Snapshot, now: datetime) -> dict[str, Any]:
    nursing = snapshot["nursing"]
    previous = nursing.get("previous") or {}
    return {
        "started_at": nursing["started_at"],
        "left_minutes": minutes(nursing_side_seconds(snapshot, now, "left")),
        "right_minutes": minutes(nursing_side_seconds(snapshot, now, "right")),
        "active_side": nursing["active_side"],
        "last_side": nursing["last_side"],
        "next_side": nursing["next_side"],
        "previous_started_at": previous.get("started_at"),
        "previous_ended_at": previous.get("ended_at"),
        "previous_left_minutes": minutes(previous.get("left_s")),
        "previous_right_minutes": minutes(previous.get("right_s")),
        "previous_last_side": previous.get("last_side"),
    }


def _pumping_attrs(snapshot: Snapshot, _now: datetime) -> dict[str, Any]:
    pumping = snapshot["pumping"]
    previous = pumping.get("previous") or {}
    return {
        "started_at": pumping["started_at"],
        "previous_started_at": previous.get("started_at"),
        "previous_duration_minutes": minutes(previous.get("duration_s")),
        "previous_left_ml": previous.get("left_ml"),
        "previous_right_ml": previous.get("right_ml"),
        "previous_total_ml": previous.get("total_ml"),
    }


def _section_time(section: str) -> Callable[[Snapshot, datetime], datetime | None]:
    return lambda snapshot, _now: parse_time((snapshot[section] or {}).get("started_at"))


def _section_attrs(section: str, transform: Callable[[dict[str, Any]], dict[str, Any]] | None = None):
    def attrs(snapshot: Snapshot, _now: datetime) -> dict[str, Any]:
        value = snapshot[section]
        if not value:
            return {}
        fields = {key: item for key, item in value.items() if key != "started_at"}
        return transform(value) | fields if transform else fields

    return attrs


def _growth(key: str) -> Callable[[Snapshot, datetime], Any]:
    return lambda snapshot, _now: (snapshot["growth"] or {}).get(key)


def _today(key: str, scale: float = 1) -> Callable[[Snapshot, datetime], Any]:
    return lambda snapshot, _now: (
        round(snapshot["today"][key] / scale) if scale != 1 else snapshot["today"][key]
    )


def _prediction(key: str) -> Callable[[Snapshot, datetime], datetime | None]:
    return lambda snapshot, _now: parse_time((snapshot["predictions"] or {}).get(key))


def _feed_due_attrs(snapshot: Snapshot, now: datetime) -> dict[str, Any]:
    feed = snapshot["feed"]
    due = parse_time(feed["next_due"])
    return {
        "interval_minutes": feed["interval_min"],
        "quiet": feed["quiet"],
        "suppressed": feed["suppressed"],
        "overdue": due is not None and now >= due,
        "next_side": snapshot["nursing"]["next_side"],
    }


SENSORS: tuple[BabbleSensorDescription, ...] = (
    BabbleSensorDescription(
        key="profile",
        value_fn=lambda snapshot, _now: snapshot["baby"]["name"],
        attrs_fn=lambda snapshot, _now: {
            key: value for key, value in snapshot["baby"].items() if key != "id"
        },
    ),
    BabbleSensorDescription(
        key="sleep",
        device_class=SensorDeviceClass.ENUM,
        options=TIMER_STATES,
        value_fn=lambda snapshot, _now: snapshot["sleep"]["state"],
        attrs_fn=_sleep_attrs,
    ),
    BabbleSensorDescription(
        key="current_sleep",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda snapshot, now: minutes(current_sleep_seconds(snapshot, now)),
        attrs_fn=lambda snapshot, _now: {
            "started_at": snapshot["sleep"]["started_at"],
            "paused": snapshot["sleep"]["state"] == "paused",
            "wake_ups": snapshot["sleep"]["wake_ups"],
        },
    ),
    BabbleSensorDescription(
        key="awake_since",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda snapshot, _now: parse_time(snapshot["sleep"]["awake_since"]),
    ),
    BabbleSensorDescription(
        key="nursing",
        device_class=SensorDeviceClass.ENUM,
        options=TIMER_STATES,
        value_fn=lambda snapshot, _now: snapshot["nursing"]["state"],
        attrs_fn=_nursing_attrs,
    ),
    BabbleSensorDescription(
        key="next_breast_side",
        device_class=SensorDeviceClass.ENUM,
        options=["left", "right"],
        value_fn=lambda snapshot, _now: snapshot["nursing"]["next_side"],
    ),
    BabbleSensorDescription(
        key="last_feed",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda snapshot, _now: parse_time((snapshot["feed"]["last"] or {}).get("started_at")),
        attrs_fn=lambda snapshot, _now: {
            "type": (snapshot["feed"]["last"] or {}).get("type"),
            "ended_at": (snapshot["feed"]["last"] or {}).get("ended_at"),
        },
    ),
    BabbleSensorDescription(
        key="next_feed_due",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda snapshot, _now: parse_time(snapshot["feed"]["next_due"]),
        attrs_fn=_feed_due_attrs,
    ),
    BabbleSensorDescription(
        key="bottle",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_section_time("bottle"),
        attrs_fn=_section_attrs("bottle"),
    ),
    BabbleSensorDescription(
        key="solids",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_section_time("solids"),
        attrs_fn=_section_attrs("solids"),
    ),
    BabbleSensorDescription(
        key="nappy",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_section_time("nappy"),
        attrs_fn=_section_attrs("nappy", lambda nappy: {"type": nappy_type(nappy)}),
    ),
    BabbleSensorDescription(
        key="pumping",
        device_class=SensorDeviceClass.ENUM,
        options=TIMER_STATES,
        value_fn=lambda snapshot, _now: snapshot["pumping"]["state"],
        attrs_fn=_pumping_attrs,
    ),
    BabbleSensorDescription(
        key="growth",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_section_time("growth"),
        attrs_fn=_section_attrs("growth"),
    ),
    BabbleSensorDescription(
        key="weight",
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        suggested_display_precision=2,
        value_fn=_growth("weight_kg"),
        attrs_fn=lambda snapshot, _now: {"percentile": (snapshot["growth"] or {}).get("weight_percentile")},
    ),
    BabbleSensorDescription(
        key="length",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.CENTIMETERS,
        suggested_display_precision=1,
        value_fn=_growth("length_cm"),
        attrs_fn=lambda snapshot, _now: {"percentile": (snapshot["growth"] or {}).get("length_percentile")},
    ),
    BabbleSensorDescription(
        key="head",
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfLength.CENTIMETERS,
        suggested_display_precision=1,
        value_fn=_growth("head_cm"),
        attrs_fn=lambda snapshot, _now: {"percentile": (snapshot["growth"] or {}).get("head_percentile")},
    ),
    BabbleSensorDescription(
        key="sleep_today",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=_today("sleep_s", 60),
        attrs_fn=lambda snapshot, _now: {
            "day_started_at": snapshot["today"]["day_started_at"],
            "night_minutes": round(snapshot["today"]["night_sleep_s"] / 60),
            "nap_minutes": round(snapshot["today"]["nap_sleep_s"] / 60),
            "longest_minutes": round(snapshot["today"]["longest_sleep_s"] / 60),
        },
    ),
    BabbleSensorDescription(
        key="naps_today",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_today("naps"),
    ),
    BabbleSensorDescription(
        key="feeds_today",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_today("feeds"),
        attrs_fn=lambda snapshot, _now: {
            "breastfeed_minutes": round(snapshot["today"]["breast_feed_s"] / 60),
            "bottles": snapshot["today"]["bottles"],
            "solids": snapshot["today"]["solids"],
        },
    ),
    BabbleSensorDescription(
        key="bottle_today",
        device_class=SensorDeviceClass.VOLUME,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfVolume.MILLILITERS,
        value_fn=_today("bottle_ml"),
    ),
    BabbleSensorDescription(
        key="wet_nappies_today",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_today("wet_nappies"),
    ),
    BabbleSensorDescription(
        key="dirty_nappies_today",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_today("dirty_nappies"),
    ),
    BabbleSensorDescription(
        key="predicted_next_sleep",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_prediction("next_sleep_at"),
        attrs_fn=lambda snapshot, _now: {
            "likely_awake_at": (snapshot["predictions"] or {}).get("likely_awake_at")
        },
        available_fn=lambda snapshot: snapshot["predictions"] is not None,
    ),
    BabbleSensorDescription(
        key="predicted_next_feed",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_prediction("next_feed_at"),
        available_fn=lambda snapshot: snapshot["predictions"] is not None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BabbleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        BabbleSensor(coordinator, baby, description) for baby in coordinator.babies for description in SENSORS
    )


class BabbleSensor(BabbleEntity, SensorEntity):
    entity_description: BabbleSensorDescription

    def __init__(self, coordinator, baby: dict[str, Any], description: BabbleSensorDescription) -> None:
        super().__init__(coordinator, baby, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        return super().available and self.entity_description.available_fn(self.snapshot)

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.snapshot, dt_util.utcnow())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.snapshot, dt_util.utcnow())
