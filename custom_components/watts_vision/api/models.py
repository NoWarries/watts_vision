"""Immutable models for the Watts Vision cloud API."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, Self

from .exceptions import WattsVisionResponseError

type JsonObject = dict[str, Any]


class WattsVisionDeviceMode(StrEnum):
    """Modes reported and accepted by Watts Vision thermostats."""

    COMFORT = "0"
    OFF = "1"
    FROST = "2"
    ECO = "3"
    BOOST = "4"
    FAN = "5"
    FAN_DISABLED = "6"
    PROGRAM_COMFORT = "8"
    PROGRAM_ECO = "11"
    PROGRAM_UNSPECIFIED = "13"
    MANUAL = "15"
    PROGRAM_BOOST = "16"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class WattsVisionCommunicationAge:
    """Time since a central unit last communicated."""

    days: int
    hours: int
    minutes: int
    seconds: int

    @classmethod
    def from_api(cls, data: JsonObject) -> Self:
        """Parse a communication age response."""
        difference = _required_object(data, "diffObj")
        return cls(
            days=_required_int(difference, "days"),
            hours=_required_int(difference, "hours"),
            minutes=_required_int(difference, "minutes"),
            seconds=_required_int(difference, "seconds"),
        )


@dataclass(frozen=True, slots=True)
class WattsVisionDevice:
    """A Watts Vision thermostat."""

    device_id: str
    api_device_id: str
    mode: WattsVisionDeviceMode
    wire_mode: str
    is_heating: bool
    is_cooling: bool
    battery_low: bool
    air_temperature: float
    min_temperature: float
    max_temperature: float
    eco_temperature: float
    frost_temperature: float
    comfort_temperature: float
    manual_temperature: float
    boost_temperature: float

    @classmethod
    def from_api(cls, data: JsonObject) -> Self:
        """Parse a thermostat response."""
        wire_mode = _required_string(data, "gv_mode")
        try:
            mode = WattsVisionDeviceMode(wire_mode)
        except ValueError:
            # Preserve availability when Watts adds a mode before we model it.
            mode = WattsVisionDeviceMode.UNKNOWN
        return cls(
            device_id=_required_string(data, "id"),
            api_device_id=_required_string(data, "id_device"),
            mode=mode,
            wire_mode=wire_mode,
            is_heating=_required_boolean(data, "heating_up"),
            is_cooling=_required_boolean(data, "heat_cool"),
            battery_low=_required_string(data, "error_code") == "1",
            air_temperature=_required_temperature(data, "temperature_air"),
            min_temperature=_required_temperature(data, "min_set_point"),
            max_temperature=_required_temperature(data, "max_set_point"),
            eco_temperature=_required_temperature(data, "consigne_eco"),
            frost_temperature=_required_temperature(data, "consigne_hg"),
            comfort_temperature=_required_temperature(data, "consigne_confort"),
            manual_temperature=_required_temperature(data, "consigne_manuel"),
            boost_temperature=_required_temperature(data, "consigne_boost"),
        )

    @property
    def target_temperature(self) -> float | None:
        """Return the active target temperature."""
        if self.mode in {
            WattsVisionDeviceMode.OFF,
            WattsVisionDeviceMode.FAN,
            WattsVisionDeviceMode.FAN_DISABLED,
            WattsVisionDeviceMode.PROGRAM_UNSPECIFIED,
            WattsVisionDeviceMode.UNKNOWN,
        }:
            target_temperature = None
        elif self.mode is WattsVisionDeviceMode.FROST:
            target_temperature = self.frost_temperature
        elif self.mode in {
            WattsVisionDeviceMode.ECO,
            WattsVisionDeviceMode.PROGRAM_ECO,
        }:
            target_temperature = self.eco_temperature
        elif self.mode in {
            WattsVisionDeviceMode.BOOST,
            WattsVisionDeviceMode.PROGRAM_BOOST,
        }:
            target_temperature = self.boost_temperature
        elif self.mode is WattsVisionDeviceMode.MANUAL:
            target_temperature = self.manual_temperature
        else:
            target_temperature = self.comfort_temperature
        return target_temperature

    def with_mode(
        self,
        mode: WattsVisionDeviceMode,
        manual_temperature: float,
    ) -> Self:
        """Return a copy with an optimistic mode update."""
        return replace(
            self,
            mode=mode,
            wire_mode=mode.value,
            manual_temperature=manual_temperature,
        )

    def with_target_temperature(self, temperature: float) -> Self:
        """Return a copy with an optimistic target-temperature update."""
        changes: dict[str, float] = {"manual_temperature": temperature}
        if self.mode is WattsVisionDeviceMode.FROST:
            changes["frost_temperature"] = temperature
        elif self.mode in {
            WattsVisionDeviceMode.ECO,
            WattsVisionDeviceMode.PROGRAM_ECO,
        }:
            changes["eco_temperature"] = temperature
        elif self.mode is WattsVisionDeviceMode.BOOST:
            changes["boost_temperature"] = temperature
        elif self.mode is WattsVisionDeviceMode.MANUAL:
            changes["manual_temperature"] = temperature
        elif self.mode is WattsVisionDeviceMode.PROGRAM_BOOST:
            changes["boost_temperature"] = temperature
        else:
            changes["comfort_temperature"] = temperature
        return replace(self, **changes)


@dataclass(frozen=True, slots=True)
class WattsVisionZone:
    """A Watts Vision heating zone."""

    label: str
    devices: tuple[WattsVisionDevice, ...]

    @classmethod
    def from_api(cls, data: JsonObject) -> Self:
        """Parse a heating zone response."""
        devices = _required_list(data, "devices")
        return cls(
            label=_required_string(data, "zone_label"),
            devices=tuple(
                WattsVisionDevice.from_api(_as_object(device, "device"))
                for device in devices
            ),
        )

    def replace_device(self, updated_device: WattsVisionDevice) -> Self:
        """Return a copy containing an updated thermostat."""
        return replace(
            self,
            devices=tuple(
                updated_device
                if device.device_id == updated_device.device_id
                else device
                for device in self.devices
            ),
        )


@dataclass(frozen=True, slots=True)
class WattsVisionSmartHome:
    """A Watts Vision central unit and its zones."""

    smart_home_id: str
    label: str
    mac_address: str
    zones: tuple[WattsVisionZone, ...]
    last_communication: WattsVisionCommunicationAge

    @classmethod
    def from_api(
        cls,
        home_data: JsonObject,
        zones_data: JsonObject,
        communication_data: JsonObject,
    ) -> Self:
        """Parse a complete smart-home response."""
        zones = _required_list(zones_data, "zones")
        return cls(
            smart_home_id=_required_string(home_data, "smarthome_id"),
            label=_required_string(home_data, "label"),
            mac_address=_required_string(home_data, "mac_address"),
            zones=tuple(
                WattsVisionZone.from_api(_as_object(zone, "zone")) for zone in zones
            ),
            last_communication=WattsVisionCommunicationAge.from_api(communication_data),
        )

    def get_device(self, device_id: str) -> WattsVisionDevice | None:
        """Return a thermostat by identifier."""
        for zone in self.zones:
            for device in zone.devices:
                if device.device_id == device_id:
                    return device
        return None

    def replace_device(self, updated_device: WattsVisionDevice) -> Self:
        """Return a copy containing an updated thermostat."""
        return replace(
            self,
            zones=tuple(zone.replace_device(updated_device) for zone in self.zones),
        )


@dataclass(frozen=True, slots=True)
class WattsVisionSnapshot:
    """A coherent Watts Vision account snapshot."""

    smart_homes: tuple[WattsVisionSmartHome, ...]

    def get_smart_home(self, smart_home_id: str) -> WattsVisionSmartHome | None:
        """Return a smart home by identifier."""
        return next(
            (
                smart_home
                for smart_home in self.smart_homes
                if smart_home.smart_home_id == smart_home_id
            ),
            None,
        )

    def get_device(
        self,
        smart_home_id: str,
        device_id: str,
    ) -> WattsVisionDevice | None:
        """Return a thermostat by smart-home and device identifier."""
        smart_home = self.get_smart_home(smart_home_id)
        return smart_home.get_device(device_id) if smart_home is not None else None

    def replace_device(
        self,
        smart_home_id: str,
        updated_device: WattsVisionDevice,
    ) -> Self:
        """Return a copy containing an updated thermostat."""
        return replace(
            self,
            smart_homes=tuple(
                smart_home.replace_device(updated_device)
                if smart_home.smart_home_id == smart_home_id
                else smart_home
                for smart_home in self.smart_homes
            ),
        )


def _as_object(value: object, label: str) -> JsonObject:
    """Return a JSON object or raise a response error."""
    if not isinstance(value, dict):
        msg = f"Watts Vision returned invalid {label} data"
        raise WattsVisionResponseError(msg)
    return value


def _required_object(data: JsonObject, key: str) -> JsonObject:
    """Return a required nested JSON object."""
    try:
        value = data[key]
    except KeyError as err:
        msg = f"Watts Vision response is missing {key}"
        raise WattsVisionResponseError(msg) from err
    return _as_object(value, key)


def _required_list(data: JsonObject, key: str) -> list[object]:
    """Return a required JSON list."""
    try:
        value = data[key]
    except KeyError as err:
        msg = f"Watts Vision response is missing {key}"
        raise WattsVisionResponseError(msg) from err
    if not isinstance(value, list):
        msg = f"Watts Vision returned invalid {key} data"
        raise WattsVisionResponseError(msg)
    return value


def _required_string(data: JsonObject, key: str) -> str:
    """Return a required value as a string."""
    try:
        value = data[key]
    except KeyError as err:
        msg = f"Watts Vision response is missing {key}"
        raise WattsVisionResponseError(msg) from err
    if value is None or isinstance(value, (dict, list)):
        msg = f"Watts Vision returned invalid {key} data"
        raise WattsVisionResponseError(msg)
    return str(value)


def _required_int(data: JsonObject, key: str) -> int:
    """Return a required value as an integer."""
    try:
        return int(data[key])
    except (KeyError, TypeError, ValueError) as err:
        msg = f"Watts Vision returned invalid {key} data"
        raise WattsVisionResponseError(msg) from err


def _required_boolean(data: JsonObject, key: str) -> bool:
    """Return a required wire-format Boolean."""
    value = _required_string(data, key)
    if value not in {"0", "1"}:
        msg = f"Watts Vision returned invalid {key} data"
        raise WattsVisionResponseError(msg)
    return value == "1"


def _required_temperature(data: JsonObject, key: str) -> float:
    """Return a required tenths-of-a-degree value as a float."""
    try:
        return float(data[key]) / 10
    except (KeyError, TypeError, ValueError) as err:
        msg = f"Watts Vision returned invalid {key} data"
        raise WattsVisionResponseError(msg) from err
