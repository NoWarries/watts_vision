"""Watts Vision integration setup."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    Platform,
)
from homeassistant.helpers import device_registry as dr

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .coordinator import WattsVisionDataUpdateCoordinator
from .watts_api import WattsApi

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PLATFORMS: tuple[Platform, ...] = (
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.CLIMATE,
)
CONFIG_ENTRY_VERSION = 1
CONFIG_ENTRY_MINOR_VERSION = 2

type WattsVisionConfigEntry = ConfigEntry[WattsVisionDataUpdateCoordinator]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WattsVisionConfigEntry,
) -> bool:
    """Set up Watts Vision from a config entry."""
    client = WattsApi(entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    coordinator = WattsVisionDataUpdateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    device_registry = dr.async_get(hass)
    for smart_home in coordinator.data.smart_homes:
        smart_home_id = str(smart_home["smarthome_id"])
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, smart_home_id)},
            connections={(dr.CONNECTION_NETWORK_MAC, str(smart_home["mac_address"]))},
            manufacturer="Watts",
            name=f"Central Unit {smart_home['label']}",
            model="BT-CT02-RF",
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: WattsVisionConfigEntry,
) -> bool:
    """Unload a Watts Vision config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(
    hass: HomeAssistant,
    entry: WattsVisionConfigEntry,
) -> bool:
    """Migrate legacy Watts Vision config entries."""
    if (
        entry.version != CONFIG_ENTRY_VERSION
        or entry.minor_version >= CONFIG_ENTRY_MINOR_VERSION
    ):
        return True

    data = dict(entry.data)
    options = dict(entry.options)
    options.setdefault(
        CONF_SCAN_INTERVAL,
        data.pop(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )

    unique_id = entry.unique_id
    candidate_unique_id = str(data[CONF_USERNAME]).strip().casefold()
    duplicate_unique_id = any(
        other.entry_id != entry.entry_id and other.unique_id == candidate_unique_id
        for other in hass.config_entries.async_entries(entry.domain)
    )
    if unique_id is None and not duplicate_unique_id:
        unique_id = candidate_unique_id

    hass.config_entries.async_update_entry(
        entry,
        data=data,
        options=options,
        unique_id=unique_id,
        minor_version=CONFIG_ENTRY_MINOR_VERSION,
    )
    _LOGGER.info("Migrated Watts Vision config entry to version 1.2")
    return True
