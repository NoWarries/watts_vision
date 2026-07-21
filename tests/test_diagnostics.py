"""Test Watts Vision diagnostics."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from custom_components.watts_vision.diagnostics import (
    async_get_config_entry_diagnostics,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.watts_vision import WattsVisionConfigEntry


async def test_diagnostics_redact_credentials_and_identifiers(
    hass: HomeAssistant,
    setup_integration: WattsVisionConfigEntry,
) -> None:
    """Test diagnostics retain useful state without account or device identifiers."""
    # Arrange - Load a configured integration with a coherent snapshot.
    entry = setup_integration

    # Act - Generate config-entry diagnostics.
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    # Assert - Verify secrets are redacted and anonymous state remains useful.
    entry_diagnostics = diagnostics["entry"]
    assert entry_diagnostics["data"][CONF_USERNAME] == "**REDACTED**"
    assert entry_diagnostics["data"][CONF_PASSWORD] == "**REDACTED**"
    serialized = str(diagnostics)
    assert "secret" not in serialized
    assert "user@example.com" not in serialized
    assert "home-1#C001-000" not in serialized
    assert diagnostics["coordinator"]["last_update_success"]
    assert diagnostics["homes"][0]["zones"][0]["devices"][0]["mode"] == "0"
