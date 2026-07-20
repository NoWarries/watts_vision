"""
This module contains the constants for the WattsVision integration.
Constants are immutable variables which reference static values.
This ensures consistency across the integration.
"""

import logging

from homeassistant.components.climate.const import (
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

PRESET_MODE_MAP = {
    "0": PRESET_COMFORT,
    "1": PRESET_OFF,
    "2": PRESET_DEFROST,
    "3": PRESET_ECO,
    "4": PRESET_BOOST,
    "8": PRESET_PROGRAM,
    "11": PRESET_PROGRAM,
}

PRESET_MODE_REVERSE_MAP = {
    PRESET_COMFORT: "0",
    PRESET_OFF: "1",
    PRESET_DEFROST: "2",
    PRESET_ECO: "3",
    PRESET_BOOST: "4",
    PRESET_PROGRAM: "11",
}

CONSIGNE_MAP = {
    "0": "consigne_confort",
    "2": "consigne_hg",
    "3": "consigne_eco",
    "4": "consigne_boost",
    "8": "consigne_confort",
    "11": "consigne_eco",
}
