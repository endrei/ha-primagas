"""Diagnostics for PRIMAGAS (credentials and personal data are redacted)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import PrimagasConfigEntry
from .const import CONF_CUSTOMER_NUMBER

TO_REDACT = {
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_CUSTOMER_NUMBER,
    "assetId",
    "assetNumber",
    "accountId",
    "deliveryAddressId",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: PrimagasConfigEntry
) -> dict[str, Any]:
    tanks = entry.runtime_data.data or {}
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "update_status": asdict(entry.runtime_data.update_status),
        "tanks": [async_redact_data(t.raw, TO_REDACT) for t in tanks.values()],
    }
