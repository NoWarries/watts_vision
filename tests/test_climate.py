"""Test Watts Vision climate commands."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import call

import pytest
from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ATTR_HVAC_MODES,
    ATTR_PRESET_MODE,
    ATTR_TEMPERATURE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_PRESET_MODE,
    SERVICE_SET_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
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
from custom_components.watts_vision.climate import WattsThermostat
from custom_components.watts_vision.const import DOMAIN
from custom_components.watts_vision.entity import WattsVisionEntityContext

from .conftest import SMART_HOMES, snapshot_from_data

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


def test_legacy_raw_attributes_are_excluded_from_recorder() -> None:
    """Test compatibility attributes remain available without history growth."""
    assert {
        "consigne_eco",
        "consigne_hg",
        "consigne_confort",
        "consigne_manuel",
        "consigne_boost",
        "temperature_air",
        "gv_mode",
    } <= WattsThermostat._unrecorded_attributes  # noqa: SLF001


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
    coordinator = setup_integration.runtime_data.coordinator
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


@pytest.mark.parametrize(
    ("wire_mode", "preset"),
    [("8", "Comfort"), ("11", "Eco"), ("16", "Boost"), ("13", None)],
    ids=("comfort", "eco", "boost", "unspecified"),
)
async def test_program_variants_report_auto_with_active_preset(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
    wire_mode: str,
    preset: str | None,
) -> None:
    """Test scheduled programs use AUTO while retaining their active preset."""
    coordinator = setup_integration.runtime_data.coordinator
    homes = [
        {
            **SMART_HOMES[0],
            "zones": [
                {
                    **SMART_HOMES[0]["zones"][0],
                    "devices": [
                        {
                            **SMART_HOMES[0]["zones"][0]["devices"][0],
                            "gv_mode": wire_mode,
                        }
                    ],
                }
            ],
        }
    ]
    mock_watts_client.async_get_snapshot.return_value = snapshot_from_data(homes)

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id(
        Platform.CLIMATE, DOMAIN, "watts_thermostat_home-1#C001-000"
    )
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == HVACMode.AUTO
    assert state.attributes.get(ATTR_PRESET_MODE) == preset


async def test_climate_advertises_only_the_commandable_season(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test the heat/cool API flag determines the sole manual HVAC mode."""
    coordinator = setup_integration.runtime_data.coordinator
    cooling_homes = [
        {
            **SMART_HOMES[0],
            "zones": [
                {
                    **SMART_HOMES[0]["zones"][0],
                    "devices": [
                        {
                            **SMART_HOMES[0]["zones"][0]["devices"][0],
                            "heat_cool": "1",
                        }
                    ],
                }
            ],
        }
    ]
    mock_watts_client.async_get_snapshot.return_value = snapshot_from_data(
        cooling_homes
    )

    await coordinator.async_refresh()
    await hass.async_block_till_done()

    entity_id = er.async_get(hass).async_get_entity_id(
        Platform.CLIMATE, DOMAIN, "watts_thermostat_home-1#C001-000"
    )
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == HVACMode.COOL
    assert state.attributes[ATTR_HVAC_MODES] == [
        HVACMode.COOL,
        HVACMode.AUTO,
        HVACMode.OFF,
    ]
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: entity_id, ATTR_HVAC_MODE: HVACMode.HEAT},
            blocking=True,
        )


async def test_auto_and_manual_hvac_commands_use_program_and_comfort_modes(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test HVAC AUTO and seasonal manual commands use supported API modes."""
    _ = setup_integration
    entity_id = er.async_get(hass).async_get_entity_id(
        Platform.CLIMATE, DOMAIN, "watts_thermostat_home-1#C001-000"
    )
    assert entity_id is not None

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: entity_id, ATTR_HVAC_MODE: HVACMode.AUTO},
        blocking=True,
    )
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: entity_id, ATTR_TEMPERATURE: 20},
            blocking=True,
        )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: entity_id, ATTR_HVAC_MODE: HVACMode.HEAT},
        blocking=True,
    )

    assert mock_watts_client.async_set_temperature.await_args_list == [
        call("home-1", "api-device-1", 62.0, WattsVisionDeviceMode.PROGRAM_ECO),
        call("home-1", "api-device-1", 68.0, WattsVisionDeviceMode.COMFORT),
    ]


async def test_temperature_rounds_to_nearest_fahrenheit_step(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test converted temperatures round instead of truncating Fahrenheit."""
    _ = setup_integration
    entity_id = er.async_get(hass).async_get_entity_id(
        Platform.CLIMATE, DOMAIN, "watts_thermostat_home-1#C001-000"
    )
    assert entity_id is not None

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: entity_id, ATTR_TEMPERATURE: 20.5},
        blocking=True,
    )

    mock_watts_client.async_set_temperature.assert_awaited_once_with(
        "home-1",
        "api-device-1",
        69.0,
        WattsVisionDeviceMode.COMFORT,
    )


async def test_turn_on_restores_mode_and_legacy_aliases_remain_actionable(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test restoration and the retained Program/Off action aliases."""
    _ = setup_integration
    entity_id = er.async_get(hass).async_get_entity_id(
        Platform.CLIMATE, DOMAIN, "watts_thermostat_home-1#C001-000"
    )
    assert entity_id is not None

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: entity_id, ATTR_PRESET_MODE: "Eco"},
        blocking=True,
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: entity_id},
        blocking=True,
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: entity_id},
        blocking=True,
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: entity_id, ATTR_PRESET_MODE: "Program"},
        blocking=True,
    )
    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: entity_id, ATTR_PRESET_MODE: "Off"},
        blocking=True,
    )

    assert mock_watts_client.async_set_temperature.await_args_list == [
        call("home-1", "api-device-1", 62.0, WattsVisionDeviceMode.ECO),
        call("home-1", "api-device-1", 50.0, WattsVisionDeviceMode.OFF),
        call("home-1", "api-device-1", 62.0, WattsVisionDeviceMode.ECO),
        call("home-1", "api-device-1", 62.0, WattsVisionDeviceMode.PROGRAM_ECO),
        call("home-1", "api-device-1", 50.0, WattsVisionDeviceMode.OFF),
    ]


async def test_turn_on_after_restart_falls_back_to_comfort(
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test an entity first seen as off has a safe Comfort restoration mode."""
    coordinator = setup_integration.runtime_data.coordinator
    off_homes = [
        {
            **SMART_HOMES[0],
            "zones": [
                {
                    **SMART_HOMES[0]["zones"][0],
                    "devices": [
                        {
                            **SMART_HOMES[0]["zones"][0]["devices"][0],
                            "gv_mode": "1",
                        }
                    ],
                }
            ],
        }
    ]
    coordinator.async_set_updated_data(snapshot_from_data(off_homes))
    thermostat = WattsThermostat(
        coordinator,
        WattsVisionEntityContext(
            smart_home_id="home-1",
            device_id="home-1#C001-000",
            zone="Living room",
            parent_device_id=setup_integration.runtime_data.parent_device_ids["home-1"],
        ),
        "api-device-1",
    )

    await thermostat.async_turn_on()

    mock_watts_client.async_set_temperature.assert_awaited_once_with(
        "home-1",
        "api-device-1",
        68.0,
        WattsVisionDeviceMode.COMFORT,
    )
