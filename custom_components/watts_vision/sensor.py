"""Sensor platform for Watts Vision."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, override

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfRatio, UnitOfTemperature
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE_TO_MODE_TYPE, DOMAIN, REPORTED_HEAT_MODES, REPORTED_TEMP_TYPES
from .coordinator import WattsVisionDataUpdateCoordinator
from .entity import WattsVisionEntity, WattsVisionEntityContext

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import WattsVisionConfigEntry


PARALLEL_UPDATES = 1


async def async_setup_entry(
    _hass: HomeAssistant,
    config_entry: WattsVisionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Watts Vision sensors."""
    runtime_data = config_entry.runtime_data
    coordinator = runtime_data.coordinator
    sensors: list[SensorEntity] = []

    for smart_home in coordinator.data.smart_homes:
        smart_home_id = smart_home.smart_home_id
        for zone in smart_home.zones:
            for device in zone.devices:
                context = WattsVisionEntityContext(
                    smart_home_id=smart_home_id,
                    device_id=device.device_id,
                    zone=zone.label,
                    parent_device_id=runtime_data.parent_device_ids[smart_home_id],
                )
                sensors.extend(
                    (
                        WattsVisionPresetModeSensor(coordinator, context),
                        WattsVisionTemperatureModeSensor(coordinator, context),
                        WattsVisionTemperatureSensor(coordinator, context),
                        WattsVisionSetTemperatureSensor(coordinator, context),
                        WattsVisionBatterySensor(coordinator, context),
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
        context: WattsVisionEntityContext,
    ) -> None:
        """Initialize a thermostat sensor."""
        super().__init__(coordinator, context)


class WattsVisionPresetModeSensor(WattsVisionDeviceSensor):
    """Represent the active Watts Vision preset mode."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = [
        mode.value.capitalize() for mode in REPORTED_HEAT_MODES
    ]
    _attr_translation_key = "preset_mode"

    def __init__(
        self,
        coordinator: WattsVisionDataUpdateCoordinator,
        context: WattsVisionEntityContext,
    ) -> None:
        """Initialize a preset mode sensor."""
        super().__init__(coordinator, context)
        self._attr_unique_id = f"thermostat_mode_{context.device_id}"

    @property
    @override
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
        mode.value.capitalize() for mode in REPORTED_TEMP_TYPES
    ]
    _attr_translation_key = "temperature_mode"

    def __init__(
        self,
        coordinator: WattsVisionDataUpdateCoordinator,
        context: WattsVisionEntityContext,
    ) -> None:
        """Initialize a temperature mode sensor."""
        super().__init__(coordinator, context)
        self._attr_unique_id = f"temperature_mode_{context.device_id}"

    @property
    @override
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
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = UnitOfRatio.PERCENTAGE
    _attr_translation_key = "battery"

    def __init__(
        self,
        coordinator: WattsVisionDataUpdateCoordinator,
        context: WattsVisionEntityContext,
    ) -> None:
        """Initialize a battery sensor."""
        super().__init__(coordinator, context)
        self._attr_unique_id = f"battery_{context.device_id}"

    @property
    @override
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
        context: WattsVisionEntityContext,
    ) -> None:
        """Initialize an air-temperature sensor."""
        super().__init__(coordinator, context)
        self._attr_unique_id = f"temperature_air_{context.device_id}"

    @property
    @override
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
        context: WattsVisionEntityContext,
    ) -> None:
        """Initialize a target-temperature sensor."""
        super().__init__(coordinator, context)
        self._attr_unique_id = f"target_temperature_{context.device_id}"

    @property
    @override
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
    _attr_entity_category = EntityCategory.DIAGNOSTIC
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
    @override
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
