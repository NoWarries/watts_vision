"""Watts Vision sensor platform."""

import logging
from collections.abc import Callable
from datetime import timedelta

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant

from .central_unit import WattsVisionLastCommunicationSensor
from .const import (
    API_CLIENT,
    DOMAIN,
    _AVAILABLE_HEAT_MODES,
    _AVAILABLE_TEMP_TYPES,
    _DEVICE_TO_MODE_TYPE,
    _TEMP_TYPE_TO_DEVICE,
)
from .watts_api import WattsApi

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=120)


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: Callable
):
    """Set up the sensor platform."""
    wattsClient: WattsApi = hass.data[DOMAIN][API_CLIENT]

    smartHomes = wattsClient.getSmartHomes()

    sensors = []

    if smartHomes is not None:
        for y in range(len(smartHomes)):
            if smartHomes[y]["zones"] is not None:
                for z in range(len(smartHomes[y]["zones"])):
                    if smartHomes[y]["zones"][z]["devices"] is not None:
                        for x in range(len(smartHomes[y]["zones"][z]["devices"])):
                            sensors.append(
                                WattsVisionPresetModeSensor(
                                    wattsClient,
                                    smartHomes[y]["smarthome_id"],
                                    smartHomes[y]["zones"][z]["devices"][x]["id"],
                                    smartHomes[y]["zones"][z]["zone_label"],
                                )
                            )
                            sensors.append(
                                WattsVisionTemperatureModeSensor(
                                    wattsClient,
                                    smartHomes[y]["smarthome_id"],
                                    smartHomes[y]["zones"][z]["devices"][x]["id"],
                                    smartHomes[y]["zones"][z]["zone_label"],
                                )
                            )
                            sensors.append(
                                WattsVisionTemperatureSensor(
                                    wattsClient,
                                    smartHomes[y]["smarthome_id"],
                                    smartHomes[y]["zones"][z]["devices"][x]["id"],
                                    smartHomes[y]["zones"][z]["zone_label"],
                                )
                            )
                            sensors.append(
                                WattsVisionSetTemperatureSensor(
                                    wattsClient,
                                    smartHomes[y]["smarthome_id"],
                                    smartHomes[y]["zones"][z]["devices"][x]["id"],
                                    smartHomes[y]["zones"][z]["zone_label"],
                                )
                            )
                            sensors.append(
                                WattsVisionBatterySensor(
                                    wattsClient,
                                    smartHomes[y]["smarthome_id"],
                                    smartHomes[y]["zones"][z]["devices"][x]["id"],
                                    smartHomes[y]["zones"][z]["zone_label"],
                                )
                            )
            sensors.append(
                WattsVisionLastCommunicationSensor(
                    wattsClient,
                    smartHomes[y]["smarthome_id"],
                    smartHomes[y]["label"],
                    smartHomes[y]["mac_address"],
                )
            )

    async_add_entities(sensors, update_before_add=True)


class WattsVisionPresetModeSensor(SensorEntity):
    """Representation of a Watts Vision thermostat."""

    def __init__(self, wattsClient: WattsApi, smartHome: str, id: str, zone: str):
        super().__init__()
        self.client = wattsClient
        self.smartHome = smartHome
        self.id = id
        self.zone = zone
        self._name = zone + " Preset mode"
        self._state = None
        self._available = True

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return "thermostat_mode_" + self.id

    @property
    def name(self) -> str:
        """Return the name of the entity."""
        return self._name

    @property
    def state(self) -> str | None:
        return self._state

    @property
    def device_class(self):
        return SensorDeviceClass.ENUM

    @property
    def options(self):
        return [mode.value.capitalize() for mode in _AVAILABLE_HEAT_MODES]

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
            "suggested_area": self.zone,
        }

    async def async_update(self):
        # try:
        smartHomeDevice = self.client.getDevice(self.smartHome, self.id)

        self._state = _DEVICE_TO_MODE_TYPE[smartHomeDevice["gv_mode"]].heat_mode.value.capitalize()

        # except:
        #     self._available = False
        #     _LOGGER.exception("Error retrieving data.")

