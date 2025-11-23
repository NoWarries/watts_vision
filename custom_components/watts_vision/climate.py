import functools
import logging
from collections.abc import Callable

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
    UnitOfTemperature,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    API_CLIENT,
    DOMAIN,
    _AVAILABLE_HEAT_MODES,
    _AVAILABLE_TEMP_TYPES,
    _DEVICE_TO_MODE_TYPE,
    _TEMP_TYPE_TO_DEVICE,
    _HEAT_MODE_TO_DEVICE,
    HeatMode,
)
from .watts_api import WattsApi

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: Callable
):
    """Set up the climate platform."""
    wattsClient: WattsApi = hass.data[DOMAIN][API_CLIENT]

    smartHomes = wattsClient.getSmartHomes()

    devices = []

    if smartHomes is not None:
        for y in range(len(smartHomes)):
            if smartHomes[y]["zones"] is not None:
                for z in range(len(smartHomes[y]["zones"])):
                    if smartHomes[y]["zones"][z]["devices"] is not None:
                        for x in range(len(smartHomes[y]["zones"][z]["devices"])):
                            devices.append(
                                WattsThermostat(
                                    wattsClient,
                                    smartHomes[y]["smarthome_id"],
                                    smartHomes[y]["zones"][z]["devices"][x]["id"],
                                    smartHomes[y]["zones"][z]["devices"][x][
                                        "id_device"
                                    ],
                                    smartHomes[y]["zones"][z]["zone_label"],
                                )
                            )

    async_add_entities(devices, update_before_add=True)


