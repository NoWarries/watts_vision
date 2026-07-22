"""Diagnostics support for Watts Vision."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.const import CONF_SCAN_INTERVAL

from .const import DEFAULT_SCAN_INTERVAL, INTEGRATION_VERSION

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import WattsVisionConfigEntry


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant,
    entry: WattsVisionConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics without account or device identifiers."""
    coordinator = entry.runtime_data.coordinator
    return {
        "integration_version": INTEGRATION_VERSION,
        "scan_interval": entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        ),
        "coordinator": coordinator.diagnostics_data(),
    }
