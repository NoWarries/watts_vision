"""Test Watts Vision diagnostics."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from custom_components.watts_vision.api import WattsVisionDeviceMode
from custom_components.watts_vision.const import DEFAULT_SCAN_INTERVAL
from custom_components.watts_vision.diagnostics import (
    async_get_config_entry_diagnostics,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_diagnostics_are_useful_and_redacted(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
) -> None:
    """Test diagnostics include health state without account identifiers."""
    coordinator = setup_integration.runtime_data.coordinator
    await coordinator.async_set_device_temperature(
        "home-1",
        "home-1#C001-000",
        68.9,
        WattsVisionDeviceMode.COMFORT,
        update_target=True,
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, setup_integration)
    serialized = json.dumps(diagnostics)

    assert diagnostics["integration_version"] == "1.0.0"
    assert diagnostics["scan_interval"] == DEFAULT_SCAN_INTERVAL
    assert diagnostics["coordinator"]["pending_commands"]
    assert "user@example.com" not in serialized
    assert "secret" not in serialized
    assert "home-1" not in serialized
    assert "C001-000" not in serialized
