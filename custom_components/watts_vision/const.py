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

DOMAIN = "watts_vision"

LOGGER = logging.getLogger(__package__)

DEFAULT_SCAN_INTERVAL = 300
MIN_SCAN_INTERVAL = 300
MAX_SCAN_INTERVAL = 86_400

PRESET_DEFROST = "Frost Protection"
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


DEVICE_TO_MODE_TYPE: dict[str, ModeInfo] = {
    "0": ModeInfo(HeatMode.COMFORT, TempType.COMFORT),
    "1": ModeInfo(HeatMode.OFF, TempType.NONE),
    "2": ModeInfo(HeatMode.FROST, TempType.FROST),
    "3": ModeInfo(HeatMode.ECO, TempType.ECO),
    "4": ModeInfo(HeatMode.BOOST, TempType.BOOST),
    "8": ModeInfo(HeatMode.PROGRAM, TempType.COMFORT),
    "11": ModeInfo(HeatMode.PROGRAM, TempType.ECO),
}

# - 5: fan
# - 6: fan disabled
# - 13: program with no known temperature type
# - 15: manual temperature
# - 16: program using the boost temperature

HEAT_MODE_TO_DEVICE: dict[HeatMode, str] = {
    HeatMode.ECO: "3",
    HeatMode.FROST: "2",
    HeatMode.COMFORT: "0",
    HeatMode.PROGRAM: "11",
    HeatMode.BOOST: "4",
    HeatMode.OFF: "1",
}

TEMP_TYPE_TO_DEVICE: dict[TempType, str] = {
    TempType.ECO: "consigne_eco",
    TempType.FROST: "consigne_hg",
    TempType.COMFORT: "consigne_confort",
    TempType.CURRENT: "temperature_air",
    TempType.MANUAL: "consigne_manuel",
    TempType.BOOST: "consigne_boost",
}

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
    HeatMode.PROGRAM,
    HeatMode.BOOST,
    HeatMode.OFF,
)
