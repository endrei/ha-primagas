"""Shared entity helpers for PRIMAGAS."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN
from .coordinator import PrimagasCoordinator


def tank_device_info(coordinator: PrimagasCoordinator, asset_id: str) -> DeviceInfo:
    """Device registry entry for one tank."""
    tank = coordinator.data[asset_id]
    capacity = tank.raw.get("assetCapacity")
    return DeviceInfo(
        identifiers={(DOMAIN, asset_id)},
        manufacturer="PRIMAGAS",
        model=f"Flüssiggastank {capacity} l" if capacity else "Flüssiggastank",
        name=tank.raw.get("assetDescription") or "PRIMAGAS Tank",
        serial_number=tank.raw.get("assetNumber"),
        configuration_url="https://kunden.primagas.de/",
    )
