"""Config flow for PRIMAGAS."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    PrimagasApiError,
    PrimagasAuthError,
    PrimagasClient,
    PrimagasConnectionError,
    PrimagasCustomerNumberError,
    create_session,
)
from .const import (
    CONF_CUSTOMER_NUMBER,
    CONF_SCAN_INTERVAL_HOURS,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
    MAX_SCAN_INTERVAL_HOURS,
    MIN_SCAN_INTERVAL_HOURS,
)

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        ),
        vol.Optional(CONF_CUSTOMER_NUMBER): TextSelector(),
    }
)

REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        ),
    }
)


class PrimagasConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for PRIMAGAS."""

    VERSION = 1

    async def _async_validate(self, data: dict[str, Any]) -> dict[str, str]:
        """Test the login. Fills in the customer number if it was empty."""
        session = create_session()
        client = PrimagasClient(
            session,
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
            data.get(CONF_CUSTOMER_NUMBER, ""),
        )
        try:
            await client.async_validate()
            data[CONF_CUSTOMER_NUMBER] = client.customer_number
        except PrimagasCustomerNumberError:
            return {"base": "customer_number_required"}
        except PrimagasAuthError as err:
            _LOGGER.warning("PRIMAGAS setup: sign-in rejected: %s", err)
            return {"base": "invalid_auth"}
        except PrimagasApiError as err:
            _LOGGER.warning(
                "PRIMAGAS setup: signed in, but data request failed: %s", err
            )
            return {"base": "api_error"}
        except PrimagasConnectionError as err:
            _LOGGER.warning("PRIMAGAS setup: cannot connect: %s", err)
            return {"base": "cannot_connect"}
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error during PRIMAGAS validation")
            return {"base": "unknown"}
        finally:
            await session.close()
        return {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_USERNAME] = user_input[CONF_USERNAME].strip()
            user_input[CONF_CUSTOMER_NUMBER] = user_input.get(
                CONF_CUSTOMER_NUMBER, ""
            ).strip()
            self._async_abort_entries_match({CONF_USERNAME: user_input[CONF_USERNAME]})
            # Only claim the customer number once the login works, so a failed
            # attempt never blocks a new setup with "already in progress".
            errors = await self._async_validate(user_input)
            if not errors:
                await self.async_set_unique_id(
                    user_input[CONF_CUSTOMER_NUMBER], raise_on_progress=False
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"PRIMAGAS {user_input[CONF_CUSTOMER_NUMBER]}",
                    data=user_input,
                )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                USER_SCHEMA,
                {k: v for k, v in (user_input or {}).items() if k != CONF_PASSWORD},
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]}
            errors = await self._async_validate(data)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            description_placeholders={"username": entry.data[CONF_USERNAME]},
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {
                **entry.data,
                CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            errors = await self._async_validate(data)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=data)
        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): USER_SCHEMA.schema[CONF_USERNAME],
                vol.Required(CONF_PASSWORD): USER_SCHEMA.schema[CONF_PASSWORD],
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                schema, {CONF_USERNAME: entry.data[CONF_USERNAME]}
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return PrimagasOptionsFlow()


class PrimagasOptionsFlow(OptionsFlow):
    """Options: polling interval."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            user_input[CONF_SCAN_INTERVAL_HOURS] = int(
                user_input[CONF_SCAN_INTERVAL_HOURS]
            )
            return self.async_create_entry(data=user_input)
        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL_HOURS, DEFAULT_SCAN_INTERVAL_HOURS
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL_HOURS, default=current
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL_HOURS,
                            max=MAX_SCAN_INTERVAL_HOURS,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="h",
                        )
                    )
                }
            ),
        )
