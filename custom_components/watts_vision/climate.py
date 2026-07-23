"""Climate platform for Watts Vision."""

from __future__ import annotations

import logging
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any, Final, override

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util.unit_conversion import TemperatureConverter

from .api import (
    WattsVisionCommunicationStaleError,
    WattsVisionDevice,
    WattsVisionDeviceMode,
    WattsVisionError,
    WattsVisionResponseError,
)
from .const import (
    DEFAULT_BOOST_DURATION_MINUTES,
    DEVICE_TO_MODE_TYPE,
    DOMAIN,
    SECONDS_PER_MINUTE,
    HeatMode,
    temperature_for_type,
)
from .entity import WattsVisionEntity, WattsVisionEntityContext

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import WattsVisionConfigEntry
    from .coordinator import WattsVisionDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 0

_CELSIUS_STEP: Final = Decimal("0.5")
_FROST_CELSIUS: Final = 7.0
_FROST_FAHRENHEIT: Final = 44.6

PROGRAM_MODES = frozenset(
    {
        WattsVisionDeviceMode.PROGRAM_BOOST,
        WattsVisionDeviceMode.PROGRAM_COMFORT,
        WattsVisionDeviceMode.PROGRAM_ECO,
        WattsVisionDeviceMode.PROGRAM_UNSPECIFIED,
    }
)
TARGET_COMMANDABLE_MODES = frozenset(
    {
        WattsVisionDeviceMode.COMFORT,
        WattsVisionDeviceMode.ECO,
        WattsVisionDeviceMode.BOOST,
    }
)
STABLE_RESTORE_MODES = frozenset(
    {
        WattsVisionDeviceMode.COMFORT,
        WattsVisionDeviceMode.ECO,
        WattsVisionDeviceMode.FROST,
        WattsVisionDeviceMode.PROGRAM_UNSPECIFIED,
    }
)


PRESET_MODE_TO_DEVICE: Final = {
    HeatMode.COMFORT.value: WattsVisionDeviceMode.COMFORT,
    HeatMode.ECO.value: WattsVisionDeviceMode.ECO,
    HeatMode.FROST.value: WattsVisionDeviceMode.FROST,
    HeatMode.BOOST.value: WattsVisionDeviceMode.BOOST,
}


