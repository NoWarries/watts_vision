"""Config and options flows for Watts Vision."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import callback

from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .watts_api import WattsApi

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigFlowResult

ACCOUNT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)

SCAN_INTERVAL_SCHEMA = vol.Schema(
    {
        vol.Required(
            CONF_SCAN_INTERVAL,
            default=DEFAULT_SCAN_INTERVAL,
        ): vol.All(int, vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL))
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the Watts Vision config flow."""

    VERSION = 1
    MINOR_VERSION = 2

    def __init__(self) -> None:
        """Initialize a config flow."""
        self._account_data: dict[str, Any] | None = None

    async def _async_credentials_are_valid(self, username: str, password: str) -> bool:
        """Return whether the account credentials authenticate."""
        api = WattsApi(username, password)
        return await self.hass.async_add_executor_job(api.test_authentication)

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the account credentials step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            username = str(user_input[CONF_USERNAME]).strip()
            password = str(user_input[CONF_PASSWORD])
            if not username or not password:
                errors["base"] = "missing_data"
            elif not await self._async_credentials_are_valid(username, password):
                errors["base"] = "invalid_credentials"
            else:
                await self.async_set_unique_id(username.casefold())
                self._abort_if_unique_id_configured()
                self._account_data = {
                    CONF_USERNAME: username,
                    CONF_PASSWORD: password,
                }
                return await self.async_step_settings()

        return self.async_show_form(
            step_id="user",
            data_schema=ACCOUNT_SCHEMA,
            errors=errors,
        )

    async def async_step_settings(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the scan interval step."""
        if self._account_data is None:
            return await self.async_step_user()

        if user_input is not None:
            return self.async_create_entry(
                title=str(self._account_data[CONF_USERNAME]),
                data=self._account_data,
                options={CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL]},
            )

        return self.async_show_form(
            step_id="settings",
            data_schema=SCAN_INTERVAL_SCHEMA,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        _config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlowHandler:
        """Return the options flow handler."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlowWithReload):
    """Handle Watts Vision options."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Manage the integration options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                SCAN_INTERVAL_SCHEMA,
                {CONF_SCAN_INTERVAL: current_interval},
            ),
        )
