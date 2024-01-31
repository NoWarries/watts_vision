"""Watts Vision Component."""

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .const import API_CLIENT, DOMAIN
from .watts_api import WattsApi

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.CLIMATE]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Watts Vision from a config entry."""
    _LOGGER.debug("Set up Watts Vision")
    hass.data.setdefault(DOMAIN, {})

    client = WattsApi(hass, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])

    try:
        await hass.async_add_executor_job(client.getLoginToken)
    except Exception as exception:  # pylint: disable=broad-except
        _LOGGER.exception(exception)
        return False

    await hass.async_add_executor_job(client.loadData)

    hass.data[DOMAIN][API_CLIENT] = client

    for platform in PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, platform)
        )

    async def refresh_devices(event_time):
        _LOGGER.debug("Refreshing devices")
        await hass.async_add_executor_job(client.reloadDevices)

    # If scan interval is not found in config, set it to 300 seconds
    if CONF_SCAN_INTERVAL not in entry.data:
        _LOGGER.warn("No scan interval found in config, defaulting to 300 seconds")
        interval = 300
    else:
        interval = entry.data.get(CONF_SCAN_INTERVAL)

    SCAN_INTERVAL = timedelta(seconds=interval)

    _LOGGER.debug("Setting up refresh interval to %s", SCAN_INTERVAL)
    async_track_time_interval(hass, refresh_devices, SCAN_INTERVAL)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Watts Vision")
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(API_CLIENT)
    return unload_ok
