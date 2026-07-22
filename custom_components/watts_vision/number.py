"""Number platform for Watts Vision thermostat settings."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberMode,
    RestoreNumber,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import callback
from homeassistant.exceptions import ServiceValidationError

from .const import (
    DEFAULT_BOOST_DURATION_MINUTES,
    DOMAIN,
    MAX_BOOST_DURATION_MINUTES,
    MIN_BOOST_DURATION_MINUTES,
)
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
    """Set up per-thermostat Boost duration settings."""
    runtime_data = config_entry.runtime_data
    coordinator = runtime_data.coordinator
    known_devices: set[tuple[str, str]] = set()

    @callback
    def async_add_new_entities() -> None:
        """Add settings for thermostats discovered after setup."""
        current_devices: dict[tuple[str, str], WattsVisionEntityContext] = {}
        for smart_home in coordinator.data.smart_homes:
            smart_home_id = smart_home.smart_home_id
            for zone in smart_home.zones:
                for device in zone.devices:
                    key = (smart_home_id, device.device_id)
                    current_devices[key] = WattsVisionEntityContext(
                        smart_home_id=smart_home_id,
                        device_id=device.device_id,
                        zone=zone.label,
                        parent_device_id=runtime_data.parent_device_ids[smart_home_id],
                    )
        new_devices = current_devices.keys() - known_devices
        if new_devices:
            async_add_entities(
                WattsBoostDurationNumber(
                    coordinator,
                    current_devices[key],
                    runtime_data.boost_durations,
                )
                for key in new_devices
            )
            known_devices.update(new_devices)

    async_add_new_entities()
    config_entry.async_on_unload(coordinator.async_add_listener(async_add_new_entities))


class WattsBoostDurationNumber(WattsVisionEntity, RestoreNumber):
    """Configure the duration used when the Boost preset is selected."""

    _attr_device_class = NumberDeviceClass.DURATION
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_max_value = float(MAX_BOOST_DURATION_MINUTES)
    _attr_native_min_value = float(MIN_BOOST_DURATION_MINUTES)
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_translation_key = "boost_duration"

    def __init__(
        self,
        coordinator: WattsVisionDataUpdateCoordinator,
        context: WattsVisionEntityContext,
        boost_durations: dict[tuple[str, str], int],
    ) -> None:
        """Initialize a restored Boost duration setting."""
        super().__init__(coordinator, context)
        self._duration_key = (context.smart_home_id, context.device_id)
        self._boost_durations = boost_durations
        duration = boost_durations.setdefault(
            self._duration_key,
            DEFAULT_BOOST_DURATION_MINUTES,
        )
        self._attr_native_value = float(duration)
        self._attr_unique_id = f"boost_duration_{context.device_id}"

    @override
    async def async_added_to_hass(self) -> None:
        """Restore the user's last selected duration."""
        await super().async_added_to_hass()
        restored = await self.async_get_last_number_data()
        if restored is None or restored.native_value is None:
            return
        restored_value = restored.native_value
        if (
            restored_value.is_integer()
            and self.native_min_value <= restored_value <= self.native_max_value
        ):
            duration = int(restored_value)
            self._boost_durations[self._duration_key] = duration
            self._attr_native_value = restored_value

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Store a whole-minute duration without sending a thermostat command."""
        if (
            not value.is_integer()
            or not self.native_min_value <= value <= self.native_max_value
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="boost_duration_invalid",
            )
        duration = int(value)
        self._boost_durations[self._duration_key] = duration
        self._attr_native_value = value
        self.async_write_ha_state()
