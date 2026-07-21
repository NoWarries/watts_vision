"""Sensor platform for Watts Vision."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfRatio, UnitOfTemperature
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    AVAILABLE_HEAT_MODES,
    AVAILABLE_TEMP_TYPES,
    DEVICE_TO_MODE_TYPE,
    DOMAIN,
)
from .coordinator import WattsVisionDataUpdateCoordinator
from .entity import WattsVisionEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from . import WattsVisionConfigEntry


PARALLEL_UPDATES = 1


async def async_setup_entry(
    _hass: HomeAssistant,
    config_entry: WattsVisionConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Watts Vision sensors."""
    coordinator = config_entry.runtime_data
    sensors: list[SensorEntity] = []

    for smart_home in coordinator.data.smart_homes:
        smart_home_id = smart_home.smart_home_id
        for zone in smart_home.zones:
            for device in zone.devices:
                sensors.extend(
                    (
                        WattsVisionPresetModeSensor(
                            coordinator, smart_home_id, device.device_id, zone.label
                        ),
                        WattsVisionTemperatureModeSensor(
                            coordinator, smart_home_id, device.device_id, zone.label
                        ),
                        WattsVisionTemperatureSensor(
                            coordinator, smart_home_id, device.device_id, zone.label
                        ),
                        WattsVisionSetTemperatureSensor(
                            coordinator, smart_home_id, device.device_id, zone.label
                        ),
                        WattsVisionBatterySensor(
                            coordinator, smart_home_id, device.device_id, zone.label
                        ),
                    )
                )

        sensors.append(
            WattsVisionLastCommunicationSensor(
                coordinator,
                smart_home_id,
                smart_home.label,
                smart_home.mac_address,
            )
        )

    async_add_entities(sensors)


class WattsVisionDeviceSensor(WattsVisionEntity, SensorEntity):
    """Base class for Watts Vision thermostat sensors."""

    def __init__(
        self,
        coordinator: WattsVisionDataUpdateCoordinator,
        smart_home_id: str,
        device_id: str,
        zone: str,
    ) -> None:
        """Initialize a thermostat sensor."""
        super().__init__(coordinator, smart_home_id, device_id, zone)


class WattsVisionPresetModeSensor(WattsVisionDeviceSensor):
    """Represent the active Watts Vision preset mode."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = [
        mode.value.capitalize() for mode in AVAILABLE_HEAT_MODES
    ]
    _attr_translation_key = "preset_mode"

    def __init__(
        self,
        coordinator: WattsVisionDataUpdateCoordinator,
        smart_home_id: str,
        device_id: str,
        zone: str,
    ) -> None:
        """Initialize a preset mode sensor."""
        super().__init__(coordinator, smart_home_id, device_id, zone)
        self._attr_unique_id = f"thermostat_mode_{device_id}"

    @property
    def native_value(self) -> str | None:
        """Return the active preset mode."""
        device = self._device()
        return (
            DEVICE_TO_MODE_TYPE[device.mode].heat_mode.value.capitalize()
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
        coordinator: WattsVisionDataUpdateCoordinator,
        smart_home_id: str,
        device_id: str,
        zone: str,
    ) -> None:
        """Initialize a temperature mode sensor."""
        super().__init__(coordinator, smart_home_id, device_id, zone)
        self._attr_unique_id = f"temperature_mode_{device_id}"

    @property
    def native_value(self) -> str | None:
        """Return the active temperature mode."""
        device = self._device()
        return (
            DEVICE_TO_MODE_TYPE[device.mode].temp_type.value.capitalize()
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
        coordinator: WattsVisionDataUpdateCoordinator,
        smart_home_id: str,
        device_id: str,
        zone: str,
    ) -> None:
        """Initialize a battery sensor."""
        super().__init__(coordinator, smart_home_id, device_id, zone)
        self._attr_unique_id = f"battery_{device_id}"

    @property
    def native_value(self) -> int | None:
        """Return the battery state."""
        device = self._device()
        if device is None:
            return None
        return 0 if device.battery_low else 100


class WattsVisionTemperatureSensor(WattsVisionDeviceSensor):
    """Represent the current air temperature."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_translation_key = "air_temperature"

    def __init__(
        self,
        coordinator: WattsVisionDataUpdateCoordinator,
        smart_home_id: str,
        device_id: str,
        zone: str,
    ) -> None:
        """Initialize an air-temperature sensor."""
        super().__init__(coordinator, smart_home_id, device_id, zone)
        self._attr_unique_id = f"temperature_air_{device_id}"

    @property
    def native_value(self) -> float | None:
        """Return the current air temperature."""
        device = self._device()
        return device.air_temperature if device is not None else None


class WattsVisionSetTemperatureSensor(WattsVisionDeviceSensor):
    """Represent the active target temperature."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.FAHRENHEIT
    _attr_translation_key = "target_temperature"

    def __init__(
        self,
        coordinator: WattsVisionDataUpdateCoordinator,
        smart_home_id: str,
        device_id: str,
        zone: str,
    ) -> None:
        """Initialize a target-temperature sensor."""
        super().__init__(coordinator, smart_home_id, device_id, zone)
        self._attr_unique_id = f"target_temperature_{device_id}"

    @property
    def native_value(self) -> float | None:
        """Return the active target temperature."""
        device = self._device()
        if device is None:
            return None
        return device.target_temperature


class WattsVisionLastCommunicationSensor(
    CoordinatorEntity[WattsVisionDataUpdateCoordinator], SensorEntity
):
    """Represent the last communication with a Watts Vision central unit."""

    _attr_has_entity_name = True
    _attr_translation_key = "last_communication"

    def __init__(
        self,
        coordinator: WattsVisionDataUpdateCoordinator,
        smart_home_id: str,
        label: str,
        mac_address: str,
    ) -> None:
        """Initialize a last-communication sensor."""
        super().__init__(coordinator)
        self._smart_home_id = smart_home_id
        self._attr_unique_id = f"last_communication_{smart_home_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, smart_home_id)},
            manufacturer="Watts",
            name=f"Central Unit {label}",
            model="BT-CT02-RF",
            connections={(CONNECTION_NETWORK_MAC, mac_address)},
        )

    @property
    def native_value(self) -> str | None:
        """Return the last communication value."""
        smart_home = self.coordinator.data.get_smart_home(self._smart_home_id)
        if smart_home is None:
            return None
        difference = smart_home.last_communication
        return (
            f"{difference.days} days, {difference.hours} hours, "
            f"{difference.minutes} minutes and {difference.seconds} seconds."
        )
