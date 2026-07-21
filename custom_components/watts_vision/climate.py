"""Climate platform for Watts Vision."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar, override

from homeassistant.components.climate import (
    ATTR_TEMPERATURE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .api import (
    WattsVisionDevice,
    WattsVisionDeviceMode,
    WattsVisionError,
    WattsVisionResponseError,
)
from .const import (
    AVAILABLE_HEAT_MODES,
    AVAILABLE_TEMP_TYPES,
    DEVICE_TO_MODE_TYPE,
    DOMAIN,
    HEAT_MODE_TO_DEVICE,
    TEMP_TYPE_TO_STATE_ATTRIBUTE,
    HeatMode,
    TempType,
    temperature_for_type,
)
from .entity import WattsVisionEntity, WattsVisionEntityContext

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import WattsVisionConfigEntry
    from .coordinator import WattsVisionDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 1


async def async_setup_entry(
    _hass: HomeAssistant,
    config_entry: WattsVisionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Watts Vision climate entities."""
    runtime_data = config_entry.runtime_data
    coordinator = runtime_data.coordinator
    entities: list[ClimateEntity] = []
    for smart_home in coordinator.data.smart_homes:
        smart_home_id = smart_home.smart_home_id
        for zone in smart_home.zones:
            entities.extend(
                WattsThermostat(
                    coordinator,
                    WattsVisionEntityContext(
                        smart_home_id=smart_home_id,
                        device_id=device.device_id,
                        zone=zone.label,
                        parent_device_id=runtime_data.parent_device_ids[smart_home_id],
                    ),
                    device.api_device_id,
                )
                for device in zone.devices
            )

    async_add_entities(entities)