class WattsVisionTemperatureModeSensor(SensorEntity):
    """Representation of a Watts Vision thermostat."""

    def __init__(self, wattsClient: WattsApi, smartHome: str, id: str, zone: str):
        super().__init__()
        self.client = wattsClient
        self.smartHome = smartHome
        self.id = id
        self.zone = zone
        self._name = zone + " Temperature mode"
        self._state = None
        self._available = True

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return "temperature_mode_" + self.id

    @property
    def name(self) -> str:
        """Return the name of the entity."""
        return self._name

    @property
    def state(self) -> str | None:
        return self._state

    @property
    def device_class(self):
        return SensorDeviceClass.ENUM

    @property
    def options(self):
        return [mode.value.capitalize() for mode in _AVAILABLE_TEMP_TYPES]

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
            "suggested_area": self.zone,
        }

    async def async_update(self):
        # try:
        smartHomeDevice = self.client.getDevice(self.smartHome, self.id)

        self._state = _DEVICE_TO_MODE_TYPE[smartHomeDevice["gv_mode"]].temp_type.value.capitalize()

        # except:
        #     self._available = False
        #     _LOGGER.exception("Error retrieving data.")

class WattsVisionBatterySensor(SensorEntity):
    """Representation of the state of a Watts Vision device."""

    def __init__(self, wattsClient: WattsApi, smartHome: str, id: str, zone: str):
        super().__init__()
        self.client = wattsClient
        self.smartHome = smartHome
        self.id = id
        self.zone = zone
        self._name = zone + " Battery"
        self._state = None
        self._available = None

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return "battery_" + self.id

    @property
    def name(self) -> str:
        """Return the name of the entity."""
        return self._name

    @property
    def device_class(self):
        return SensorDeviceClass.BATTERY

    @property
    def native_unit_of_measurement(self):
        return PERCENTAGE

    @property
    def state(self) -> int:
        if self.client.getDevice(self.smartHome, self.id)["error_code"] == 1:
            _LOGGER.warning(
                "Battery is malfunctioning or (almost) empty for device %s ", self.id
            )
            return 0
        return 100

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


class WattsVisionTemperatureSensor(SensorEntity):
    """Representation of a Watts Vision temperature sensor."""

    def __init__(self, wattsClient: WattsApi, smartHome: str, id: str, zone: str):
        super().__init__()
        self.client = wattsClient
        self.smartHome = smartHome
        self.id = id
        self.zone = zone
        self._name = zone + " Air temperature"
        self._state = None
        self._available = True

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return "temperature_air_" + self.id

    @property
    def name(self) -> str:
        """Return the name of the entity."""
        return self._name

    @property
    def state(self) -> str | None:
        return self._state

    @property
    def device_class(self):
        return SensorDeviceClass.TEMPERATURE

    @property
    def native_unit_of_measurement(self):
        return UnitOfTemperature.FAHRENHEIT

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
        value = int(smartHomeDevice["temperature_air"])
        if self.hass.config.units.temperature_unit == UnitOfTemperature.CELSIUS:
            self._state = round((value - 320) * 5 / 9 / 10, 1)
        else:
            self._state = value / 10
        # except:
        #     self._available = False
        #     _LOGGER.exception("Error retrieving data.")


class WattsVisionSetTemperatureSensor(SensorEntity):
    """Representation of a Watts Vision temperature sensor."""

    def __init__(self, wattsClient: WattsApi, smartHome: str, id: str, zone: str):
        super().__init__()
        self.client = wattsClient
        self.smartHome = smartHome
        self.id = id
        self.zone = zone
        self._name = zone + " Target temperature"
        self._state = None
        self._available = True

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the sensor."""
        return "target_temperature_" + self.id

    @property
    def name(self) -> str:
        """Return the name of the entity."""
        return self._name

    @property
    def state(self) -> str | None:
        return self._state

    @property
    def device_class(self):
        return SensorDeviceClass.TEMPERATURE

    @property
    def native_unit_of_measurement(self):
        return UnitOfTemperature.FAHRENHEIT

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

        if smartHomeDevice["gv_mode"] == "1":
            self._state = NaN
        else:
            value = int(smartHomeDevice[_TEMP_TYPE_TO_DEVICE[_DEVICE_TO_MODE_TYPE[smartHomeDevice["gv_mode"]].temp_type]])
            if self.hass.config.units.temperature_unit == UnitOfTemperature.CELSIUS:
                self._state = round((value - 320) * 5 / 9 / 10, 1)
            else:
                self._state = value / 10

        # except:
        #     self._available = False
        #     _LOGGER.exception("Error retrieving data.")
