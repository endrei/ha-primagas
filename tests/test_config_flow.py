"""Config flow and setup tests."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.primagas.api import PrimagasAuthError, Tank
from custom_components.primagas.const import CONF_CUSTOMER_NUMBER, DOMAIN

from .test_api import ASSET

INPUT = {
    CONF_USERNAME: " kunde@example.org ",
    CONF_PASSWORD: "pw",
    CONF_CUSTOMER_NUMBER: "1234567",
}
VALIDATE = "custom_components.primagas.config_flow.PrimagasClient.async_validate"
GET_TANKS = "custom_components.primagas.api.PrimagasClient.async_get_tanks"


async def test_user_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    with patch(VALIDATE, side_effect=PrimagasAuthError):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], dict(INPUT)
        )
    assert result["errors"] == {"base": "invalid_auth"}

    tanks = {ASSET["assetId"]: Tank(ASSET["assetId"], ASSET["assetId"], ASSET)}
    with patch(VALIDATE), patch(GET_TANKS, return_value=tanks):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], dict(INPUT)
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_USERNAME] == "kunde@example.org"
    assert result["result"].unique_id == "1234567"

    state = hass.states.get("sensor.tank_fill_level")
    assert state is not None, [s.entity_id for s in hass.states.async_all()]
    assert state.state == "61"
    assert hass.states.get("sensor.tank_stock_left").state == "210"


async def test_auth_failure_starts_reauth(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="1234567",
        data={
            CONF_USERNAME: "kunde@example.org",
            CONF_PASSWORD: "alt",
            CONF_CUSTOMER_NUMBER: "1234567",
        },
    )
    entry.add_to_hass(hass)
    with patch(GET_TANKS, side_effect=PrimagasAuthError):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == ["reauth"]


async def test_failed_attempt_does_not_block_new_flow(hass: HomeAssistant) -> None:
    first = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(VALIDATE, side_effect=PrimagasAuthError):
        await hass.config_entries.flow.async_configure(first["flow_id"], dict(INPUT))
    second = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(VALIDATE, side_effect=PrimagasAuthError):
        result = await hass.config_entries.flow.async_configure(
            second["flow_id"], dict(INPUT)
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_status_sensor(hass: HomeAssistant) -> None:
    from custom_components.primagas.api import PrimagasApiError, PrimagasPortalError

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="1234567",
        data={
            CONF_USERNAME: "kunde@example.org",
            CONF_PASSWORD: "pw",
            CONF_CUSTOMER_NUMBER: "1234567",
        },
    )
    entry.add_to_hass(hass)
    tanks = {ASSET["assetId"]: Tank(ASSET["assetId"], ASSET["assetId"], ASSET)}
    with patch(GET_TANKS, return_value=tanks):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    status = hass.states.get("sensor.tank_status")
    assert status.state == "ok"
    assert status.attributes["consecutive_failures"] == 0
    assert hass.states.get("sensor.tank_last_successful_update").state != "unavailable"

    coordinator = entry.runtime_data
    with patch(GET_TANKS, side_effect=PrimagasPortalError("login page changed")):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    status = hass.states.get("sensor.tank_status")
    assert status.state == "portal_error"
    assert status.attributes["error"] == "login page changed"
    assert status.attributes["consecutive_failures"] == 1
    assert hass.states.get("sensor.tank_fill_level").state == "unavailable"
    assert hass.states.get("sensor.tank_last_successful_update").state != "unavailable"

    with patch(GET_TANKS, side_effect=PrimagasApiError("API answered 503", 503)):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    status = hass.states.get("sensor.tank_status")
    assert status.state == "api_unavailable"
    assert status.attributes["http_status"] == 503
    assert status.attributes["consecutive_failures"] == 2

    with patch(GET_TANKS, return_value=tanks):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    assert hass.states.get("sensor.tank_status").state == "ok"
    assert hass.states.get("sensor.tank_fill_level").state == "61"


async def test_refresh_button(hass: HomeAssistant) -> None:
    import pytest
    from homeassistant.exceptions import HomeAssistantError

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="1234567",
        data={
            CONF_USERNAME: "kunde@example.org",
            CONF_PASSWORD: "pw",
            CONF_CUSTOMER_NUMBER: "1234567",
        },
    )
    entry.add_to_hass(hass)
    tanks = {ASSET["assetId"]: Tank(ASSET["assetId"], ASSET["assetId"], ASSET)}
    with patch(GET_TANKS, return_value=tanks) as get_tanks:
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert hass.states.get("button.tank_refresh_now") is not None
        assert get_tanks.call_count == 1

        # Right after setup the button refuses, to protect the portal.
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(
                "button",
                "press",
                {"entity_id": "button.tank_refresh_now"},
                blocking=True,
            )
        assert get_tanks.call_count == 1

        entry.runtime_data.update_status.last_attempt = None
        await hass.services.async_call(
            "button", "press", {"entity_id": "button.tank_refresh_now"}, blocking=True
        )
        assert get_tanks.call_count == 2


async def test_removed_sensors_are_cleaned_up(hass: HomeAssistant) -> None:
    from homeassistant.helpers import entity_registry as er

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="1234567",
        data={
            CONF_USERNAME: "kunde@example.org",
            CONF_PASSWORD: "pw",
            CONF_CUSTOMER_NUMBER: "1234567",
        },
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "sensor", DOMAIN, f"{ASSET['assetId']}_estimated_level", config_entry=entry
    )
    tanks = {ASSET["assetId"]: Tank(ASSET["assetId"], ASSET["assetId"], ASSET)}
    with patch(GET_TANKS, return_value=tanks):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert registry.async_get(old.entity_id) is None
    assert hass.states.get("sensor.tank_fill_level").state == "61"
