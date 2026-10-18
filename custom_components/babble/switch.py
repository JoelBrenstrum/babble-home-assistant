from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import BabbleConfigEntry, BabbleCoordinator
from .entity import BabbleEntity
from .model import is_asleep, nursing_side_active, nursing_turn_on


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BabbleConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SwitchEntity] = []
    for baby in coordinator.babies:
        entities.append(SleepSwitch(coordinator, baby))
        entities.extend(NursingSwitch(coordinator, baby, side) for side in ("left", "right"))
    async_add_entities(entities)


class SleepSwitch(BabbleEntity, SwitchEntity):
    def __init__(self, coordinator: BabbleCoordinator, baby: dict[str, Any]) -> None:
        super().__init__(coordinator, baby, "sleep_timer")

    @property
    def is_on(self) -> bool:
        return is_asleep(self.snapshot)

    async def async_turn_on(self, **kwargs: Any) -> None:
        if not self.is_on:
            await self.coordinator.async_action(self.baby_id, "start_sleep")

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self.is_on:
            await self.coordinator.async_action(self.baby_id, "end_sleep")


class NursingSwitch(BabbleEntity, SwitchEntity):
    def __init__(self, coordinator: BabbleCoordinator, baby: dict[str, Any], side: str) -> None:
        super().__init__(coordinator, baby, f"nursing_{side}")
        self.side = side

    @property
    def is_on(self) -> bool:
        return nursing_side_active(self.snapshot, self.side)

    async def async_turn_on(self, **kwargs: Any) -> None:
        step = nursing_turn_on(self.snapshot, self.side)
        if step:
            await self.coordinator.async_action(self.baby_id, *step)

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self.is_on:
            await self.coordinator.async_action(self.baby_id, "end_nursing")
