from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BabbleCoordinator
from .model import Snapshot


class BabbleEntity(CoordinatorEntity[BabbleCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: BabbleCoordinator, baby: dict[str, Any], key: str) -> None:
        super().__init__(coordinator)
        self.baby_id: str = baby["id"]
        self._attr_unique_id = f"{self.baby_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.baby_id)},
            name=baby["name"],
            manufacturer="babble",
            model=baby.get("family_name") or None,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=coordinator.client.url,
        )

    @property
    def snapshot(self) -> Snapshot:
        return self.coordinator.data[self.baby_id]

    @property
    def available(self) -> bool:
        return super().available and self.baby_id in (self.coordinator.data or {})
