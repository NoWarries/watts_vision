"""Test Watts Vision climate commands."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import call

import pytest
from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ATTR_TEMPERATURE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACMode,
)
from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.watts_vision.api import (
    WattsVisionConnectionError,
    WattsVisionDeviceMode,
    WattsVisionResponseError,
)
from custom_components.watts_vision.const import DOMAIN

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_climate_commands_preserve_api_payloads(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test temperature and HVAC commands preserve their API payloads."""
    # Arrange - Resolve the thermostat entity.
    _ = setup_integration
    entity_id = er.async_get(hass).async_get_entity_id(
        Platform.CLIMATE,
        DOMAIN,
        "watts_thermostat_home-1#C001-000",
    )
    assert entity_id is not None

    # Act - Send temperature and HVAC mode commands.
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {
            ATTR_ENTITY_ID: entity_id,
            ATTR_TEMPERATURE: 20,
        },
        blocking=True,
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {
            ATTR_ENTITY_ID: entity_id,
            ATTR_HVAC_MODE: HVACMode.OFF,
        },
        blocking=True,
    )

    # Assert - Verify the existing API payloads.
    assert mock_watts_client.async_set_temperature.await_args_list == [
        call(
            "home-1",
            "api-device-1",
            68.0,
            WattsVisionDeviceMode.COMFORT,
        ),
        call(
            "home-1",
            "api-device-1",
            50.0,
            WattsVisionDeviceMode.OFF,
        ),
    ]
    coordinator = setup_integration.runtime_data
    device = coordinator.data.get_device("home-1", "home-1#C001-000")
    assert device is not None
    assert device.mode is WattsVisionDeviceMode.OFF


@pytest.mark.parametrize(
    ("api_result", "expected_message"),
    [
        (WattsVisionConnectionError("cloud failure"), "Unable to update"),
        (WattsVisionResponseError("rejected"), "rejected"),
    ],
    ids=("api-error", "rejected-command"),
)
async def test_climate_command_reports_api_failure(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
    api_result: Exception,
    expected_message: str,
) -> None:
    """Test climate commands retain their API error behavior."""
    # Arrange - Configure a failed thermostat API command.
    _ = setup_integration
    entity_id = er.async_get(hass).async_get_entity_id(
        Platform.CLIMATE,
        DOMAIN,
        "watts_thermostat_home-1#C001-000",
    )
    assert entity_id is not None
    mock_watts_client.async_set_temperature.side_effect = api_result

    # Act - Send the thermostat command.
    with pytest.raises(HomeAssistantError) as raised_error:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {
                ATTR_ENTITY_ID: entity_id,
                ATTR_TEMPERATURE: 20,
            },
            blocking=True,
        )

    # Assert - Verify the Home Assistant error message.
    assert expected_message in str(raised_error.value)
