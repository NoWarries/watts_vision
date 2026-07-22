"""Test Watts Vision climate commands."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import ANY, call

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
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

from custom_components.watts_vision.api import (
    WattsVisionCommunicationAge,
    WattsVisionConnectionError,
    WattsVisionDeviceMode,
    WattsVisionResponseError,
)
from custom_components.watts_vision.climate import WattsThermostat
from custom_components.watts_vision.const import DOMAIN
from custom_components.watts_vision.entity import WattsVisionEntityContext

from .conftest import SMART_HOMES, snapshot_from_data

HALF_CELSIUS = 0.5

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
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.attributes["preset_modes"] == [
        "Comfort",
        "Eco",
        "Frost Protection",
        "Boost",
    ]
    assert state.attributes["target_temp_step"] == HALF_CELSIUS

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
            0.0,
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


async def test_stale_central_unit_reports_clear_command_error(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test a live communication preflight prevents an undeliverable command."""
    _ = setup_integration
    entity_id = er.async_get(hass).async_get_entity_id(
        Platform.CLIMATE,
        DOMAIN,
        "watts_thermostat_home-1#C001-000",
    )
    assert entity_id is not None
    mock_watts_client.async_get_communication_age.return_value = (
        WattsVisionCommunicationAge(0, 0, 1, 1)
    )

    with pytest.raises(HomeAssistantError) as raised_error:
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_PRESET_MODE,
            {ATTR_ENTITY_ID: entity_id, ATTR_PRESET_MODE: "Eco"},
            blocking=True,
        )

    assert "61 seconds" in str(raised_error.value)
    mock_watts_client.async_set_temperature.assert_not_awaited()


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


@pytest.mark.parametrize("wire_mode", ["8", "11", "13", "16"])
async def test_temperature_write_is_rejected_for_every_program_phase(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
    wire_mode: str,
) -> None:
    """Test PR #24's read-only target rule across every Program variant."""
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

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: entity_id, ATTR_TEMPERATURE: 20},
            blocking=True,
        )

    mock_watts_client.async_set_temperature.assert_not_awaited()


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
    mock_watts_client.reset_mock()

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
    mock_watts_client.async_get_current_program_mode.assert_awaited_once()


