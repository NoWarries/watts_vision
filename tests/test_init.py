"""Test Watts Vision setup and coordinator behavior."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_SCAN_INTERVAL,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    Platform,
)
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.watts_vision.api import (
    WattsVisionAuthenticationError,
    WattsVisionConnectionError,
    WattsVisionDeviceMode,
)
from custom_components.watts_vision.const import DEVICE_TO_MODE_TYPE, DOMAIN

from .conftest import SMART_HOMES, snapshot_from_data

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from homeassistant.core import HomeAssistant, State
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.watts_vision import WattsVisionConfigEntry


def _entity_id(
    hass: HomeAssistant,
    platform: Platform,
    unique_id: str,
) -> str:
    """Return an entity ID from the entity registry."""
    entity_id = er.async_get(hass).async_get_entity_id(platform, DOMAIN, unique_id)
    assert entity_id is not None
    return entity_id


def _state(hass: HomeAssistant, entity_id: str) -> State:
    """Return an entity state."""
    state = hass.states.get(entity_id)
    assert state is not None
    return state


def test_home_assistant_mapping_covers_every_api_mode() -> None:
    """Test every API mode has a Home Assistant reporting fallback."""
    # Arrange - Collect every API mode, including the future-mode sentinel.
    api_modes = set(WattsVisionDeviceMode)

    # Act - Collect the integration's reporting mappings.
    mapped_modes = set(DEVICE_TO_MODE_TYPE)

    # Assert - Verify an API addition cannot produce an unmapped lookup.
    assert mapped_modes == api_modes


async def test_setup_creates_parent_devices_and_preserves_states(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test setup creates coherent devices and entity states."""
    # Arrange - Load the device registry.
    device_registry = dr.async_get(hass)

    # Act - Resolve the parent, child, and preserved entities.
    battery_id = _entity_id(hass, Platform.SENSOR, "battery_home-1#C001-000")
    battery_entry = er.async_get(hass).async_get(battery_id)
    assert battery_entry is not None
    assert battery_entry.device_id is not None
    parent = device_registry.async_get(
        setup_integration.runtime_data.parent_device_ids["home-1"]
    )
    child = device_registry.async_get(battery_entry.device_id)
    temperature_id = _entity_id(
        hass, Platform.SENSOR, "temperature_air_home-1#C001-000"
    )
    target_id = _entity_id(hass, Platform.SENSOR, "target_temperature_home-1#C001-000")
    preset_id = _entity_id(hass, Platform.SENSOR, "thermostat_mode_home-1#C001-000")
    temperature_mode_id = _entity_id(
        hass, Platform.SENSOR, "temperature_mode_home-1#C001-000"
    )
    heating_id = _entity_id(
        hass, Platform.BINARY_SENSOR, "thermostat_is_heating_home-1#C001-000"
    )
    last_communication_id = _entity_id(
        hass, Platform.SENSOR, "last_communication_home-1"
    )

    # Assert - Verify topology, states, units, and quiet logs.
    assert setup_integration.state is ConfigEntryState.LOADED
    assert parent is not None
    assert child is not None
    assert child.via_device_id == parent.id
    assert _state(hass, battery_id).state == "0"
    assert _state(hass, battery_id).attributes[ATTR_UNIT_OF_MEASUREMENT] == "%"
    assert float(_state(hass, temperature_id).state) == pytest.approx(21.9444444444)
    assert float(_state(hass, target_id).state) == pytest.approx(20.0)
    assert _state(hass, preset_id).state == "Comfort"
    assert _state(hass, temperature_mode_id).state == "Comfort"
    assert _state(hass, heating_id).state == STATE_ON
    assert _state(hass, last_communication_id).state == (
        "0 days, 1 hours, 2 minutes and 3 seconds."
    )
    assert "non existing `via_device`" not in caplog.text
    assert "Battery is malfunctioning" not in caplog.text


