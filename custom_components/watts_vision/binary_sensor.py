"""Binary sensor platform for Watts Vision."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from . import WattsVisionConfigEntry
    from .watts_api import JsonObject, WattsApi

SCAN_INTERVAL = timedelta(seconds=120)


async def async_setup_entry(
    _hass: HomeAssistant,
    config_entry: WattsVisionConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Watts Vision binary sensors."""
    client = config_entry.runtime_data
    sensors: list[BinarySensorEntity] = []
    for smart_home in client.get_smart_homes():
        smart_home_id = str(smart_home["smarthome_id"])
        for zone in smart_home.get("zones") or []:
            zone_label = str(zone["zone_label"])
            sensors.extend(
                WattsVisionHeatingBinarySensor(
                    client,
                    smart_home_id,
                    str(device["id"]),
                    zone_label,
                )
                for device in zone.get("devices") or []
            )

    async_add_entities(sensors, update_before_add=True)


class WattsVisionHeatingBinarySensor(BinarySensorEntity):
    """Represent whether a Watts Vision thermostat is actively heating."""

    _attr_device_class = BinarySensorDeviceClass.HEAT
    _attr_has_entity_name = True
    _attr_translation_key = "heating"

    def __init__(
        self,
        client: WattsApi,
        smart_home_id: str,
        device_id: str,
        zone: str,
    ) -> None:
        """Initialize a heating binary sensor."""
        self._client = client
        self._smart_home_id = smart_home_id
        self._device_id = device_id
        self._attr_unique_id = f"thermostat_is_heating_{device_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            manufacturer="Watts",
            name=f"Thermostat {zone}",
            model="BT-D03-RF",
            via_device=(DOMAIN, smart_home_id),
            suggested_area=zone,
        )

    def _device(self) -> JsonObject | None:
        """Return the cached device."""
        return self._client.get_device(self._smart_home_id, self._device_id)

    async def async_update(self) -> None:
        """Update the heating state from cached data."""
        device = self._device()
        self._attr_available = device is not None
        self._attr_is_on = (
            str(device["heating_up"]) != "0" if device is not None else None
        )