class WattsThermostat(ClimateEntity):
    """"""

    def __init__(
        self, wattsClient: WattsApi, smartHome: str, id: str, deviceID: str, zone: str
    ):
        super().__init__()
        self.client = wattsClient
        self.smartHome = smartHome
        self.id = id
        self.zone = zone
        self.deviceID = deviceID
        self._name = zone + " Thermostat"
        self._available = True
        self._attr_extra_state_attributes = {"previous_gv_mode": "0"}

    @property
    def unique_id(self):
        """Return the unique ID for this device."""
        return "watts_thermostat_" + self.id

    @property
    def name(self) -> str:
        """Return the name of the entity."""
        return self._name

    @property
    def supported_features(self):
        return (
            ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
        )

    @property
    def temperature_unit(self) -> str:
        return UnitOfTemperature.FAHRENHEIT

    @property
    def hvac_modes(self) -> list[str]:
        return [HVACMode.HEAT] + [HVACMode.COOL] + [HVACMode.OFF]

    @property
    def hvac_mode(self) -> str:
        return self._attr_hvac_mode

    @property
    def hvac_action(self) -> str:
        return self._attr_hvac_action

    @property
    def preset_modes(self) -> list[str]:
        """Return the available presets."""
        return [mode.value for mode in _AVAILABLE_HEAT_MODES]

    @property
    def preset_mode(self) -> str:
        return self._attr_preset_mode

    @property
    def device_info(self):
        return {
            "identifiers": {
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self.id)
            },
            "manufacturer": "Watts",
            "name": "Thermostat " + self.zone,
            "model": "BT-D03-RF",
            "via_device": (DOMAIN, self.smartHome),
        }

    async def async_update(self):
        # try:
        smartHomeDevice = self.client.getDevice(self.smartHome, self.id)

        self._attr_current_temperature = float(smartHomeDevice["temperature_air"]) / 10
        if smartHomeDevice["gv_mode"] != "2":
            self._attr_min_temp = float(smartHomeDevice["min_set_point"]) / 10
            self._attr_max_temp = float(smartHomeDevice["max_set_point"]) / 10
        else:
            self._attr_min_temp = float(446 / 10)
            self._attr_max_temp = float(446 / 10)

        if smartHomeDevice["heating_up"] == "0":
            if smartHomeDevice["gv_mode"] == "1":
                self._attr_hvac_action = HVACAction.OFF
            else:
                self._attr_hvac_action = HVACAction.IDLE
        elif smartHomeDevice["heat_cool"] == "1":
            self._attr_hvac_action = HVACAction.COOLING
        else:
            self._attr_hvac_action = HVACAction.HEATING

        self._attr_preset_mode = _DEVICE_TO_MODE_TYPE[smartHomeDevice["gv_mode"]].heat_mode.value

        if smartHomeDevice["gv_mode"] == "1":
            self._attr_hvac_mode = HVACMode.OFF
            self._attr_target_temperature = None
            targettemp = 0
        else:
            if smartHomeDevice["heat_cool"] == "1":
                self._attr_hvac_mode = HVACMode.COOL
            else:
                self._attr_hvac_mode = HVACMode.HEAT
            consigne = _TEMP_TYPE_TO_DEVICE[_DEVICE_TO_MODE_TYPE[smartHomeDevice["gv_mode"]].temp_type]
            self._attr_target_temperature = float(smartHomeDevice[consigne]) / 10
            targettemp = self._attr_target_temperature

        logstring = f"Update: {self._name} targettemp={targettemp}"
        for consigne in [_TEMP_TYPE_TO_DEVICE[mode] for mode in _AVAILABLE_TEMP_TYPES]:
            self._attr_extra_state_attributes[consigne] = (
                float(smartHomeDevice[consigne]) / 10
            )
            logstring += (
                f" {consigne[9:]}={self._attr_extra_state_attributes[consigne]}"
            )
        _LOGGER.debug(logstring)

        self._attr_extra_state_attributes["gv_mode"] = smartHomeDevice["gv_mode"]
        _LOGGER.debug(
            "Update: {} air={} heat_mode {} temp_type {} min {} max {}".format(
                self._name,
                self._attr_current_temperature,
                _DEVICE_TO_MODE_TYPE[smartHomeDevice["gv_mode"]].heat_mode,
                _DEVICE_TO_MODE_TYPE[smartHomeDevice["gv_mode"]].temp_type,
                self._attr_min_temp,
                self._attr_max_temp,
            )
        )

        # except:
        #     self._available = False
        #     _LOGGER.exception("Error retrieving data.")

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        mode = self._attr_extra_state_attributes["previous_gv_mode"]
        if hvac_mode == HVACMode.HEAT or hvac_mode == HVACMode.COOL:
            if mode == "1":
                consigne = "Off"
                value = 0
            else:
                consigne = _TEMP_TYPE_TO_DEVICE[_DEVICE_TO_MODE_TYPE[mode].temp_type]
                value = int(self._attr_extra_state_attributes[consigne])

        if hvac_mode == HVACMode.OFF:
            self._attr_extra_state_attributes["previous_gv_mode"] = (
                self._attr_extra_state_attributes["gv_mode"]
            )
            mode = _HEAT_MODE_TO_DEVICE[HeatMode.OFF]
            consigne = "Off"
            value = 0

        _LOGGER.debug(
            f"Set hvac mode to {hvac_mode} for device {self._name} with temperature {value} {consigne}"
        )

        value = min(value, self._attr_max_temp)
        value = max(value, self._attr_min_temp)
        value = str(value * 10)

        # reloading the devices may take some time, meanwhile set the new values manually
        smartHomeDevice = self.client.getDevice(self.smartHome, self.id)
        smartHomeDevice["consigne_manuel"] = value
        smartHomeDevice["gv_mode"] = mode

        func = functools.partial(
            self.client.pushTemperature, self.smartHome, self.deviceID, value, mode
        )
        await self.hass.async_add_executor_job(func)

    async def async_set_preset_mode(self, preset_mode):
        """Set new target preset mode."""
        heat_mode = HeatMode(preset_mode)
        gv_mode = _HEAT_MODE_TO_DEVICE[heat_mode]

        if heat_mode not in [HeatMode.OFF, HeatMode.PROGRAM]:
            temp_type = _DEVICE_TO_MODE_TYPE[gv_mode].temp_type
            consigne = _TEMP_TYPE_TO_DEVICE[temp_type]

            value = float(self._attr_extra_state_attributes[consigne])
            value = min(value, self._attr_max_temp)
            value = max(value, self._attr_min_temp)
            value = str(round(value * 10, 0))

            _LOGGER.debug(
                f"Set preset mode to {preset_mode} for device {self._name} with temperature {value} ({consigne} was {self._attr_extra_state_attributes[consigne]}) "
            )
        else:
            value = "0"
            self._attr_extra_state_attributes["previous_gv_mode"] = (
                self._attr_extra_state_attributes["gv_mode"]
            )
            _LOGGER.debug(
                f"Set preset mode to {preset_mode} for device {self._name} "
            )

        # reloading the devices may take some time, meanwhile set the new values manually
        smartHomeDevice = self.client.getDevice(self.smartHome, self.id)
        smartHomeDevice["consigne_manuel"] = value
        smartHomeDevice["gv_mode"] = gv_mode

        func = functools.partial(
            self.client.pushTemperature,
            self.smartHome,
            self.deviceID,
            value,
            gv_mode,
        )
        await self.hass.async_add_executor_job(func)

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        value = int(kwargs["temperature"])

        # Get the smartHomeDevice
        smartHomeDevice = self.client.getDevice(self.smartHome, self.id)

        gvMode = smartHomeDevice["gv_mode"]
        if _DEVICE_TO_MODE_TYPE[gvMode].heat_mode == HeatMode.PROGRAM:
            # This is not accepted by Watts!
            raise HomeAssistantError(
                f"Setting temperature is not supported in {_DEVICE_TO_MODE_TYPE[gvMode].heat_mode.value} mode."
            )

        temp_type = _DEVICE_TO_MODE_TYPE[gvMode].temp_type

        _LOGGER.debug(
            f"Set a-temperature to {value} for device {self._name} in temp_type {temp_type} - min {self._attr_min_temp} max {self._attr_max_temp}"
        )
        value = min(value, self._attr_max_temp)
        value = max(value, self._attr_min_temp)
        value = str(value * 10)
        _LOGGER.debug(
            f"Set b-temperature to {value} for device {self._name} in mode {temp_type}"
        )

        # update its temp settings
        smartHomeDevice["consigne_manuel"] = value
        smartHomeDevice[_TEMP_TYPE_TO_DEVICE[_DEVICE_TO_MODE_TYPE[gvMode].temp_type]] = value

        # Set the smartHomeDevice using the just altered SmartHomeDevice
        # self.client.setDevice(self.smartHome, self.id, smartHomeDevice)

        func = functools.partial(
            self.client.pushTemperature, self.smartHome, self.deviceID, value, str(gvMode)
        )

        await self.hass.async_add_executor_job(func)
