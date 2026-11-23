"""Sensors for PRIMAGAS tanks."""

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
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTime, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import PrimagasConfigEntry
from .api import Tank
from .const import DOMAIN
from .coordinator import STATUS_OPTIONS, PrimagasCoordinator
from .entity import tank_device_info


def _ts(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = dt_util.parse_datetime(str(value))
    if parsed and parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt_util.UTC)
    return parsed


@dataclass(frozen=True, kw_only=True)
class PrimagasSensorDescription(SensorEntityDescription):
    value_fn: Callable[[Tank], Any]


SENSORS: tuple[PrimagasSensorDescription, ...] = (
    PrimagasSensorDescription(
        key="level",
        translation_key="level",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: t.raw.get("assetCurrentLevelPercentage"),
    ),
    PrimagasSensorDescription(
        key="volume",
        translation_key="volume",
        device_class=SensorDeviceClass.VOLUME_STORAGE,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda t: t.raw.get("assetCurrentFillingVolume"),
    ),
    PrimagasSensorDescription(
        key="stock_left",
        translation_key="stock_left",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.DAYS,
        value_fn=lambda t: t.forecast.get("stockLeftInDays"),
    ),
    PrimagasSensorDescription(
        key="runout_date",
        translation_key="runout_date",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda t: _ts(t.forecast.get("predictedRunoutDate")),
    ),
    PrimagasSensorDescription(
        key="replenishment_order_date",
        translation_key="replenishment_order_date",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda t: _ts(t.forecast.get("predictedReplenishmentOrderDate")),
    ),
    PrimagasSensorDescription(
        key="forecast_time",
        translation_key="forecast_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t: _ts(t.forecast.get("forecastDateTime")),
    ),
    PrimagasSensorDescription(
        key="capacity",
        translation_key="capacity",
        device_class=SensorDeviceClass.VOLUME_STORAGE,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t: t.raw.get("assetCapacity"),
    ),
    PrimagasSensorDescription(
        key="max_volume",
        translation_key="max_volume",
        device_class=SensorDeviceClass.VOLUME_STORAGE,
        native_unit_of_measurement=UnitOfVolume.LITERS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda t: t.raw.get("assetMaximumFillingVolume"),
    ),
)


# Sensors that existed in earlier versions and are removed from the registry.
REMOVED_KEYS = ("estimated_level", "replenishment_volume")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PrimagasConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    registry = er.async_get(hass)
    for asset_id in coordinator.data:
        for key in REMOVED_KEYS:
            if entity_id := registry.async_get_entity_id(
                "sensor", DOMAIN, f"{asset_id}_{key}"
            ):
                registry.async_remove(entity_id)
    async_add_entities(
        PrimagasSensor(coordinator, asset_id, description)
        for asset_id in coordinator.data
        for description in SENSORS
    )
    async_add_entities(
        entity
        for asset_id in coordinator.data
        for entity in (
            PrimagasStatusSensor(coordinator, asset_id, STATUS_DESCRIPTION),
            PrimagasLastSuccessSensor(coordinator, asset_id, LAST_SUCCESS_DESCRIPTION),
        )
    )


STATUS_DESCRIPTION = PrimagasSensorDescription(
    key="status",
    translation_key="status",
    device_class=SensorDeviceClass.ENUM,
    options=STATUS_OPTIONS,
    entity_category=EntityCategory.DIAGNOSTIC,
    value_fn=lambda t: None,
)

LAST_SUCCESS_DESCRIPTION = PrimagasSensorDescription(
    key="last_success",
    translation_key="last_success",
    device_class=SensorDeviceClass.TIMESTAMP,
    entity_category=EntityCategory.DIAGNOSTIC,
    value_fn=lambda t: None,
)


class PrimagasSensor(CoordinatorEntity[PrimagasCoordinator], SensorEntity):
    """One value of one tank."""

    _attr_has_entity_name = True
    entity_description: PrimagasSensorDescription

    def __init__(
        self,
        coordinator: PrimagasCoordinator,
        asset_id: str,
        description: PrimagasSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._asset_id = asset_id
        self._attr_unique_id = f"{asset_id}_{description.key}"
        self._attr_device_info = tank_device_info(coordinator, asset_id)

    @property
    def available(self) -> bool:
        return super().available and self._asset_id in self.coordinator.data

    @property
    def native_value(self) -> Any:
        tank = self.coordinator.data.get(self._asset_id)
        return self.entity_description.value_fn(tank) if tank else None


class PrimagasStatusSensor(PrimagasSensor):
    """Result of the latest poll. Stays available when the poll fails."""

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> str:
        return self.coordinator.update_status.status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self.coordinator.update_status
        next_update = None
        if status.last_attempt and self.coordinator.update_interval:
            next_update = status.last_attempt + self.coordinator.update_interval
        return {
            "error": status.error,
            "http_status": status.http_status,
            "last_attempt": status.last_attempt,
            "last_success": status.last_success,
            "next_update": next_update,
            "consecutive_failures": status.consecutive_failures,
            "update_interval_hours": (
                self.coordinator.update_interval.total_seconds() / 3600
                if self.coordinator.update_interval
                else None
            ),
        }


class PrimagasLastSuccessSensor(PrimagasSensor):
    """Time of the last successful poll. Stays available when the poll fails."""

    @property
    def available(self) -> bool:
        return self.coordinator.update_status.last_success is not None

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.update_status.last_success
