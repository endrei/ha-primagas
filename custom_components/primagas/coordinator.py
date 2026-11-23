"""Data update coordinator for PRIMAGAS."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import PrimagasAuthError, PrimagasClient, PrimagasError, Tank
from .const import CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS, DOMAIN

_LOGGER = logging.getLogger(__name__)


class PrimagasCoordinator(DataUpdateCoordinator[dict[str, Tank]]):
    """Polls the customer portal every few hours."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: PrimagasClient
    ) -> None:
        hours = entry.options.get(CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(hours=hours),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Tank]:
        try:
            return await self.client.async_get_tanks()
        except PrimagasAuthError as err:
            raise ConfigEntryAuthFailed("PRIMAGAS login rejected") from err
        except PrimagasError as err:
            raise UpdateFailed(f"PRIMAGAS not reachable: {err}") from err
