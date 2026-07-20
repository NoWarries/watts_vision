"""Sensor platform for Watts Vision."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any, ClassVar

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfRatio, UnitOfTemperature
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo

from .const import (
    AVAILABLE_HEAT_MODES,
    AVAILABLE_TEMP_TYPES,
    DEVICE_TO_MODE_TYPE,
    DOMAIN,
    TEMP_TYPE_TO_DEVICE,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from . import WattsVisionConfigEntry
    from .watts_api import JsonObject, WattsApi

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=120)


async def async_setup_entry(
    _hass: HomeAssistant,
    config_entry: WattsVisionConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Watts Vision sensors."""
    client = config_entry.runtime_data
    sensors: list[SensorEntity] = []

    for smart_home in client.get_smart_homes():
        smart_home_id = str(smart_home["smarthome_id"])
        for zone in smart_home.get("zones") or []:
            zone_label = str(zone["zone_label"])
            for device in zone.get("devices") or []:
                device_id = str(device["id"])
                sensors.extend(
                    (
                        WattsVisionPresetModeSensor(
                            client, smart_home_id, device_id, zone_label
                        ),
                        WattsVisionTemperatureModeSensor(
                            client, smart_home_id, device_id, zone_label
                        ),
                        WattsVisionTemperatureSensor(
                            client, smart_home_id, device_id, zone_label
                        ),
                        WattsVisionSetTemperatureSensor(
                            client, smart_home_id, device_id, zone_label
                        ),
                        WattsVisionBatterySensor(
                            client, smart_home_id, device_id, zone_label
                        ),
                    )
                )

        sensors.append(
            WattsVisionLastCommunicationSensor(
                client,
                smart_home_id,
                str(smart_home["label"]),
                str(smart_home["mac_address"]),
            )
        )

    async_add_entities(sensors, update_before_add=True)


class WattsVisionDeviceSensor(SensorEntity):
    """Base class for Watts Vision thermostat sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        client: WattsApi,
        smart_home_id: str,
        device_id: str,
        zone: str,
    ) -> None:
        """Initialize a thermostat sensor."""
        self._client = client
        self._smart_home_id = smart_home_id
        self._device_id = device_id
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


class WattsVisionPresetModeSensor(WattsVisionDeviceSensor):
    """Represent the active Watts Vision preset mode."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = [
        mode.value.capitalize() for mode in AVAILABLE_HEAT_MODES
    ]
    _attr_translation_key = "preset_mode"

    def __init__(
        self,
        client: WattsApi,
        smart_home_id: str,
        device_id: str,
        zone: str,
    ) -> None:
        """Initialize a preset mode sensor."""
        super().__init__(client, smart_home_id, device_id, zone)
        self._attr_unique_id = f"thermostat_mode_{device_id}"

    async def async_update(self) -> None:
        """Update the active preset mode from cached data."""
        device = self._device()
        self._attr_available = device is not None
        self._attr_native_value = (
            DEVICE_TO_MODE_TYPE[str(device["gv_mode"])].heat_mode.value.capitalize()
            if device is not None
            else None
        )


class WattsVisionTemperatureModeSensor(WattsVisionDeviceSensor):
    """Represent the active Watts Vision temperature mode."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = [
        mode.value.capitalize() for mode in AVAILABLE_TEMP_TYPES
    ]
    _attr_translation_key = "temperature_mode"

    def __init__(
        self,
        client: WattsApi,
        smart_home_id: str,
        device_id: str,
        zone: str,
    ) -> None:
        """Initialize a temperature mode sensor."""
        super().__init__(client, smart_home_id, device_id, zone)
        self._attr_unique_id = f"temperature_mode_{device_id}"

    async def async_update(self) -> None:
        """Update the temperature mode from cached data."""
        device = self._device()
        self._attr_available = device is not None
        self._attr_native_value = (
            DEVICE_TO_MODE_TYPE[str(device["gv_mode"])].temp_type.value.capitalize()
            if device is not None
            else None
        )


class WattsVisionBatterySensor(WattsVisionDeviceSensor):
    """Represent the Watts Vision device battery state."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = UnitOfRatio.PERCENTAGE
    _attr_translation_key = "battery"

    def __init__(
        self,
        client: WattsApi,
        smart_home_id: str,
        device_id: str,
        zone: str,
    ) -> None:
        """Initialize a battery sensor."""
        super().__init__(client, smart_home_id, device_id, zone)
        self._attr_unique_id = f"battery_{device_id}"

    async def async_update(self) -> None:
        """Update the battery state from cached data."""
        device = self._device()
        self._attr_available = device is not None
        if device is None:
            self._attr_native_value = None
            return
        if str(device.get("error_code")) == "1":
            _LOGGER.warning(
                "Battery is malfunctioning or almost empty for device %s",
                self._device_id,
            )
            self._attr_native_value = 0
        else:
            self._attr_native_value = 100


class WattsVisionTemperatureSensor(WattsVisionDeviceSensor):
    """Represent the current air temperature."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_translation_key = "air_temperature"

    def __init__(
        self,
        client: WattsApi,
        smart_home_id: str,
        device_id: str,
        zone: str,
    ) -> None:
        """Initialize an air-temperature sensor."""
        super().__init__(client, smart_home_id, device_id, zone)
        self._attr_unique_id = f"temperature_air_{device_id}"

    async def async_update(self) -> None:
        """Update the air temperature from cached data."""
        device = self._device()
        self._attr_available = device is not None
        self._attr_native_value = (
            float(device["temperature_air"]) / 10 if device is not None else None
        )


class WattsVisionSetTemperatureSensor(WattsVisionDeviceSensor):
    """Represent the active target temperature."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_translation_key = "target_temperature"

    def __init__(
        self,
        client: WattsApi,
        smart_home_id: str,
        device_id: str,
        zone: str,
    ) -> None:
        """Initialize a target-temperature sensor."""
        super().__init__(client, smart_home_id, device_id, zone)
        self._attr_unique_id = f"target_temperature_{device_id}"

    async def async_update(self) -> None:
        """Update the target temperature from cached data."""
        device = self._device()
        self._attr_available = device is not None
        if device is None or str(device["gv_mode"]) == "1":
            self._attr_native_value = None
            return
        temperature_key = TEMP_TYPE_TO_DEVICE[
            DEVICE_TO_MODE_TYPE[str(device["gv_mode"])].temp_type
        ]
        self._attr_native_value = float(device[temperature_key]) / 10


class WattsVisionLastCommunicationSensor(SensorEntity):
    """Represent the last communication with a Watts Vision central unit."""

    _attr_has_entity_name = True
    _attr_translation_key = "last_communication"

    def __init__(
        self,
        client: WattsApi,
        smart_home_id: str,
        label: str,
        mac_address: str,
    ) -> None:
        """Initialize a last-communication sensor."""
        self._client = client
        self._smart_home_id = smart_home_id
        self._attr_unique_id = f"last_communication_{smart_home_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, smart_home_id)},
            manufacturer="Watts",
            name=f"Central Unit {label}",
            model="BT-CT02-RF",
            connections={(CONNECTION_NETWORK_MAC, mac_address)},
        )

    async def async_update(self) -> None:
        """Fetch and update the last communication value."""
        data: dict[str, Any] = await self.hass.async_add_executor_job(
            self._client.get_last_communication,
            self._smart_home_id,
        )
        difference = data["diffObj"]
        self._attr_native_value = (
            f"{difference['days']} days, {difference['hours']} hours, "
            f"{difference['minutes']} minutes and {difference['seconds']} seconds."
        )