async def async_setup_entry(
    _hass: HomeAssistant,
    config_entry: WattsVisionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Watts Vision climate entities."""
    runtime_data = config_entry.runtime_data
    coordinator = runtime_data.coordinator
    known_devices: set[tuple[str, str]] = set()

    @callback
    def async_add_new_entities() -> None:
        """Add thermostats discovered in a later coordinator snapshot."""
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
                WattsThermostat(
                    coordinator,
                    current_devices[key],
                    runtime_data.boost_durations,
                )
                for key in new_devices
            )
            known_devices.update(new_devices)

    async_add_new_entities()
    config_entry.async_on_unload(coordinator.async_add_listener(async_add_new_entities))


class WattsThermostat(WattsVisionEntity, ClimateEntity):
    """Represent a Watts Vision thermostat."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5

    def __init__(
        self,
        coordinator: WattsVisionDataUpdateCoordinator,
        context: WattsVisionEntityContext,
        boost_durations: dict[tuple[str, str], int] | None = None,
    ) -> None:
        """Initialize a thermostat entity."""
        super().__init__(coordinator, context)
        self._boost_duration_key = (context.smart_home_id, context.device_id)
        self._boost_durations = boost_durations if boost_durations is not None else {}
        self._boost_durations.setdefault(
            self._boost_duration_key,
            DEFAULT_BOOST_DURATION_MINUTES,
        )
        self._attr_unique_id = f"watts_thermostat_{context.device_id}"
        self._attr_name = None
        self._attr_translation_key = "thermostat"
        self._attr_preset_modes = list(PRESET_MODE_TO_DEVICE)
        self._previous_device_mode = WattsVisionDeviceMode.COMFORT
        self._update_from_coordinator()

    def _update_from_coordinator(self) -> None:
        """Update thermostat attributes from effective coordinator data."""
        device = self._device()
        if device is None:
            return

        device_mode = device.mode
        stable_mode = _stable_restore_mode(device_mode)
        if stable_mode is not None:
            self._previous_device_mode = stable_mode

        self._attr_current_temperature = _fahrenheit_to_celsius(device.air_temperature)
        self._attr_min_temp = _fahrenheit_to_celsius(device.min_temperature)
        self._attr_max_temp = _fahrenheit_to_celsius(device.max_temperature)

        if device_mode is WattsVisionDeviceMode.OFF:
            self._attr_hvac_action = HVACAction.OFF
        elif not device.is_heating:
            self._attr_hvac_action = HVACAction.IDLE
        elif device.is_cooling:
            self._attr_hvac_action = HVACAction.COOLING
        else:
            self._attr_hvac_action = HVACAction.HEATING

        seasonal_mode = HVACMode.COOL if device.is_cooling else HVACMode.HEAT
        self._attr_hvac_modes = [seasonal_mode, HVACMode.AUTO, HVACMode.OFF]
        mode_info = DEVICE_TO_MODE_TYPE[device_mode]
        if device_mode is WattsVisionDeviceMode.OFF:
            self._attr_hvac_mode = HVACMode.OFF
            self._attr_preset_mode = None
            self._attr_target_temperature = None
        elif device_mode in PROGRAM_MODES:
            self._attr_hvac_mode = HVACMode.AUTO
            self._attr_preset_mode = None
            self._attr_target_temperature = _optional_celsius(device.target_temperature)
        else:
            self._attr_hvac_mode = seasonal_mode
            self._attr_preset_mode = (
                mode_info.heat_mode.value
                if mode_info.heat_mode
                in {HeatMode.COMFORT, HeatMode.ECO, HeatMode.FROST, HeatMode.BOOST}
                else None
            )
            self._attr_target_temperature = _optional_celsius(device.target_temperature)

        features = (
            ClimateEntityFeature.PRESET_MODE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )
        if device_mode in TARGET_COMMANDABLE_MODES:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        self._attr_supported_features = features
        _LOGGER.debug(
            "Updated Watts Vision thermostat: mode=%s target=%s current=%s",
            device_mode,
            self._attr_target_temperature,
            self._attr_current_temperature,
        )

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_from_coordinator()
        self.async_write_ha_state()

    @override
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set a deterministic Home Assistant HVAC mode."""
        device = self._require_device()
        seasonal_mode = HVACMode.COOL if device.is_cooling else HVACMode.HEAT
        if hvac_mode is HVACMode.OFF:
            device_mode = WattsVisionDeviceMode.OFF
            value = 0.0
        elif hvac_mode is HVACMode.AUTO:
            device_mode = WattsVisionDeviceMode.PROGRAM_UNSPECIFIED
            value = device.target_temperature or device.comfort_temperature
        elif hvac_mode is seasonal_mode:
            device_mode = WattsVisionDeviceMode.COMFORT
            value = device.comfort_temperature
        else:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="hvac_mode_unsupported",
                translation_placeholders={"mode": hvac_mode},
            )
        await self._async_push_temperature(
            value,
            device_mode,
            update_target=False,
        )

    @override
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set a confirmed commandable thermostat preset."""
        device = self._require_device()
        try:
            device_mode = PRESET_MODE_TO_DEVICE[preset_mode]
        except KeyError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="preset_mode_unsupported",
                translation_placeholders={"mode": preset_mode},
            ) from err
        value = (
            self._boost_start_temperature(device)
            if device_mode is WattsVisionDeviceMode.BOOST
            else self._temperature_for_mode(device, device_mode)
        )
        await self._async_push_temperature(
            value,
            device_mode,
            update_target=device_mode is WattsVisionDeviceMode.BOOST,
        )

    @override
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a target on the device's confirmed Celsius grid."""
        device = self._require_device()
        if device.mode not in TARGET_COMMANDABLE_MODES:
            mode_info = DEVICE_TO_MODE_TYPE[device.mode]
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="temperature_mode_unsupported",
                translation_placeholders={"mode": mode_info.heat_mode.value},
            )
        requested_celsius = float(kwargs[ATTR_TEMPERATURE])
        quantized_celsius = _quantize_celsius(requested_celsius, device)
        value = _celsius_to_fahrenheit(quantized_celsius)
        await self._async_push_temperature(
            value,
            device.mode,
            update_target=True,
        )

    @override
    async def async_turn_on(self) -> None:
        """Turn on using the last stable commandable mode."""
        device = self._require_device()
        if device.mode is not WattsVisionDeviceMode.OFF:
            return
        device_mode = self._previous_device_mode
        if device_mode not in STABLE_RESTORE_MODES:
            device_mode = WattsVisionDeviceMode.COMFORT
        value = self._temperature_for_mode(device, device_mode)
        await self._async_push_temperature(
            value,
            device_mode,
            update_target=False,
        )

    @override
    async def async_turn_off(self) -> None:
        """Turn off the thermostat."""
        device = self._require_device()
        if device.mode is WattsVisionDeviceMode.OFF:
            return
        await self.async_set_hvac_mode(HVACMode.OFF)

    def _require_device(self) -> WattsVisionDevice:
        """Return the cached device or raise when unavailable."""
        device = self._device()
        if device is None or not self.available:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_unavailable",
                translation_placeholders={"device_id": self._device_id},
            )
        return device

    @staticmethod
    def _temperature_for_mode(
        device: WattsVisionDevice,
        mode: WattsVisionDeviceMode,
    ) -> float:
        """Return the Fahrenheit command value for a confirmed mode."""
        if mode is WattsVisionDeviceMode.FROST:
            return _FROST_FAHRENHEIT
        if mode is WattsVisionDeviceMode.PROGRAM_UNSPECIFIED:
            return device.target_temperature or device.comfort_temperature
        temperature_type = DEVICE_TO_MODE_TYPE[mode].temp_type
        return temperature_for_type(device, temperature_type)

    @staticmethod
    def _boost_start_temperature(device: WattsVisionDevice) -> float:
        """Choose a Boost target that requests work in the active season."""
        active = device.target_temperature or device.comfort_temperature
        air_celsius = Decimal(str(_fahrenheit_to_celsius(device.air_temperature)))
        if device.is_cooling:
            demand_tick = (air_celsius / _CELSIUS_STEP).to_integral_value(
                rounding=ROUND_CEILING
            ) - 1
            demand = _celsius_to_fahrenheit(float(demand_tick * _CELSIUS_STEP))
            return max(
                min(
                    active,
                    device.boost_temperature,
                    demand,
                    device.max_temperature,
                ),
                device.min_temperature,
            )

        demand_tick = (air_celsius / _CELSIUS_STEP).to_integral_value(
            rounding=ROUND_FLOOR
        ) + 1
        demand = _celsius_to_fahrenheit(float(demand_tick * _CELSIUS_STEP))
        return min(
            max(
                active,
                device.boost_temperature,
                demand,
                device.min_temperature,
            ),
            device.max_temperature,
        )

    async def _async_push_temperature(
        self,
        value: float,
        device_mode: WattsVisionDeviceMode,
        *,
        update_target: bool,
    ) -> None:
        """Push a command through coordinator reconciliation."""
        boost_duration = (
            self._boost_durations[self._boost_duration_key] * SECONDS_PER_MINUTE
            if device_mode is WattsVisionDeviceMode.BOOST
            else None
        )
        try:
            await self.coordinator.async_set_device_temperature(
                self._smart_home_id,
                self._device_id,
                value,
                device_mode,
                boost_duration=boost_duration,
                update_target=update_target,
            )
        except WattsVisionCommunicationStaleError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="smart_home_not_communicating",
                translation_placeholders={"seconds": str(err.age_seconds)},
            ) from err
        except WattsVisionResponseError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="thermostat_update_rejected",
            ) from err
        except WattsVisionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="thermostat_update_failed",
            ) from err


