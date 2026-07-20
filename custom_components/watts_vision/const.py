"""
This module contains the constants for the WattsVision integration.
Constants are immutable variables which reference static values.
This ensures consistency across the integration.
"""

import logging
from typing import NamedTuple
from enum import Enum

from homeassistant.components.climate.const import (
    PRESET_NONE,
    PRESET_BOOST,
    PRESET_COMFORT,
    PRESET_ECO,
)

API_CLIENT = "api"

DOMAIN = "watts_vision"

LOGGER = logging.getLogger(__package__)

PRESET_DEFROST = "Frost Protection"
PRESET_OFF = "Off"
PRESET_PROGRAM = "Program"

class HeatMode(Enum):
    """Enum of available heating modes."""

    OFF = PRESET_OFF
    FROST = PRESET_DEFROST
    COMFORT = PRESET_COMFORT
    PROGRAM = PRESET_PROGRAM
    ECO = PRESET_ECO
    BOOST = PRESET_BOOST

class TempType(Enum):
    """Enum of available temperatures modes."""

    NONE = PRESET_NONE
    FROST = PRESET_DEFROST
    ECO = PRESET_ECO
    COMFORT = PRESET_COMFORT
    BOOST = PRESET_BOOST
    CURRENT = "Current"
    TARGET = "Target"
    MANUAL = "Manual"

class _ModeInfo(NamedTuple):
    heat_mode: HeatMode
    temp_type: TempType

_DEVICE_TO_MODE_TYPE: dict[str, _ModeInfo] = {
    "0": _ModeInfo(HeatMode.COMFORT, TempType.COMFORT),
    "1": _ModeInfo(HeatMode.OFF, TempType.NONE),
    "2": _ModeInfo(HeatMode.FROST, TempType.FROST),
    "3": _ModeInfo(HeatMode.ECO, TempType.ECO),
    "4": _ModeInfo(HeatMode.BOOST, TempType.BOOST),
    # "5": ModeInfo("fan", None),
    # "6": ModeInfo("fan-disabled", None),
    "8": _ModeInfo(HeatMode.PROGRAM, TempType.COMFORT),
    "11": _ModeInfo(HeatMode.PROGRAM, TempType.ECO),
    # "13": ModeInfo("program", None),
    # "15": ModeInfo("manual", "manual"),
    # "16": ModeInfo("program", "boost"),
}

_HEAT_MODE_TO_DEVICE: dict[HeatMode, str] = {
    HeatMode.ECO: "3",
    HeatMode.FROST: "2",
    HeatMode.COMFORT: "0",
    HeatMode.PROGRAM: "11",
    HeatMode.BOOST: "4",
    HeatMode.OFF: "1",
}

_HEAT_MODE_TO_WRITABLE_TEMP_TYPE: dict[HeatMode, TempType] = {
    HeatMode.ECO: TempType.ECO,
    HeatMode.FROST: TempType.FROST,
    HeatMode.COMFORT: TempType.COMFORT,
    HeatMode.BOOST: TempType.BOOST,
}

_TEMP_TYPE_TO_DEVICE: dict[TempType, str] = {
    TempType.ECO: "consigne_eco",
    TempType.FROST: "consigne_hg",
    TempType.COMFORT: "consigne_confort",
    TempType.CURRENT: "temperature_air",
    TempType.MANUAL: "consigne_manuel",
    TempType.BOOST: "consigne_boost",
}

_AVAILABLE_TEMP_TYPES: list[TempType] = [
    TempType.ECO,
    TempType.FROST,
    TempType.COMFORT,
    TempType.CURRENT,
    TempType.BOOST,
]

_READONLY_TEMP_TYPES: list[TempType] = [
    TempType.CURRENT,
    TempType.TARGET,
]

_AVAILABLE_HEAT_MODES: list[HeatMode] = [
    HeatMode.COMFORT,
    HeatMode.ECO,
    HeatMode.FROST,
    HeatMode.PROGRAM,
    HeatMode.BOOST,
    HeatMode.OFF,
]
