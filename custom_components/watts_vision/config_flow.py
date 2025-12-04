"""This Modules contains the logic to register your watts vision account with HA"""

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, LOGGER
from .watts_api import WattsApi

# Schema for registering an account with the WattsVision API
register_schema = vol.Schema(
    {vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str}
)

# Schema for configuring the Watts Vision integration
option_schema = vol.Schema(
    {vol.Optional(CONF_SCAN_INTERVAL, description={"suggested_value": 300}): int}
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """
    Standard config flow for WattsVision.

    Args:
        config_entries (ConfigFlow)
        domain (str, optional): Defaults to DOMAIN constant.

    """

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    # Dictionary to store user input
    input: dict
    # Dictionary to store errors
    errors: dict = {}

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """
        Handle the initial configuration step.

        Args:
            user_input (dict, optional): User input. Defaults to None.

        Returns:
            FlowResult: A FlowResult object

        """
        if user_input is not None:
            LOGGER.debug(
                "[ConfigFlow] [async_step_user] user_input submitted %s", user_input
            )
            if await self.validate_input_user(user_input) is False:
                LOGGER.debug("[ConfigFlow] [user] user_input validation failed")
                LOGGER.debug("[ConfigFlow] [user] errors: %s", self.errors)
                return await self.async_step_user()
            LOGGER.debug("[ConfigFlow] [async_step_user] user_input validation passed")

            self.input = user_input

            return await self.async_step_settings()

        LOGGER.debug("[ConfigFlow] [async_step_user] config flow started")
        return self.async_show_form(
            step_id="user", data_schema=register_schema, errors=self.errors
        )

    async def validate_input_user(self, user_input: dict) -> bool:
        """
        Validate the user input for the initial configuration step.

        Args:
            user_input (dict): User input

        Returns:
            bool: True if the input is valid, False otherwise

        """
        api = WattsApi(self.hass, user_input[CONF_USERNAME], user_input[CONF_PASSWORD])

        try:
            authenticated = await self.hass.async_add_executor_job(
                api.test_authentication
            )
        # pylint: disable=broad-except
        except Exception as exception:
            LOGGER.exception(
                "[ConfigFlow] [validate_input_user] Error while authenticating: %s",
                exception,
            )
            self.errors = {CONF_USERNAME: "unknown_authentication_error"}
            return False

        LOGGER.debug("[ConfigFlow] [validate_input_user] Validating user_input")
        if user_input[CONF_USERNAME] == "" or user_input[CONF_PASSWORD] == "":
            self.errors = {CONF_USERNAME: "missing_data"}
            return False
        if authenticated is False:
            self.errors = {CONF_USERNAME: "invalid_credentials"}
            return False
        return True

    async def async_step_settings(self, user_input: dict | None = None) -> FlowResult:
        """
        Handle the settings configuration step.

        Args:
            user_input (dict, optional): User input. Defaults to None.

        Returns:
            FlowResult: A FlowResult object

        """
        if user_input is not None:
            LOGGER.debug(
                "[ConfigFlow] [async_step_settings] user_input submitted %s", user_input
            )
            if self.validate_input_settings(user_input) is False:
                LOGGER.debug(
                    "[ConfigFlow] [async_step_settings] user_input validation failed"
                )
                LOGGER.debug(
                    "[ConfigFlow] [async_step_settings] errors: %s", self.errors
                )
                return await self.async_step_settings()
            LOGGER.debug(
                "[ConfigFlow] [async_step_settings] user_input validation passed"
            )

            self.input.update(user_input)

            LOGGER.info(
                "[ConfigFlow] [async_step_settings] Creating entry %s", self.input
            )
            return self.async_create_entry(
                title=self.input["username"], data=self.input
            )

        return self.async_show_form(
            step_id="settings", data_schema=option_schema, errors=self.errors
        )

    def validate_input_settings(self, user_input: dict) -> bool:
        """
        Validate the user input for the settings step.

        Args:
            user_input (dict): User input

        Returns:
            bool: True if the input is valid, False otherwise

        """
        LOGGER.debug("[ConfigFlow] [validate_input_settings] Validating user_input")
        if user_input[CONF_SCAN_INTERVAL] < 300:
            self.errors = {CONF_SCAN_INTERVAL: "scan_interval_too_low"}
            return False
        if user_input[CONF_SCAN_INTERVAL] > 86400:
            self.errors = {CONF_SCAN_INTERVAL: "scan_interval_too_high"}
            return False
        return True

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """
    Standard options flow for WattsVision.

    Args:
        config_entries (OptionsFlow)

    """

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    # Dictionary to store errors
    errors: dict = {}

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            LOGGER.debug(
                "[OptionsFlowHandler] [async_step_user] user_input submitted %s",
                user_input,
            )
            if self.validate_input_settings(user_input) is False:
                LOGGER.debug(
                    "[OptionsFlowHandler] [async_step_user] user_input validation failed"
                )
                LOGGER.debug(
                    "[OptionsFlowHandler] [async_step_user] errors: %s", self.errors
                )
                return await self.async_step_user()
            LOGGER.debug(
                "[OptionsFlowHandler] [async_step_user] user_input validation passed"
            )

            LOGGER.info(
                "[OptionsFlowHandler] [async_step_user] Updating entry %s", user_input
            )
            updated = self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={
                    CONF_USERNAME: self.config_entry.data[CONF_USERNAME],
                    CONF_PASSWORD: self.config_entry.data[CONF_PASSWORD],
                    CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                },
            )
            if updated:
                LOGGER.info(
                    "[OptionsFlowHandler] [async_step_user] Entry updated reload platform"
                )
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)

            return self.async_create_entry(title="", data=user_input)

        interval = 300
        try:
            interval = self.config_entry.data[CONF_SCAN_INTERVAL]
        except:
            LOGGER.warn(
                "Something went wrong retrieving scan interval, attempting to restore"
            )
            interval = 300
        finally:
            LOGGER.debug("Updating")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL, description={"suggested_value": interval}
                    ): int
                }
            ),
            errors=self.errors,
        )

    def validate_input_settings(self, user_input: dict) -> bool:
        """
        Validate the user input for the settings step.

        Args:
            user_input (dict): User input

        Returns:
            bool: True if the input is valid, False otherwise

        """
        LOGGER.debug(
            "[OptionsFlowHandler] [validate_input_settings] Validating user_input"
        )
        if user_input[CONF_SCAN_INTERVAL] < 300:
            self.errors = {CONF_SCAN_INTERVAL: "scan_interval_too_low"}
            return False
        if user_input[CONF_SCAN_INTERVAL] > 86400:
            self.errors = {CONF_SCAN_INTERVAL: "scan_interval_too_high"}
            return False
        return True
