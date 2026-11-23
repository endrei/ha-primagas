"""Data update coordinator for PRIMAGAS."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    PrimagasApiError,
    PrimagasAuthError,
    PrimagasClient,
    PrimagasConnectionError,
    PrimagasCustomerNumberError,
    PrimagasPortalError,
    Tank,
)
from .const import CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Values of the "Status" diagnostic sensor
STATUS_OK = "ok"
STATUS_AUTH_FAILED = "auth_failed"
STATUS_PORTAL_ERROR = "portal_error"
STATUS_API_UNAVAILABLE = "api_unavailable"
STATUS_API_ERROR = "api_error"
STATUS_CONNECTION_ERROR = "connection_error"
STATUS_NO_TANKS = "no_tanks"
STATUS_INTEGRATION_ERROR = "integration_error"
STATUS_OPTIONS = [
    STATUS_OK,
    STATUS_AUTH_FAILED,
    STATUS_PORTAL_ERROR,
    STATUS_API_UNAVAILABLE,
    STATUS_API_ERROR,
    STATUS_CONNECTION_ERROR,
    STATUS_NO_TANKS,
    STATUS_INTEGRATION_ERROR,
]


@dataclass
class UpdateStatus:
    """Outcome of the latest poll, for troubleshooting."""

    status: str = STATUS_OK
    error: str | None = None
    http_status: int | None = None
    last_attempt: datetime | None = None
    last_success: datetime | None = None
    consecutive_failures: int = 0


def classify(err: Exception) -> tuple[str, int | None]:
    """Map an exception to a status value and an optional HTTP status."""
    if isinstance(err, PrimagasAuthError):
        return STATUS_AUTH_FAILED, None
    if isinstance(err, PrimagasApiError):
        if err.status >= 500 or err.status == 429:
            return STATUS_API_UNAVAILABLE, err.status
        return STATUS_API_ERROR, err.status
    if isinstance(err, PrimagasCustomerNumberError):
        return STATUS_API_ERROR, None
    if isinstance(err, PrimagasPortalError):
        return STATUS_PORTAL_ERROR, None
    if isinstance(err, PrimagasConnectionError):
        return STATUS_CONNECTION_ERROR, None
    return STATUS_INTEGRATION_ERROR, None


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
        self.update_status = UpdateStatus()

    async def _async_update_data(self) -> dict[str, Tank]:
        status = self.update_status
        status.last_attempt = dt_util.utcnow()
        try:
            tanks = await self.client.async_get_tanks()
        except Exception as err:
            status.status, status.http_status = classify(err)
            status.error = str(err) or type(err).__name__
            status.consecutive_failures += 1
            if not self.last_update_success:
                # HA does not notify entities about repeated failures,
                # so push the new status to the diagnostic sensors here.
                self.async_update_listeners()
            if status.status == STATUS_AUTH_FAILED:
                raise ConfigEntryAuthFailed("PRIMAGAS login rejected") from err
            if status.status == STATUS_INTEGRATION_ERROR:
                _LOGGER.exception("Unexpected error in the PRIMAGAS integration")
            raise UpdateFailed(f"PRIMAGAS update failed: {status.error}") from err

        status.consecutive_failures = 0
        status.http_status = None
        status.last_success = status.last_attempt
        if tanks:
            status.status, status.error = STATUS_OK, None
        else:
            status.status, status.error = STATUS_NO_TANKS, "No tanks in the account"
        return tanks
