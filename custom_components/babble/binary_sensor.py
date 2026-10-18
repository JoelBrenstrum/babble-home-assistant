from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import BabbleConfigEntry
from .entity import BabbleEntity
from .model import Snapshot, feed_overdue, is_asleep, is_feeding


@dataclass(frozen=True, kw_only=True)
class BabbleBinarySensorDescription(BinarySensorEntityDescription):
    is_on_fn: Callable[[Snapshot, datetime], bool]
    attrs_fn: Callable[[Snapshot], dict[str, Any]] | None = None


BINARY_SENSORS: tuple[BabbleBinarySensorDescription, ...] = (
    BabbleBinarySensorDescription(
        key="asleep",
        is_on_fn=lambda snapshot, _now: is_asleep(snapshot),
        attrs_fn=lambda snapshot: {
            "paused": snapshot["sleep"]["state"] == "paused",
            "started_at": snapshot["sleep"]["started_at"],
        },
    ),
    BabbleBinarySensorDescription(
        key="feeding",
        device_class=BinarySensorDeviceClass.RUNNING,
        is_on_fn=lambda snapshot, _now: is_feeding(snapshot),
        attrs_fn=lambda snapshot: {
            "paused": snapshot["nursing"]["state"] == "paused",
            "side": snapshot["nursing"]["active_side"],
        },
    ),
    BabbleBinarySensorDescription(
        key="feed_overdue",
        device_class=BinarySensorDeviceClass.PROBLEM,
        is_on_fn=feed_overdue,
        attrs_fn=lambda snapshot: {"due_at": snapshot["feed"]["next_due"]},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BabbleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        BabbleBinarySensor(coordinator, baby, description)
        for baby in coordinator.babies
        for description in BINARY_SENSORS
    )


class BabbleBinarySensor(BabbleEntity, BinarySensorEntity):
    entity_description: BabbleBinarySensorDescription

    def __init__(self, coordinator, baby: dict[str, Any], description: BabbleBinarySensorDescription) -> None:
        super().__init__(coordinator, baby, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return self.entity_description.is_on_fn(self.snapshot, dt_util.utcnow())

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.snapshot)
