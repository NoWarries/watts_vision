"""Data update coordinator for Watts Vision."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    WattsVisionAuthenticationError,
    WattsVisionClient,
    WattsVisionDevice,
    WattsVisionError,
    WattsVisionSnapshot,
)
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, LOGGER

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import WattsVisionConfigEntry


class WattsVisionDataUpdateCoordinator(DataUpdateCoordinator[WattsVisionSnapshot]):
    """Coordinate polling for one Watts Vision account."""

    config_entry: WattsVisionConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: WattsVisionConfigEntry,
        client: WattsVisionClient,
    ) -> None:
        """Initialize the coordinator."""
        self.client = client
        scan_interval = config_entry.options.get(
            CONF_SCAN_INTERVAL,
            config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
            always_update=False,
        )

    async def _async_update_data(self) -> WattsVisionSnapshot:
        """Fetch a complete account snapshot."""
        try:
            return await self.client.async_get_snapshot()
        except WattsVisionAuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except WattsVisionError as err:
            message = f"Unable to update Watts Vision data: {err}"
            raise UpdateFailed(message) from err

    @callback
    def async_set_updated_device(
        self,
        smart_home_id: str,
        device: WattsVisionDevice,
    ) -> None:
        """Publish an immutable optimistic device update."""
        self.async_set_updated_data(
            self.data.replace_device(smart_home_id, device),
        )
