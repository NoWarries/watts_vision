"""Climate platform for Watts Vision."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar

from homeassistant.components.climate import (
    ATTR_TEMPERATURE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import UnitOfTemperature
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

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
    HEAT_MODE_TO_DEVICE,
    TEMP_TYPE_TO_STATE_ATTRIBUTE,
    HeatMode,
    temperature_for_type,
)
from .entity import WattsVisionEntity

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from . import WattsVisionConfigEntry
    from .coordinator import WattsVisionDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 1


async def async_setup_entry(
    _hass: HomeAssistant,
    config_entry: WattsVisionConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Watts Vision climate entities."""
    coordinator = config_entry.runtime_data
    entities: list[ClimateEntity] = []
    for smart_home in coordinator.data.smart_homes:
        smart_home_id = smart_home.smart_home_id
        for zone in smart_home.zones:
            entities.extend(
                WattsThermostat(
                    coordinator,
                    smart_home_id,
                    device.device_id,
                    device.api_device_id,
                    zone.label,
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
        smart_home_id: str,
        device_id: str,
        api_device_id: str,
        zone: str,
    ) -> None:
        """Initialize a thermostat entity."""
        super().__init__(coordinator, smart_home_id, device_id, zone)
        self._api_device_id = api_device_id
        self._attr_unique_id = f"watts_thermostat_{device_id}"
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
                if device_mode is WattsVisionDeviceMode.OFF
                else HVACAction.IDLE
            )
        elif device.is_cooling:
            self._attr_hvac_action = HVACAction.COOLING
        else:
            self._attr_hvac_action = HVACAction.HEATING

        mode_info = DEVICE_TO_MODE_TYPE[device_mode]
        self._attr_preset_mode = mode_info.heat_mode.value
        if device_mode is WattsVisionDeviceMode.OFF:
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
        self._attr_extra_state_attributes["gv_mode"] = device_mode.value
        _LOGGER.debug(
            "Updated %s: mode=%s target=%s current=%s",
            self._device_id,
            device_mode,
            self._attr_target_temperature,
            self._attr_current_temperature,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._update_from_coordinator()
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode."""
        device = self._require_device()
        current_mode = device.mode
        if hvac_mode == HVACMode.OFF:
            self._attr_extra_state_attributes["previous_gv_mode"] = current_mode.value
            device_mode = HEAT_MODE_TO_DEVICE[HeatMode.OFF]
            value = 0.0
        else:
            device_mode = WattsVisionDeviceMode(
                str(
                    self._attr_extra_state_attributes.get(
                        "previous_gv_mode",
                        current_mode.value,
                    )
                )
            )
            if device_mode is WattsVisionDeviceMode.OFF:
                device_mode = HEAT_MODE_TO_DEVICE[HeatMode.COMFORT]
            value = temperature_for_type(
                device,
                DEVICE_TO_MODE_TYPE[device_mode].temp_type,
            )

        value = self._clamp_temperature(value)
        await self._async_push_temperature(
            value,
            device_mode,
            device.with_mode(device_mode, value),
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the thermostat preset mode."""
        device = self._require_device()
        heat_mode = HeatMode(preset_mode)
        device_mode = HEAT_MODE_TO_DEVICE[heat_mode]
        if heat_mode in {HeatMode.OFF, HeatMode.PROGRAM}:
            value = 0.0
            self._attr_extra_state_attributes["previous_gv_mode"] = device.mode.value
        else:
            value = self._clamp_temperature(
                temperature_for_type(
                    device,
                    DEVICE_TO_MODE_TYPE[device_mode].temp_type,
                )
            )
        await self._async_push_temperature(
            value,
            device_mode,
            device.with_mode(device_mode, value),
        )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a new target temperature."""
        device = self._require_device()
        device_mode = device.mode
        mode_info = DEVICE_TO_MODE_TYPE[device_mode]
        if mode_info.heat_mode == HeatMode.PROGRAM:
            # Watts rejects direct target-temperature writes in program mode.
            msg = (
                "Setting temperature is not supported in "
                f"{mode_info.heat_mode.value} mode"
            )
            raise HomeAssistantError(msg)

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
            msg = f"Watts Vision device {self._device_id} is unavailable"
            raise HomeAssistantError(msg)
        return device

    def _clamp_temperature(self, value: float) -> float:
        """Clamp a temperature to the thermostat limits."""
        minimum = self._attr_min_temp
        maximum = self._attr_max_temp
        if minimum is None or maximum is None:
            msg = "Thermostat temperature limits are unavailable"
            raise HomeAssistantError(msg)
        return min(max(value, minimum), maximum)

    async def _async_push_temperature(
        self,
        value: float,
        device_mode: WattsVisionDeviceMode,
        updated_device: WattsVisionDevice,
    ) -> None:
        """Push a temperature update and publish its optimistic state."""
        try:
            await self.coordinator.client.async_set_temperature(
                self._smart_home_id,
                self._api_device_id,
                value,
                device_mode,
            )
        except WattsVisionResponseError as err:
            msg = "Watts Vision rejected the thermostat update"
            raise HomeAssistantError(msg) from err
        except WattsVisionError as err:
            msg = "Unable to update the Watts Vision thermostat"
            raise HomeAssistantError(msg) from err
        self.coordinator.async_set_updated_device(
            self._smart_home_id,
            updated_device,
        )