def _stable_restore_mode(
    mode: WattsVisionDeviceMode,
) -> WattsVisionDeviceMode | None:
    """Normalize a reported mode into a safe restart target."""
    if mode in PROGRAM_MODES:
        return WattsVisionDeviceMode.PROGRAM_UNSPECIFIED
    return mode if mode in STABLE_RESTORE_MODES else None


def _fahrenheit_to_celsius(value: float) -> float:
    """Convert an API Fahrenheit value for Home Assistant."""
    return TemperatureConverter.convert(
        value,
        UnitOfTemperature.FAHRENHEIT,
        UnitOfTemperature.CELSIUS,
    )


def _celsius_to_fahrenheit(value: float) -> float:
    """Convert a quantized Celsius value without binary arithmetic drift."""
    converted = Decimal(str(value)) * Decimal("1.8") + Decimal(32)
    return float(converted)


def _optional_celsius(value: float | None) -> float | None:
    """Convert an optional Fahrenheit temperature."""
    return _fahrenheit_to_celsius(value) if value is not None else None


def _quantize_celsius(value: float, device: WattsVisionDevice) -> float:
    """Clamp and quantize one request to the thermostat's 0.5 °C grid."""
    requested = Decimal(str(value))
    minimum = Decimal(str(_fahrenheit_to_celsius(device.min_temperature)))
    maximum = Decimal(str(_fahrenheit_to_celsius(device.max_temperature)))
    minimum_tick = (minimum / _CELSIUS_STEP).to_integral_value(rounding=ROUND_CEILING)
    maximum_tick = (maximum / _CELSIUS_STEP).to_integral_value(rounding=ROUND_FLOOR)
    requested_tick = (requested / _CELSIUS_STEP).to_integral_value(
        rounding=ROUND_HALF_UP
    )
    clamped_tick = min(max(requested_tick, minimum_tick), maximum_tick)
    return float(clamped_tick * _CELSIUS_STEP)
