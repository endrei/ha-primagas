"""The PRIMAGAS integration: tank level from kunden.primagas.de."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant

from .api import PrimagasClient, create_session
from .const import CONF_CUSTOMER_NUMBER
from .coordinator import PrimagasCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type PrimagasConfigEntry = ConfigEntry[PrimagasCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: PrimagasConfigEntry) -> bool:
    """Set up PRIMAGAS from a config entry."""
    # Own session so the login cookies never mix with other integrations.
    session = create_session()
    entry.async_on_unload(session.close)
    client = PrimagasClient(
        session,
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        entry.data[CONF_CUSTOMER_NUMBER],
    )
    coordinator = PrimagasCoordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await session.close()
        raise
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: PrimagasConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: PrimagasConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
