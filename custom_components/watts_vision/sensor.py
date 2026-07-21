"""Sensor platform for Watts Vision."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DEVICE_TO_MODE_TYPE, DOMAIN, REPORTED_HEAT_MODES, REPORTED_TEMP_TYPES
from .coordinator import WattsVisionDataUpdateCoordinator
from .entity import WattsVisionEntity, WattsVisionEntityContext

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
    from homeassistant.helpers.typing import StateType

    from . import WattsVisionConfigEntry
    from .api import WattsVisionDevice


PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class WattsVisionSensorEntityDescription(SensorEntityDescription):
    """Describe a Watts Vision thermostat sensor."""

    unique_id_prefix: str
    value_fn: Callable[[WattsVisionDevice], StateType]


THERMOSTAT_SENSORS: tuple[WattsVisionSensorEntityDescription, ...] = (
    WattsVisionSensorEntityDescription(
        key="preset_mode",
        translation_key="preset_mode",
        device_class=SensorDeviceClass.ENUM,
        entity_registry_enabled_default=False,
        options=[mode.name.lower() for mode in REPORTED_HEAT_MODES],
        unique_id_prefix="thermostat_mode",
        value_fn=lambda device: DEVICE_TO_MODE_TYPE[device.mode].heat_mode.name.lower(),
    ),
    WattsVisionSensorEntityDescription(
        key="temperature_mode",
        translation_key="temperature_mode",
        device_class=SensorDeviceClass.ENUM,
        entity_registry_enabled_default=False,
        options=[mode.name.lower() for mode in REPORTED_TEMP_TYPES],
        unique_id_prefix="temperature_mode",
        value_fn=lambda device: DEVICE_TO_MODE_TYPE[device.mode].temp_type.name.lower(),
    ),
    WattsVisionSensorEntityDescription(
        key="air_temperature",
        translation_key="air_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        state_class=SensorStateClass.MEASUREMENT,
        unique_id_prefix="temperature_air",
        value_fn=lambda device: device.air_temperature,
    ),
    WattsVisionSensorEntityDescription(
        key="target_temperature",
        translation_key="target_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfTemperature.FAHRENHEIT,
        unique_id_prefix="target_temperature",
        value_fn=lambda device: device.target_temperature,
    ),
)


async def async_setup_entry(
    _hass: HomeAssistant,
    config_entry: WattsVisionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Watts Vision sensors."""
    runtime_data = config_entry.runtime_data
    coordinator = runtime_data.coordinator
    known_devices: set[tuple[str, str]] = set()
    known_homes: set[str] = set()

    @callback
    def async_add_new_entities() -> None:
        """Add sensor entities discovered in a later snapshot."""
        current_devices: dict[tuple[str, str], WattsVisionEntityContext] = {}
        current_homes = {
            smart_home.smart_home_id: smart_home
            for smart_home in coordinator.data.smart_homes
        }
        for smart_home in coordinator.data.smart_homes:
            smart_home_id = smart_home.smart_home_id
            for zone in smart_home.zones:
                for device in zone.devices:
                    current_devices[(smart_home_id, device.device_id)] = (
                        WattsVisionEntityContext(
                            smart_home_id=smart_home_id,
                            device_id=device.device_id,
                            zone=zone.label,
                            parent_device_id=runtime_data.parent_device_ids[
                                smart_home_id
                            ],
                        )
                    )

        new_devices = current_devices.keys() - known_devices
        new_homes = current_homes.keys() - known_homes
        entities: list[SensorEntity] = [
            WattsVisionDeviceSensor(coordinator, current_devices[key], description)
            for key in new_devices
            for description in THERMOSTAT_SENSORS
        ]
        for smart_home_id in new_homes:
            smart_home = current_homes[smart_home_id]
            entities.extend(
                (
                    WattsVisionLastCommunicationTimestampSensor(
                        coordinator,
                        smart_home_id,
                        smart_home.label,
                        smart_home.mac_address,
                    ),
                )
            )
        if entities:
            async_add_entities(entities)
            known_devices.update(new_devices)
            known_homes.update(new_homes)

    async_add_new_entities()
    config_entry.async_on_unload(coordinator.async_add_listener(async_add_new_entities))


class WattsVisionDeviceSensor(WattsVisionEntity, SensorEntity):
    """Represent a declaratively described thermostat sensor."""

    entity_description: WattsVisionSensorEntityDescription

    def __init__(
        self,
        coordinator: WattsVisionDataUpdateCoordinator,
        context: WattsVisionEntityContext,
        entity_description: WattsVisionSensorEntityDescription,
    ) -> None:
        """Initialize a thermostat sensor."""
        super().__init__(coordinator, context)
        self.entity_description = entity_description
        self._attr_unique_id = (
            f"{entity_description.unique_id_prefix}_{context.device_id}"
        )

    @property
    @override
    def native_value(self) -> StateType:
        """Return the sensor value from the latest snapshot."""
        device = self._device()
        return self.entity_description.value_fn(device) if device is not None else None


class WattsVisionHubSensor(
    CoordinatorEntity[WattsVisionDataUpdateCoordinator], SensorEntity
):
    """Base class for a sensor attached to a Watts Vision central unit."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WattsVisionDataUpdateCoordinator,
        smart_home_id: str,
        label: str,
        mac_address: str,
    ) -> None:
        """Initialize a central-unit sensor."""
        super().__init__(coordinator)
        self._smart_home_id = smart_home_id
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, smart_home_id)},
            manufacturer="Watts",
            name=f"Central Unit {label}",
            model="BT-CT02-RF",
            connections={(dr.CONNECTION_NETWORK_MAC, dr.format_mac(mac_address))},
        )

    @property
    @override
    def available(self) -> bool:
        """Return whether the coordinator and central unit are available."""
        return (
            super().available
            and self.coordinator.data.get_smart_home(self._smart_home_id) is not None
        )


class WattsVisionLastCommunicationTimestampSensor(WattsVisionHubSensor):
    """Represent the timestamp of the central unit's last communication."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "last_communication"

    def __init__(
        self,
        coordinator: WattsVisionDataUpdateCoordinator,
        smart_home_id: str,
        label: str,
        mac_address: str,
    ) -> None:
        """Initialize a last-communication timestamp sensor."""
        super().__init__(coordinator, smart_home_id, label, mac_address)
        self._attr_unique_id = f"last_communication_timestamp_{smart_home_id}"

    @property
    @override
    def native_value(self) -> datetime | None:
        """Return the estimated time of the last communication."""
        smart_home = self.coordinator.data.get_smart_home(self._smart_home_id)
        if smart_home is None:
            return None
        return dt_util.utcnow() - smart_home.last_communication.as_timedelta()
