"""Constants for the Watts Vision integration."""

from __future__ import annotations

import logging
from enum import Enum
from typing import NamedTuple

from homeassistant.components.climate.const import (
    PRESET_BOOST,
    PRESET_COMFORT,
    PRESET_ECO,
    PRESET_NONE,
)

from .api import WattsVisionDevice, WattsVisionDeviceMode
from .api.const import (
    DEFAULT_BOOST_DURATION_SECONDS,
    MAX_BOOST_DURATION_SECONDS,
    MIN_BOOST_DURATION_SECONDS,
)

DOMAIN = "watts_vision"
INTEGRATION_VERSION = "1.0.0"

LOGGER = logging.getLogger(__package__)

DEFAULT_SCAN_INTERVAL = 300
MIN_SCAN_INTERVAL = 300
MAX_SCAN_INTERVAL = 86_400

SECONDS_PER_MINUTE = 60
DEFAULT_BOOST_DURATION_MINUTES = DEFAULT_BOOST_DURATION_SECONDS // SECONDS_PER_MINUTE
MIN_BOOST_DURATION_MINUTES = MIN_BOOST_DURATION_SECONDS // SECONDS_PER_MINUTE
MAX_BOOST_DURATION_MINUTES = MAX_BOOST_DURATION_SECONDS // SECONDS_PER_MINUTE

PRESET_DEFROST = "frost_protection"
PRESET_OFF = "Off"
PRESET_PROGRAM = "Program"


class HeatMode(Enum):
    """Available heating modes."""

    OFF = PRESET_OFF
    FROST = PRESET_DEFROST
    COMFORT = PRESET_COMFORT
    PROGRAM = PRESET_PROGRAM
    ECO = PRESET_ECO
    BOOST = PRESET_BOOST
    MANUAL = "Manual"
    UNKNOWN = "Unknown"


class TempType(Enum):
    """Available temperature modes."""

    NONE = PRESET_NONE
    FROST = PRESET_DEFROST
    ECO = PRESET_ECO
    COMFORT = PRESET_COMFORT
    BOOST = PRESET_BOOST
    CURRENT = "Current"
    TARGET = "Target"
    MANUAL = "Manual"


class ModeInfo(NamedTuple):
    """Heating and temperature mode pair."""

    heat_mode: HeatMode
    temp_type: TempType


DEVICE_TO_MODE_TYPE: dict[WattsVisionDeviceMode, ModeInfo] = {
    WattsVisionDeviceMode.COMFORT: ModeInfo(HeatMode.COMFORT, TempType.COMFORT),
    WattsVisionDeviceMode.OFF: ModeInfo(HeatMode.OFF, TempType.NONE),
    WattsVisionDeviceMode.FROST: ModeInfo(HeatMode.FROST, TempType.FROST),
    WattsVisionDeviceMode.ECO: ModeInfo(HeatMode.ECO, TempType.ECO),
    WattsVisionDeviceMode.BOOST: ModeInfo(HeatMode.BOOST, TempType.BOOST),
    WattsVisionDeviceMode.MODE_5: ModeInfo(HeatMode.UNKNOWN, TempType.NONE),
    WattsVisionDeviceMode.MODE_6: ModeInfo(HeatMode.UNKNOWN, TempType.NONE),
    WattsVisionDeviceMode.PROGRAM_COMFORT: ModeInfo(HeatMode.PROGRAM, TempType.COMFORT),
    WattsVisionDeviceMode.PROGRAM_ECO: ModeInfo(HeatMode.PROGRAM, TempType.ECO),
    WattsVisionDeviceMode.PROGRAM_UNSPECIFIED: ModeInfo(
        HeatMode.PROGRAM,
        TempType.NONE,
    ),
    WattsVisionDeviceMode.MANUAL: ModeInfo(HeatMode.MANUAL, TempType.MANUAL),
    WattsVisionDeviceMode.PROGRAM_BOOST: ModeInfo(
        HeatMode.PROGRAM,
        TempType.BOOST,
    ),
    WattsVisionDeviceMode.UNKNOWN: ModeInfo(HeatMode.UNKNOWN, TempType.NONE),
}


def temperature_for_type(
    device: WattsVisionDevice,
    temperature_type: TempType,
) -> float:
    """Return a thermostat temperature for an integration temperature type."""
    if temperature_type is TempType.ECO:
        return device.eco_temperature
    if temperature_type is TempType.FROST:
        return device.frost_temperature
    if temperature_type is TempType.COMFORT:
        return device.comfort_temperature
    if temperature_type is TempType.CURRENT:
        return device.air_temperature
    if temperature_type is TempType.MANUAL:
        return device.manual_temperature
    if temperature_type is TempType.BOOST:
        return device.boost_temperature
    msg = f"Temperature type {temperature_type.value} has no device value"
    raise ValueError(msg)


AVAILABLE_TEMP_TYPES: tuple[TempType, ...] = (
    TempType.ECO,
    TempType.FROST,
    TempType.COMFORT,
    TempType.CURRENT,
    TempType.BOOST,
)

AVAILABLE_HEAT_MODES: tuple[HeatMode, ...] = (
    HeatMode.COMFORT,
    HeatMode.ECO,
    HeatMode.FROST,
    HeatMode.BOOST,
)

REPORTED_HEAT_MODES: tuple[HeatMode, ...] = (
    *AVAILABLE_HEAT_MODES,
    HeatMode.PROGRAM,
    HeatMode.OFF,
    HeatMode.MANUAL,
    HeatMode.UNKNOWN,
)

REPORTED_TEMP_TYPES: tuple[TempType, ...] = (
    *AVAILABLE_TEMP_TYPES,
    TempType.NONE,
    TempType.MANUAL,
)
