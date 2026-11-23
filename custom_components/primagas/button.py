"""Button to poll PRIMAGAS outside the regular interval."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import PrimagasConfigEntry
from .const import DOMAIN
from .coordinator import PrimagasCoordinator
from .entity import tank_device_info

# Protects the PRIMAGAS portal from rapid repeated presses.
MIN_TIME_BETWEEN_MANUAL_UPDATES = timedelta(seconds=60)

REFRESH_DESCRIPTION = ButtonEntityDescription(
    key="refresh",
    translation_key="refresh",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PrimagasConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        PrimagasRefreshButton(coordinator, asset_id) for asset_id in coordinator.data
    )


class PrimagasRefreshButton(CoordinatorEntity[PrimagasCoordinator], ButtonEntity):
    """Fetch the tank data now."""

    _attr_has_entity_name = True
    entity_description = REFRESH_DESCRIPTION

    def __init__(self, coordinator: PrimagasCoordinator, asset_id: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{asset_id}_refresh"
        self._attr_device_info = tank_device_info(coordinator, asset_id)

    @property
    def available(self) -> bool:
        # Must stay usable when the last poll failed, that is when it helps most.
        return True

    async def async_press(self) -> None:
        last = self.coordinator.update_status.last_attempt
        if last and dt_util.utcnow() - last < MIN_TIME_BETWEEN_MANUAL_UPDATES:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="refresh_too_soon",
                translation_placeholders={
                    "seconds": str(int(MIN_TIME_BETWEEN_MANUAL_UPDATES.total_seconds()))
                },
            )
        await self.coordinator.async_refresh()
