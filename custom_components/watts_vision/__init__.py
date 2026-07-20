"""Watts Vision integration setup."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    Platform,
)
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.event import async_track_time_interval

from .const import DEFAULT_SCAN_INTERVAL
from .watts_api import WattsApi, WattsApiError, WattsAuthenticationError

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

type WattsVisionConfigEntry = ConfigEntry[WattsApi]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WattsVisionConfigEntry,
) -> bool:
    """Set up Watts Vision from a config entry."""
    client = WattsApi(entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])

    try:
        await hass.async_add_executor_job(client.get_login_token)
        await hass.async_add_executor_job(client.load_data)
    except WattsAuthenticationError as err:
        raise ConfigEntryAuthFailed from err
    except WattsApiError as err:
        raise ConfigEntryNotReady from err

    entry.runtime_data = client
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    scan_interval = entry.options.get(
        CONF_SCAN_INTERVAL,
        entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )

    async def async_refresh_devices(_now: datetime) -> None:
        """Refresh cached device data."""
        try:
            await hass.async_add_executor_job(client.reload_devices)
        except WattsApiError:
            _LOGGER.exception("Unable to refresh Watts Vision devices")

    entry.async_on_unload(
        async_track_time_interval(
            hass,
            async_refresh_devices,
            timedelta(seconds=scan_interval),
        )
    )
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
