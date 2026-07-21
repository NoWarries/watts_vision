"""Diagnostics support for Watts Vision."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import WattsVisionConfigEntry

TO_REDACT = {CONF_PASSWORD, CONF_USERNAME, "title", "unique_id"}


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant,
    entry: WattsVisionConfigEntry,
) -> dict[str, Any]:
    """Return privacy-conscious diagnostics for a config entry."""
    coordinator = entry.runtime_data.coordinator
    return {
        "entry": async_redact_data(entry.as_dict(), TO_REDACT),
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_exception": (
                str(coordinator.last_exception)
                if coordinator.last_exception is not None
                else None
            ),
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval is not None
                else None
            ),
        },
        "homes": [
            {
                "last_communication": asdict(smart_home.last_communication),
                "zones": [
                    {
                        "devices": [
                            {
                                "mode": device.mode.value,
                                "wire_mode": device.wire_mode,
                                "is_heating": device.is_heating,
                                "is_cooling": device.is_cooling,
                                "battery_low": device.battery_low,
                                "air_temperature": device.air_temperature,
                                "target_temperature": device.target_temperature,
                            }
                            for device in zone.devices
                        ]
                    }
                    for zone in smart_home.zones
                ],
            }
            for smart_home in coordinator.data.smart_homes
        ],
    }
