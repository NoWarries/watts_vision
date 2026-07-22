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
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import WattsVisionClient
from .const import DEFAULT_SCAN_INTERVAL
from .coordinator import WattsVisionDataUpdateCoordinator
from .runtime import WattsVisionRuntimeData

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PLATFORMS: tuple[Platform, ...] = (
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.CLIMATE,
)
CONFIG_ENTRY_VERSION = 1
CONFIG_ENTRY_MINOR_VERSION = 3

type WattsVisionConfigEntry = ConfigEntry[WattsVisionRuntimeData]


def _async_remove_retired_entities(
    hass: HomeAssistant,
    entry: WattsVisionConfigEntry,
) -> None:
    """Remove registry entries for retired fabricated compatibility sensors."""
    entity_registry = er.async_get(hass)
    for registry_entry in er.async_entries_for_config_entry(
        entity_registry,
        entry.entry_id,
    ):
        unique_id = registry_entry.unique_id
        is_retired_battery = unique_id.startswith(
            "battery_"
        ) and not unique_id.startswith("battery_low_")
        is_retired_communication_age = unique_id.startswith(
            "last_communication_"
        ) and not unique_id.startswith("last_communication_timestamp_")
        if registry_entry.platform == entry.domain and (
            is_retired_battery or is_retired_communication_age
        ):
            entity_registry.async_remove(registry_entry.entity_id)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WattsVisionConfigEntry,
) -> bool:
    """Set up Watts Vision from a config entry."""
    client = WattsVisionClient(
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        session=async_get_clientsession(hass),
    )
    parent_device_ids: dict[str, str] = {}
    coordinator = WattsVisionDataUpdateCoordinator(
        hass,
        entry,
        client,
        parent_device_ids,
    )
    await coordinator.async_config_entry_first_refresh()
    entry.async_on_unload(coordinator.async_cancel_reconciliation)

    entry.runtime_data = WattsVisionRuntimeData(
        coordinator=coordinator,
        parent_device_ids=parent_device_ids,
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

    _async_remove_retired_entities(hass, entry)

    hass.config_entries.async_update_entry(
        entry,
        data=data,
        options=options,
        unique_id=unique_id,
        minor_version=CONFIG_ENTRY_MINOR_VERSION,
    )
    _LOGGER.info("Migrated Watts Vision config entry to version 1.3")
    return True