class WattsThermostat(WattsVisionEntity, ClimateEntity):
    """Represent a Watts Vision thermostat."""

    _attr_hvac_modes: ClassVar[list[HVACMode]] = [
        HVACMode.HEAT,
        HVACMode.COOL,
        HVACMode.OFF,
    ]
    _attr_preset_modes: ClassVar[list[str]] = [
        mode.value for mode in AVAILABLE_HEAT_MODES
    ]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    )
    _attr_temperature_unit = UnitOfTemperature.FAHRENHEIT

    def __init__(
        self,
        coordinator: WattsVisionDataUpdateCoordinator,
        context: WattsVisionEntityContext,
        api_device_id: str,
    ) -> None:
        """Initialize a thermostat entity."""
        super().__init__(coordinator, context)
        self._api_device_id = api_device_id
        self._attr_unique_id = f"watts_thermostat_{context.device_id}"
        self._attr_name = None
        self._attr_extra_state_attributes = {"previous_gv_mode": "0"}
        self._update_from_coordinator()

    def _update_from_coordinator(self) -> None:
        """Update thermostat attributes from coordinator data."""
        device = self._device()
        if device is None:
            return

        device_mode = device.mode
        self._attr_current_temperature = device.air_temperature
        if device_mode is WattsVisionDeviceMode.FROST:
            self._attr_min_temp = 44.6
            self._attr_max_temp = 44.6
        else:
            self._attr_min_temp = device.min_temperature
            self._attr_max_temp = device.max_temperature

        if not device.is_heating:
            self._attr_hvac_action = (
                HVACAction.OFF
                if device_mode
                in {
                    WattsVisionDeviceMode.OFF,
                    WattsVisionDeviceMode.FAN_DISABLED,
                }
                else HVACAction.IDLE
            )
        elif device.is_cooling:
            self._attr_hvac_action = HVACAction.COOLING
        else:
            self._attr_hvac_action = HVACAction.HEATING

        mode_info = DEVICE_TO_MODE_TYPE[device_mode]
        self._attr_preset_mode = mode_info.heat_mode.value
        if device_mode in {
            WattsVisionDeviceMode.OFF,
            WattsVisionDeviceMode.FAN_DISABLED,
        }:
            self._attr_hvac_mode = HVACMode.OFF
            self._attr_target_temperature = None
        else:
            self._attr_hvac_mode = HVACMode.COOL if device.is_cooling else HVACMode.HEAT
            self._attr_target_temperature = device.target_temperature

        for temperature_type in AVAILABLE_TEMP_TYPES:
            state_attribute = TEMP_TYPE_TO_STATE_ATTRIBUTE[temperature_type]
            self._attr_extra_state_attributes[state_attribute] = temperature_for_type(
                device,
                temperature_type,
            )
        self._attr_extra_state_attributes["gv_mode"] = device.wire_mode
        _LOGGER.debug(
            "Updated %s: mode=%s target=%s current=%s",
            self._device_id,
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
        """Set the HVAC mode."""
        device = self._require_device()
        current_mode = device.mode
        if hvac_mode == HVACMode.OFF:
            self._attr_extra_state_attributes["previous_gv_mode"] = device.wire_mode
            device_mode = HEAT_MODE_TO_DEVICE[HeatMode.OFF]
            value = 0.0
        else:
            try:
                device_mode = WattsVisionDeviceMode(
                    str(
                        self._attr_extra_state_attributes.get(
                            "previous_gv_mode",
                            current_mode.value,
                        )
                    )
                )
            except ValueError:
                device_mode = HEAT_MODE_TO_DEVICE[HeatMode.COMFORT]
            if device_mode in {
                WattsVisionDeviceMode.OFF,
                WattsVisionDeviceMode.UNKNOWN,
            }:
                device_mode = HEAT_MODE_TO_DEVICE[HeatMode.COMFORT]
            value = self._temperature_for_mode(device, device_mode)

        value = self._clamp_temperature(value)
        await self._async_push_temperature(
            value,
            device_mode,
            device.with_mode(device_mode, value),
        )

    @override
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the thermostat preset mode."""
        device = self._require_device()
        heat_mode = HeatMode(preset_mode)
        device_mode = HEAT_MODE_TO_DEVICE[heat_mode]
        if heat_mode in {
            HeatMode.OFF,
            HeatMode.PROGRAM,
            HeatMode.FAN,
            HeatMode.FAN_DISABLED,
        }:
            value = 0.0
            self._attr_extra_state_attributes["previous_gv_mode"] = device.wire_mode
        else:
            value = self._clamp_temperature(
                self._temperature_for_mode(device, device_mode)
            )
        await self._async_push_temperature(
            value,
            device_mode,
            device.with_mode(device_mode, value),
        )

    @override
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a new target temperature."""
        device = self._require_device()
        device_mode = device.mode
        mode_info = DEVICE_TO_MODE_TYPE[device_mode]
        if (
            mode_info.heat_mode is HeatMode.PROGRAM
            or mode_info.temp_type is TempType.NONE
        ):
            # Watts rejects direct target-temperature writes in program mode.
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="temperature_mode_unsupported",
                translation_placeholders={"mode": mode_info.heat_mode.value},
            )

        value = self._clamp_temperature(float(int(kwargs[ATTR_TEMPERATURE])))
        await self._async_push_temperature(
            value,
            device_mode,
            device.with_target_temperature(value),
        )

    def _require_device(self) -> WattsVisionDevice:
        """Return the cached device or raise when unavailable."""
        device = self._device()
        if device is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_unavailable",
                translation_placeholders={"device_id": self._device_id},
            )
        return device

    def _clamp_temperature(self, value: float) -> float:
        """Clamp a temperature to the thermostat limits."""
        minimum = self._attr_min_temp
        maximum = self._attr_max_temp
        if minimum is None or maximum is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="temperature_limits_unavailable",
            )
        return min(max(value, minimum), maximum)

    @staticmethod
    def _temperature_for_mode(
        device: WattsVisionDevice,
        mode: WattsVisionDeviceMode,
    ) -> float:
        """Return a command value, including for modes without a target."""
        temperature_type = DEVICE_TO_MODE_TYPE[mode].temp_type
        if temperature_type is TempType.NONE:
            return device.manual_temperature
        return temperature_for_type(device, temperature_type)

    async def _async_push_temperature(
        self,
        value: float,
        device_mode: WattsVisionDeviceMode,
        updated_device: WattsVisionDevice,
    ) -> None:
        """Push a temperature update and publish its optimistic state."""
        try:
            await self.coordinator.async_set_device_temperature(
                self._smart_home_id,
                self._api_device_id,
                value,
                device_mode,
                updated_device,
            )
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
