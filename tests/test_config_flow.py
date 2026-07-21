"""Test Watts Vision config-flow credential validation."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.watts_vision.api import (
    WattsVisionAuthenticationError,
    WattsVisionConnectionError,
)
from custom_components.watts_vision.const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


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
