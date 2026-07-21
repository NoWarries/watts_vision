"""Test Watts Vision config-flow credential validation."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.watts_vision.api import (
    WattsVisionAuthenticationError,
    WattsVisionConnectionError,
)
from custom_components.watts_vision.const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_config_flow_shows_initial_form(hass: HomeAssistant) -> None:
    """Test starting the flow without input displays the credential form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}


async def test_settings_step_without_pending_account_returns_to_user(
    hass: HomeAssistant,
) -> None:
    """Test a stale settings flow cannot create an entry without credentials."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "settings"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_config_flow_validates_credentials_with_shared_session(
    hass: HomeAssistant,
) -> None:
    """Test valid credentials advance using Home Assistant's web session."""
    # Arrange - Mock successful asynchronous credential validation.
    with patch(
        "custom_components.watts_vision.config_flow.WattsVisionClient",
        autospec=True,
    ) as client_class:
        client_class.return_value.async_validate_credentials = AsyncMock()

        # Act - Submit account credentials.
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
            data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"},
        )

        # Assert - Verify the shared session and settings transition.
        client_class.assert_called_once_with(
            "user@example.com",
            "secret",
            session=async_get_clientsession(hass),
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "settings"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_SCAN_INTERVAL: 600},
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["title"] == "user@example.com"
        assert result["data"] == {
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
        }
        assert result["options"] == {CONF_SCAN_INTERVAL: 600}


@pytest.mark.parametrize(
    ("api_error", "expected_error"),
    [
        (WattsVisionAuthenticationError("rejected"), "invalid_credentials"),
        (WattsVisionConnectionError("offline"), "cannot_connect"),
    ],
    ids=("authentication", "connection"),
)
async def test_config_flow_maps_typed_credential_errors(
    hass: HomeAssistant,
    api_error: Exception,
    expected_error: str,
) -> None:
    """Test typed API errors map to stable config-flow errors."""
    # Arrange - Mock a failed asynchronous credential validation.
    with patch(
        "custom_components.watts_vision.config_flow.WattsVisionClient",
        autospec=True,
    ) as client_class:
        client_class.return_value.async_validate_credentials = AsyncMock(
            side_effect=api_error
        )

        # Act - Submit account credentials.
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
            data={CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"},
        )

        # Assert - Verify the user-facing config-flow error.
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] == {"base": expected_error}


async def test_config_flow_rejects_missing_and_duplicate_accounts(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """Test empty credentials and normalized duplicate account detection."""
    missing = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={CONF_USERNAME: " ", CONF_PASSWORD: ""},
    )
    assert missing["type"] is FlowResultType.FORM
    assert missing["errors"] == {"base": "missing_data"}

    with patch(
        "custom_components.watts_vision.config_flow.WattsVisionClient",
        autospec=True,
    ) as client_class:
        client_class.return_value.async_validate_credentials = AsyncMock()
        duplicate = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_USER},
            data={CONF_USERNAME: "USER@example.com", CONF_PASSWORD: "secret"},
        )

    assert duplicate["type"] is FlowResultType.ABORT
    assert duplicate["reason"] == "already_configured"
    assert config_entry.unique_id == "user@example.com"


@pytest.mark.parametrize(
    ("password", "api_error", "expected_error"),
    [
        ("", None, "missing_data"),
        (
            "new-secret",
            WattsVisionAuthenticationError("rejected"),
            "invalid_credentials",
        ),
        ("new-secret", WattsVisionConnectionError("offline"), "cannot_connect"),
    ],
    ids=("missing", "authentication", "connection"),
)
async def test_reauthentication_maps_validation_errors(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    password: str,
    api_error: Exception | None,
    expected_error: str,
) -> None:
    """Test reauthentication preserves the entry while validation fails."""
    with patch(
        "custom_components.watts_vision.config_flow.WattsVisionClient",
        autospec=True,
    ) as client_class:
        client_class.return_value.async_validate_credentials = AsyncMock(
            side_effect=api_error
        )
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_REAUTH, "entry_id": config_entry.entry_id},
            data=config_entry.data,
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: password},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected_error}
    assert config_entry.data[CONF_PASSWORD] == "secret"


async def test_reauthentication_updates_password_and_reloads(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """Test successful reauthentication updates the existing entry."""
    with patch(
        "custom_components.watts_vision.config_flow.WattsVisionClient",
        autospec=True,
    ) as client_class:
        client_class.return_value.async_validate_credentials = AsyncMock()
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_REAUTH, "entry_id": config_entry.entry_id},
            data=config_entry.data,
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_PASSWORD: "new-secret"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_PASSWORD] == "new-secret"


async def test_options_flow_uses_current_value_and_saves(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """Test options expose the configured interval and save replacements."""
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 900},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_SCAN_INTERVAL: 900}
