"""Data update coordinator for Watts Vision."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, LOGGER
from .watts_api import JsonObject, WattsApi, WattsApiError, WattsAuthenticationError

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import WattsVisionConfigEntry


@dataclass(frozen=True, slots=True)
class WattsVisionData:
    """Coherent snapshot of Watts Vision account data."""

    smart_homes: list[JsonObject]
    last_communication: dict[str, JsonObject]

    def get_device(self, smart_home_id: str, device_id: str) -> JsonObject | None:
        """Return a device from the snapshot."""
        for smart_home in self.smart_homes:
            if str(smart_home.get("smarthome_id")) != smart_home_id:
                continue
            for zone in smart_home.get("zones") or []:
                for device in zone.get("devices") or []:
                    if str(device.get("id")) == device_id:
                        return device
        return None


class WattsVisionDataUpdateCoordinator(DataUpdateCoordinator[WattsVisionData]):
    """Coordinate polling for one Watts Vision account."""

    config_entry: WattsVisionConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: WattsVisionConfigEntry,
        client: WattsApi,
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

    async def _async_update_data(self) -> WattsVisionData:
        """Fetch a complete account snapshot."""
        try:
            await self.hass.async_add_executor_job(self.client.load_data)
            smart_homes = self.client.get_smart_homes()
            smart_home_ids = [
                str(smart_home["smarthome_id"]) for smart_home in smart_homes
            ]
            communication_results = await asyncio.gather(
                *(
                    self.hass.async_add_executor_job(
                        self.client.get_last_communication,
                        smart_home_id,
                    )
                    for smart_home_id in smart_home_ids
                )
            )
        except WattsAuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except WattsApiError as err:
            message = f"Unable to update Watts Vision data: {err}"
            raise UpdateFailed(message) from err

        return WattsVisionData(
            smart_homes=smart_homes,
            last_communication=dict(
                zip(smart_home_ids, communication_results, strict=True)
            ),
        )
