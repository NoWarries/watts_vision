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
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    AVAILABLE_HEAT_MODES,
    AVAILABLE_TEMP_TYPES,
    DEVICE_TO_MODE_TYPE,
    DOMAIN,
    HEAT_MODE_TO_DEVICE,
    TEMP_TYPE_TO_DEVICE,
    HeatMode,
)
from .watts_api import WattsApiError

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from . import WattsVisionConfigEntry
    from .watts_api import JsonObject, WattsApi

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    _hass: HomeAssistant,
    config_entry: WattsVisionConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Watts Vision climate entities."""
    client = config_entry.runtime_data
    entities: list[ClimateEntity] = []
    for smart_home in client.get_smart_homes():
        smart_home_id = str(smart_home["smarthome_id"])
        for zone in smart_home.get("zones") or []:
            zone_label = str(zone["zone_label"])
            entities.extend(
                WattsThermostat(
                    client,
                    smart_home_id,
                    str(device["id"]),
                    str(device["id_device"]),
                    zone_label,
                )
                for device in zone.get("devices") or []
            )

    async_add_entities(entities, update_before_add=True)


class WattsThermostat(ClimateEntity):
    """Represent a Watts Vision thermostat."""

    _attr_has_entity_name = True
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
        client: WattsApi,
        smart_home_id: str,
        device_id: str,
        api_device_id: str,
        zone: str,
    ) -> None:
        """Initialize a thermostat entity."""
        self._client = client
        self._smart_home_id = smart_home_id
        self._device_id = device_id
        self._api_device_id = api_device_id
        self._attr_unique_id = f"watts_thermostat_{device_id}"
        self._attr_name = None
        self._attr_extra_state_attributes = {"previous_gv_mode": "0"}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            manufacturer="Watts",
            name=f"Thermostat {zone}",
            model="BT-D03-RF",
            via_device=(DOMAIN, smart_home_id),
            suggested_area=zone,
        )

    async def async_update(self) -> None:
        """Update thermostat attributes from cached data."""
        device = self._client.get_device(self._smart_home_id, self._device_id)
        self._attr_available = device is not None
        if device is None:
            return

        device_mode = str(device["gv_mode"])
        self._attr_current_temperature = float(device["temperature_air"]) / 10
        if device_mode == "2":
            self._attr_min_temp = 44.6
            self._attr_max_temp = 44.6
        else:
            self._attr_min_temp = float(device["min_set_point"]) / 10
            self._attr_max_temp = float(device["max_set_point"]) / 10

        if str(device["heating_up"]) == "0":
            self._attr_hvac_action = (
                HVACAction.OFF if device_mode == "1" else HVACAction.IDLE
            )
        elif str(device["heat_cool"]) == "1":
            self._attr_hvac_action = HVACAction.COOLING
        else:
            self._attr_hvac_action = HVACAction.HEATING

        mode_info = DEVICE_TO_MODE_TYPE[device_mode]
        self._attr_preset_mode = mode_info.heat_mode.value
        if device_mode == "1":
            self._attr_hvac_mode = HVACMode.OFF
            self._attr_target_temperature = None
        else:
            self._attr_hvac_mode = (
                HVACMode.COOL if str(device["heat_cool"]) == "1" else HVACMode.HEAT
            )
            temperature_key = TEMP_TYPE_TO_DEVICE[mode_info.temp_type]
            self._attr_target_temperature = float(device[temperature_key]) / 10

        for temperature_type in AVAILABLE_TEMP_TYPES:
            temperature_key = TEMP_TYPE_TO_DEVICE[temperature_type]
            self._attr_extra_state_attributes[temperature_key] = (
                float(device[temperature_key]) / 10
            )
        self._attr_extra_state_attributes["gv_mode"] = device_mode
        _LOGGER.debug(
            "Updated %s: mode=%s target=%s current=%s",
            self._device_id,
            device_mode,
            self._attr_target_temperature,
            self._attr_current_temperature,
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode."""
        device = self._require_device()
        current_mode = str(device["gv_mode"])
        if hvac_mode == HVACMode.OFF:
            self._attr_extra_state_attributes["previous_gv_mode"] = current_mode
            device_mode = HEAT_MODE_TO_DEVICE[HeatMode.OFF]
            value = 0.0
        else:
            device_mode = str(
                self._attr_extra_state_attributes.get("previous_gv_mode", current_mode)
            )
            if device_mode == "1":
                device_mode = HEAT_MODE_TO_DEVICE[HeatMode.COMFORT]
            temperature_key = TEMP_TYPE_TO_DEVICE[
                DEVICE_TO_MODE_TYPE[device_mode].temp_type
            ]
            value = float(self._attr_extra_state_attributes[temperature_key])

        value = self._clamp_temperature(value)
        api_value = str(round(value * 10))

        # Device reloads can take a while, so update the shared cache
        # optimistically to keep every entity consistent until the next poll.
        device["consigne_manuel"] = api_value
        device["gv_mode"] = device_mode
        await self._async_push_temperature(api_value, device_mode)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the thermostat preset mode."""
        device = self._require_device()
        heat_mode = HeatMode(preset_mode)
        device_mode = HEAT_MODE_TO_DEVICE[heat_mode]
        if heat_mode in {HeatMode.OFF, HeatMode.PROGRAM}:
            api_value = "0"
            self._attr_extra_state_attributes["previous_gv_mode"] = str(
                device["gv_mode"]
            )
        else:
            temperature_key = TEMP_TYPE_TO_DEVICE[
                DEVICE_TO_MODE_TYPE[device_mode].temp_type
            ]
            value = float(self._attr_extra_state_attributes[temperature_key])
            value = self._clamp_temperature(value)
            api_value = str(round(value * 10))
        device["consigne_manuel"] = api_value
        device["gv_mode"] = device_mode
        await self._async_push_temperature(api_value, device_mode)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a new target temperature."""
        device = self._require_device()
        device_mode = str(device["gv_mode"])
        mode_info = DEVICE_TO_MODE_TYPE[device_mode]
        if mode_info.heat_mode == HeatMode.PROGRAM:
            # Watts rejects direct target-temperature writes in program mode.
            msg = (
                "Setting temperature is not supported in "
                f"{mode_info.heat_mode.value} mode"
            )
            raise HomeAssistantError(msg)

        value = self._clamp_temperature(float(int(kwargs[ATTR_TEMPERATURE])))
        api_value = str(round(value * 10))
        temperature_key = TEMP_TYPE_TO_DEVICE[mode_info.temp_type]
        device["consigne_manuel"] = api_value
        device[temperature_key] = api_value
        await self._async_push_temperature(api_value, device_mode)

    def _require_device(self) -> JsonObject:
        """Return the cached device or raise when unavailable."""
        device = self._client.get_device(self._smart_home_id, self._device_id)
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

    async def _async_push_temperature(self, value: str, device_mode: str) -> None:
        """Push a temperature update through the executor."""
        try:
            success = await self.hass.async_add_executor_job(
                self._client.push_temperature,
                self._smart_home_id,
                self._api_device_id,
                value,
                device_mode,
            )
        except WattsApiError as err:
            msg = "Unable to update the Watts Vision thermostat"
            raise HomeAssistantError(msg) from err
        if not success:
            msg = "Watts Vision rejected the thermostat update"
            raise HomeAssistantError(msg)
