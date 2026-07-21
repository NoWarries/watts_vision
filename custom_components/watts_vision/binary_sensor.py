"""Binary sensor platform for Watts Vision."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import callback

from .entity import WattsVisionEntity, WattsVisionEntityContext

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import WattsVisionConfigEntry
    from .coordinator import WattsVisionDataUpdateCoordinator


PARALLEL_UPDATES = 1


async def async_setup_entry(
    _hass: HomeAssistant,
    config_entry: WattsVisionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Watts Vision binary sensors."""
    runtime_data = config_entry.runtime_data
    coordinator = runtime_data.coordinator
    known_devices: set[tuple[str, str]] = set()

    @callback
    def async_add_new_entities() -> None:
        """Add binary sensors discovered in a later snapshot."""
        current_devices: dict[tuple[str, str], WattsVisionEntityContext] = {}
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
        if new_devices:
            async_add_entities(
                entity
                for key in new_devices
                for entity in (
                    WattsVisionHeatingBinarySensor(
                        coordinator,
                        current_devices[key],
                    ),
                    WattsVisionBatteryLowBinarySensor(
                        coordinator,
                        current_devices[key],
                    ),
                )
            )
            known_devices.update(new_devices)

    async_add_new_entities()
    config_entry.async_on_unload(coordinator.async_add_listener(async_add_new_entities))


class WattsVisionHeatingBinarySensor(WattsVisionEntity, BinarySensorEntity):
    """Represent whether a Watts Vision thermostat is actively heating."""

    _attr_device_class = BinarySensorDeviceClass.HEAT
    _attr_entity_registry_enabled_default = False
    _attr_translation_key = "heating"

    def __init__(
        self,
        coordinator: WattsVisionDataUpdateCoordinator,
        context: WattsVisionEntityContext,
    ) -> None:
        """Initialize a heating binary sensor."""
        super().__init__(coordinator, context)
        self._attr_unique_id = f"thermostat_is_heating_{context.device_id}"

    @property
    @override
    def is_on(self) -> bool | None:
        """Return whether the thermostat is actively heating."""
        device = self._device()
        return device.is_heating if device is not None else None


class WattsVisionBatteryLowBinarySensor(WattsVisionEntity, BinarySensorEntity):
    """Represent the thermostat's actual low-battery flag."""

    _attr_device_class = BinarySensorDeviceClass.BATTERY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "battery_low"

    def __init__(
        self,
        coordinator: WattsVisionDataUpdateCoordinator,
        context: WattsVisionEntityContext,
    ) -> None:
        """Initialize a low-battery binary sensor."""
        super().__init__(coordinator, context)
        self._attr_unique_id = f"battery_low_{context.device_id}"

    @property
    @override
    def is_on(self) -> bool | None:
        """Return whether the thermostat reports a low battery."""
        device = self._device()
        return device.battery_low if device is not None else None