async def test_successful_refresh_updates_all_entity_states_together(
    hass: HomeAssistant,
    setup_integration: WattsVisionConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test one coordinator snapshot refreshes every platform together."""
    # Arrange - Prepare a changed account snapshot.
    coordinator = setup_integration.runtime_data.coordinator
    temperature_id = _entity_id(
        hass, Platform.SENSOR, "temperature_air_home-1#C001-000"
    )
    preset_id = _entity_id(hass, Platform.SENSOR, "thermostat_mode_home-1#C001-000")
    heating_id = _entity_id(
        hass, Platform.BINARY_SENSOR, "thermostat_is_heating_home-1#C001-000"
    )
    last_communication_id = _entity_id(
        hass, Platform.SENSOR, "last_communication_home-1"
    )
    refreshed_home_data = [dict(SMART_HOMES[0])]
    refreshed_home_data[0] = {
        **SMART_HOMES[0],
        "zones": [
            {
                **SMART_HOMES[0]["zones"][0],
                "devices": [
                    {
                        **SMART_HOMES[0]["zones"][0]["devices"][0],
                        "temperature_air": "700",
                        "gv_mode": "3",
                        "heating_up": "0",
                    }
                ],
            }
        ],
    }
    mock_watts_client.async_get_snapshot.return_value = snapshot_from_data(
        refreshed_home_data,
        {"diffObj": {"days": 1, "hours": 2, "minutes": 3, "seconds": 4}},
    )

    # Act - Refresh the shared coordinator once.
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    # Assert - Verify every platform uses the new snapshot.
    assert float(_state(hass, temperature_id).state) == pytest.approx(21.1111111111)
    assert _state(hass, preset_id).state == "Eco"
    assert _state(hass, heating_id).state == STATE_OFF
    assert _state(hass, last_communication_id).state == (
        "1 days, 2 hours, 3 minutes and 4 seconds."
    )


@pytest.mark.parametrize(
    ("error", "expected_state"),
    [
        (WattsVisionAuthenticationError, ConfigEntryState.SETUP_ERROR),
        (WattsVisionConnectionError, ConfigEntryState.SETUP_RETRY),
    ],
)
async def test_setup_handles_cloud_failures(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_watts_client: MagicMock,
    error: type[Exception],
    expected_state: ConfigEntryState,
) -> None:
    """Test setup distinguishes authentication and temporary failures."""
    # Arrange - Make the initial cloud request fail.
    mock_watts_client.async_get_snapshot.side_effect = error("cloud failure")

    # Act - Attempt config-entry setup.
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    # Assert - Verify retry or reauthentication behavior.
    assert config_entry.state is expected_state
    if error is WattsVisionAuthenticationError:
        assert any(
            flow["context"]["source"] == "reauth"
            for flow in hass.config_entries.flow.async_progress()
        )


async def test_coordinator_failure_and_recovery_logs_failure_once(
    hass: HomeAssistant,
    setup_integration: WattsVisionConfigEntry,
    mock_watts_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test coordinator failure and recovery update entity availability."""
    # Arrange - Prepare an established coordinator outage.
    coordinator = setup_integration.runtime_data.coordinator
    temperature_id = _entity_id(
        hass,
        Platform.SENSOR,
        "temperature_air_home-1#C001-000",
    )
    mock_watts_client.async_get_snapshot.side_effect = WattsVisionConnectionError(
        "offline"
    )
    previous_snapshot = coordinator.data
    caplog.set_level(logging.ERROR, logger="custom_components.watts_vision")

    # Act - Fail twice, then recover with fresh data.
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    state_while_offline = _state(hass, temperature_id).state
    snapshot_while_offline = coordinator.data
    errors_while_offline = [
        record for record in caplog.records if record.levelno == logging.ERROR
    ]
    recovered_homes = [dict(SMART_HOMES[0])]
    recovered_homes[0] = {
        **SMART_HOMES[0],
        "zones": [
            {
                **SMART_HOMES[0]["zones"][0],
                "devices": [
                    {
                        **SMART_HOMES[0]["zones"][0]["devices"][0],
                        "temperature_air": "700",
                    }
                ],
            }
        ],
    }
    mock_watts_client.async_get_snapshot.side_effect = None
    mock_watts_client.async_get_snapshot.return_value = snapshot_from_data(
        recovered_homes
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    # Assert - Verify availability, recovery, and one-time logging.
    assert state_while_offline == STATE_UNAVAILABLE
    assert len(errors_while_offline) == 1
    assert snapshot_while_offline is previous_snapshot
    assert coordinator.data is not previous_snapshot
    assert float(_state(hass, temperature_id).state) == pytest.approx(21.1111111111)
    assert coordinator.last_update_success


async def test_options_reload_applies_scan_interval(
    hass: HomeAssistant,
    setup_integration: WattsVisionConfigEntry,
) -> None:
    """Test updating options reloads the configured scan interval."""
    # Arrange - Start the options flow.
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)

    # Act - Save a new polling interval.
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 900},
    )
    await hass.async_block_till_done()

    # Assert - Verify the reloaded coordinator interval.
    assert setup_integration.runtime_data.coordinator.update_interval == timedelta(
        seconds=900
    )


async def test_unload_removes_entities_and_coordinator_contexts(
    hass: HomeAssistant,
    setup_integration: WattsVisionConfigEntry,
) -> None:
    """Test unloading removes entities and coordinator subscriptions."""
    # Arrange - Capture the coordinator and one entity.
    coordinator = setup_integration.runtime_data.coordinator
    temperature_id = _entity_id(
        hass,
        Platform.SENSOR,
        "temperature_air_home-1#C001-000",
    )

    # Act - Unload the config entry.
    unloaded = await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()

    # Assert - Verify platform and listener cleanup.
    assert unloaded
    assert setup_integration.state is ConfigEntryState.NOT_LOADED
    assert _state(hass, temperature_id).state == STATE_UNAVAILABLE
    assert not list(coordinator.async_contexts())
