"""Test Watts Vision Boost duration settings."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import call

import pytest
from homeassistant.components.climate import (
    ATTR_PRESET_MODE,
    SERVICE_SET_PRESET_MODE,
)
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.components.number import DOMAIN as NUMBER_DOMAIN
from homeassistant.components.number import SERVICE_SET_VALUE
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.watts_vision.api import WattsVisionDeviceMode
from custom_components.watts_vision.const import DOMAIN

from .conftest import SMART_HOMES, snapshot_from_data

MIN_BOOST_MINUTES = 3.0
MAX_BOOST_MINUTES = 63_359.0
RESTORED_BOOST_MINUTES = 17.0

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_boost_duration_number_controls_boost_command(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test the restored per-device setting supplies Boost command seconds."""
    _ = setup_integration
    registry = er.async_get(hass)
    number_entity_id = registry.async_get_entity_id(
        Platform.NUMBER,
        DOMAIN,
        "boost_duration_home-1#C001-000",
    )
    climate_entity_id = registry.async_get_entity_id(
        Platform.CLIMATE,
        DOMAIN,
        "watts_thermostat_home-1#C001-000",
    )
    assert number_entity_id is not None
    assert climate_entity_id is not None
    number_state = hass.states.get(number_entity_id)
    assert number_state is not None
    assert number_state.state == "120.0"
    assert number_state.attributes["min"] == MIN_BOOST_MINUTES
    assert number_state.attributes["max"] == MAX_BOOST_MINUTES

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: number_entity_id, "value": 3},
        blocking=True,
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: climate_entity_id, ATTR_PRESET_MODE: "Boost"},
        blocking=True,
    )

    assert mock_watts_client.async_set_temperature.await_args == call(
        "home-1",
        "api-device-1",
        72.0,
        WattsVisionDeviceMode.BOOST,
        boost_duration=180,
    )


@pytest.mark.parametrize("value", [2, 3.5, 63_360])
async def test_boost_duration_number_rejects_invalid_values(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
    value: float,
) -> None:
    """Test invalid Boost durations never reach the thermostat API."""
    _ = setup_integration
    number_entity_id = er.async_get(hass).async_get_entity_id(
        Platform.NUMBER,
        DOMAIN,
        "boost_duration_home-1#C001-000",
    )
    assert number_entity_id is not None

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: number_entity_id, "value": value},
            blocking=True,
        )

    mock_watts_client.async_set_temperature.assert_not_awaited()


async def test_boost_duration_is_restored_after_reload(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """Test a previously selected per-device duration survives reload."""
    registry = er.async_get(hass)
    number_entity_id = registry.async_get_entity_id(
        Platform.NUMBER,
        DOMAIN,
        "boost_duration_home-1#C001-000",
    )
    assert number_entity_id is not None
    current_state = hass.states.get(number_entity_id)
    assert current_state is not None
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: number_entity_id, "value": RESTORED_BOOST_MINUTES},
        blocking=True,
    )

    await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done()

    restored_state = hass.states.get(number_entity_id)
    assert restored_state is not None
    assert restored_state.state == str(RESTORED_BOOST_MINUTES)
    assert (
        setup_integration.runtime_data.boost_durations[("home-1", "home-1#C001-000")]
        == RESTORED_BOOST_MINUTES
    )


async def test_boost_durations_are_isolated_per_thermostat(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test each thermostat sends its own configured Boost duration."""
    first_device = SMART_HOMES[0]["zones"][0]["devices"][0]
    second_device = {
        **first_device,
        "id": "home-1#C001-001",
        "id_device": "api-device-2",
    }
    homes = [
        {
            **SMART_HOMES[0],
            "zones": [
                {
                    **SMART_HOMES[0]["zones"][0],
                    "devices": [first_device, second_device],
                }
            ],
        }
    ]
    mock_watts_client.async_get_snapshot.return_value = snapshot_from_data(homes)
    await setup_integration.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    first_number = registry.async_get_entity_id(
        Platform.NUMBER, DOMAIN, "boost_duration_home-1#C001-000"
    )
    second_number = registry.async_get_entity_id(
        Platform.NUMBER, DOMAIN, "boost_duration_home-1#C001-001"
    )
    first_climate = registry.async_get_entity_id(
        Platform.CLIMATE, DOMAIN, "watts_thermostat_home-1#C001-000"
    )
    second_climate = registry.async_get_entity_id(
        Platform.CLIMATE, DOMAIN, "watts_thermostat_home-1#C001-001"
    )
    assert first_number is not None
    assert second_number is not None
    assert first_climate is not None
    assert second_climate is not None

    for entity_id, duration in ((first_number, 3), (second_number, 63_359)):
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: entity_id, "value": duration},
            blocking=True,
        )
    mock_watts_client.async_set_temperature.reset_mock()
    for entity_id in (first_climate, second_climate):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_PRESET_MODE,
            {ATTR_ENTITY_ID: entity_id, ATTR_PRESET_MODE: "Boost"},
            blocking=True,
        )

    assert mock_watts_client.async_set_temperature.await_args_list == [
        call(
            "home-1",
            "api-device-1",
            72.0,
            WattsVisionDeviceMode.BOOST,
            boost_duration=180,
        ),
        call(
            "home-1",
            "api-device-2",
            72.0,
            WattsVisionDeviceMode.BOOST,
            boost_duration=3_801_540,
        ),
    ]