async def test_auto_uses_current_program_comfort_phase(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test AUTO commands Program Comfort when that schedule period is active."""
    _ = setup_integration
    mock_watts_client.async_get_current_program_mode.return_value = (
        WattsVisionDeviceMode.PROGRAM_COMFORT
    )
    entity_id = er.async_get(hass).async_get_entity_id(
        Platform.CLIMATE, DOMAIN, "watts_thermostat_home-1#C001-000"
    )
    assert entity_id is not None
    mock_watts_client.reset_mock()

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_HVAC_MODE,
        {ATTR_ENTITY_ID: entity_id, ATTR_HVAC_MODE: HVACMode.AUTO},
        blocking=True,
    )

    mock_watts_client.async_get_current_program_mode.assert_awaited_once()
    mock_watts_client.async_set_temperature.assert_awaited_once_with(
        "home-1",
        "api-device-1",
        68.0,
        WattsVisionDeviceMode.PROGRAM_COMFORT,
    )
    assert mock_watts_client.method_calls == [
        call.async_get_current_program_mode("home-1#C001-000", ANY),
        call.async_get_communication_age("home-1"),
        call.async_set_temperature(
            "home-1",
            "api-device-1",
            68.0,
            WattsVisionDeviceMode.PROGRAM_COMFORT,
        ),
    ]


async def test_auto_uses_current_program_boost_phase(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test AUTO commands the production client's Program Boost mode."""
    _ = setup_integration
    mock_watts_client.async_get_current_program_mode.return_value = (
        WattsVisionDeviceMode.PROGRAM_BOOST
    )
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

    mock_watts_client.async_get_current_program_mode.assert_awaited_once()
    mock_watts_client.async_set_temperature.assert_awaited_once_with(
        "home-1",
        "api-device-1",
        72.0,
        WattsVisionDeviceMode.PROGRAM_BOOST,
    )


async def test_temperature_uses_device_celsius_half_step(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test a 0.5 Celsius request is converted once to Fahrenheit tenths."""
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
        68.9,
        WattsVisionDeviceMode.COMFORT,
    )


@pytest.mark.parametrize(
    ("requested", "expected_fahrenheit"),
    [(20.24, 68.0), (20.25, 68.9), (20.74, 68.9), (20.75, 69.8)],
)
async def test_temperature_midpoints_use_decimal_half_up(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
    requested: float,
    expected_fahrenheit: float,
) -> None:
    """Test midpoint handling does not use Python ties-to-even rounding."""
    _ = setup_integration
    entity_id = er.async_get(hass).async_get_entity_id(
        Platform.CLIMATE, DOMAIN, "watts_thermostat_home-1#C001-000"
    )
    assert entity_id is not None

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: entity_id, ATTR_TEMPERATURE: requested},
        blocking=True,
    )

    mock_watts_client.async_set_temperature.assert_awaited_once_with(
        "home-1",
        "api-device-1",
        expected_fahrenheit,
        WattsVisionDeviceMode.COMFORT,
    )


async def test_fahrenheit_configuration_is_converted_only_once(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test Home Assistant converts Fahrenheit input once at the entity boundary."""
    hass.config.units = US_CUSTOMARY_SYSTEM
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    entity_id = er.async_get(hass).async_get_entity_id(
        Platform.CLIMATE, DOMAIN, "watts_thermostat_home-1#C001-000"
    )
    assert entity_id is not None

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: entity_id, ATTR_TEMPERATURE: 68.9},
        blocking=True,
    )

    mock_watts_client.async_set_temperature.assert_awaited_once_with(
        "home-1",
        "api-device-1",
        68.9,
        WattsVisionDeviceMode.COMFORT,
    )


async def test_turn_on_restores_mode_and_legacy_aliases_are_rejected(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test restoration and removal of nonstandard Program/Off presets."""
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
    for unsupported_preset in ("Program", "Off"):
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(
                CLIMATE_DOMAIN,
                SERVICE_SET_PRESET_MODE,
                {ATTR_ENTITY_ID: entity_id, ATTR_PRESET_MODE: unsupported_preset},
                blocking=True,
            )

    assert mock_watts_client.async_set_temperature.await_args_list == [
        call("home-1", "api-device-1", 62.0, WattsVisionDeviceMode.ECO),
        call("home-1", "api-device-1", 0.0, WattsVisionDeviceMode.OFF),
        call("home-1", "api-device-1", 62.0, WattsVisionDeviceMode.ECO),
    ]


async def test_frost_reports_fixed_target_and_rejects_temperature_write(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test Frost Protection is a fixed 7 Celsius reporting preset."""
    coordinator = setup_integration.runtime_data.coordinator
    frost_homes = [
        {
            **SMART_HOMES[0],
            "zones": [
                {
                    **SMART_HOMES[0]["zones"][0],
                    "devices": [
                        {
                            **SMART_HOMES[0]["zones"][0]["devices"][0],
                            "gv_mode": "2",
                        }
                    ],
                }
            ],
        }
    ]
    mock_watts_client.async_get_snapshot.return_value = snapshot_from_data(frost_homes)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    mock_watts_client.async_set_temperature.reset_mock()

    entity_id = er.async_get(hass).async_get_entity_id(
        Platform.CLIMATE, DOMAIN, "watts_thermostat_home-1#C001-000"
    )
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.attributes[ATTR_PRESET_MODE] == "Frost Protection"
    assert ATTR_TEMPERATURE not in state.attributes

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {ATTR_ENTITY_ID: entity_id, ATTR_TEMPERATURE: 8},
            blocking=True,
        )
    mock_watts_client.async_set_temperature.assert_not_awaited()


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
