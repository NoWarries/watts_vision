"""Immutable models for the Watts Vision cloud API."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Self

from .exceptions import WattsVisionResponseError

if TYPE_CHECKING:
    from collections.abc import Mapping

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
            days=_required_non_negative_int(difference, "days"),
            hours=_required_non_negative_int(difference, "hours"),
            minutes=_required_non_negative_int(difference, "minutes"),
            seconds=_required_non_negative_int(difference, "seconds"),
        )

    def as_timedelta(self) -> timedelta:
        """Return the communication age as a duration."""
        return timedelta(
            days=self.days,
            hours=self.hours,
            minutes=self.minutes,
            seconds=self.seconds,
        )


@dataclass(frozen=True, slots=True)
class WattsVisionHomeStatus:
    """Describe the trustworthiness of one smart-home update."""

    topology_fresh: bool = True
    topology_complete: bool = True
    communication_fresh: bool = True
    malformed_records: int = 0
    issues: tuple[str, ...] = ()


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
        wire_mode = _required_non_empty_string(data, "gv_mode")
        try:
            mode = WattsVisionDeviceMode(wire_mode)
        except ValueError:
            # Preserve availability when Watts adds a mode before we model it.
            mode = WattsVisionDeviceMode.UNKNOWN
        device = cls(
            device_id=_required_non_empty_string(data, "id"),
            api_device_id=_required_non_empty_string(data, "id_device"),
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
        if device.min_temperature > device.max_temperature:
            msg = "Watts Vision returned inverted thermostat temperature limits"
            raise WattsVisionResponseError(msg)
        return device

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

    def with_command(
        self,
        mode: WattsVisionDeviceMode,
        temperature: float,
        *,
        update_target: bool,
    ) -> Self:
        """Return the state expected after an accepted thermostat command."""
        # The production client submits Program Boost as a mode-only command.
        # Keeping the previous manual target prevents reconciliation from waiting
        # for a field that was never sent to the thermostat.
        updated = (
            replace(self, mode=mode, wire_mode=mode.value)
            if mode is WattsVisionDeviceMode.PROGRAM_BOOST
            else self.with_mode(mode, temperature)
        )
        if not update_target and mode is WattsVisionDeviceMode.PROGRAM_ECO:
            return updated
        if mode is WattsVisionDeviceMode.COMFORT:
            return replace(updated, comfort_temperature=temperature)
        if mode is WattsVisionDeviceMode.ECO:
            return replace(updated, eco_temperature=temperature)
        if mode is WattsVisionDeviceMode.FROST:
            return replace(updated, frost_temperature=temperature)
        if mode is WattsVisionDeviceMode.BOOST:
            return replace(updated, boost_temperature=temperature)
        return updated


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
    last_communication: WattsVisionCommunicationAge | None

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
            smart_home_id=_required_non_empty_string(home_data, "smarthome_id"),
            label=_required_string(home_data, "label"),
            mac_address=_required_non_empty_string(home_data, "mac_address"),
            zones=tuple(
                WattsVisionZone.from_api(_as_object(zone, "zone")) for zone in zones
            ),
            last_communication=WattsVisionCommunicationAge.from_api(communication_data),
        )

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
    account_complete: bool = True
    home_status: Mapping[str, WattsVisionHomeStatus] = field(default_factory=dict)
    fresh_devices: frozenset[tuple[str, str]] | None = None
    issues: tuple[str, ...] = ()
    _home_index: Mapping[str, WattsVisionSmartHome] = field(
        init=False,
        repr=False,
        compare=False,
    )
    _device_index: Mapping[tuple[str, str], WattsVisionDevice] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        """Build immutable indexes and reject ambiguous identifiers."""
        home_index = {home.smart_home_id: home for home in self.smart_homes}
        if len(home_index) != len(self.smart_homes):
            msg = "Watts Vision returned duplicate smart-home identifiers"
            raise WattsVisionResponseError(msg)
        device_index = {
            (home.smart_home_id, device.device_id): device
            for home in self.smart_homes
            for zone in home.zones
            for device in zone.devices
        }
        device_count = sum(
            len(zone.devices) for home in self.smart_homes for zone in home.zones
        )
        if len(device_index) != device_count:
            msg = "Watts Vision returned duplicate thermostat identifiers"
            raise WattsVisionResponseError(msg)
        object.__setattr__(self, "_home_index", MappingProxyType(home_index))
        object.__setattr__(self, "_device_index", MappingProxyType(device_index))
        statuses = {
            home_id: self.home_status.get(home_id, WattsVisionHomeStatus())
            for home_id in home_index
        }
        object.__setattr__(self, "home_status", MappingProxyType(statuses))
        if self.fresh_devices is None:
            object.__setattr__(self, "fresh_devices", frozenset(device_index))

    def get_smart_home(self, smart_home_id: str) -> WattsVisionSmartHome | None:
        """Return a smart home by identifier."""
        return self._home_index.get(smart_home_id)

    def get_device(
        self,
        smart_home_id: str,
        device_id: str,
    ) -> WattsVisionDevice | None:
        """Return a thermostat by smart-home and device identifier."""
        return self._device_index.get((smart_home_id, device_id))

    def is_home_available(self, smart_home_id: str) -> bool:
        """Return whether a home's topology was refreshed successfully."""
        status = self.home_status.get(smart_home_id)
        return status is not None and status.topology_fresh

    def is_communication_available(self, smart_home_id: str) -> bool:
        """Return whether communication metadata is fresh."""
        status = self.home_status.get(smart_home_id)
        return status is not None and status.communication_fresh

    def is_device_available(self, smart_home_id: str, device_id: str) -> bool:
        """Return whether a thermostat record was refreshed successfully."""
        fresh_devices = self.fresh_devices
        return fresh_devices is not None and (smart_home_id, device_id) in fresh_devices

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


def _required_non_empty_string(data: JsonObject, key: str) -> str:
    """Return a required, non-empty string value."""
    value = _required_string(data, key).strip()
    if not value:
        msg = f"Watts Vision returned empty {key} data"
        raise WattsVisionResponseError(msg)
    return value


def _required_int(data: JsonObject, key: str) -> int:
    """Return a required value as an integer."""
    try:
        return int(data[key])
    except (KeyError, TypeError, ValueError) as err:
        msg = f"Watts Vision returned invalid {key} data"
        raise WattsVisionResponseError(msg) from err


def _required_non_negative_int(data: JsonObject, key: str) -> int:
    """Return a required non-negative integer."""
    value = _required_int(data, key)
    if value < 0:
        msg = f"Watts Vision returned negative {key} data"
        raise WattsVisionResponseError(msg)
    return value


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
        value = float(data[key]) / 10
    except (KeyError, TypeError, ValueError) as err:
        msg = f"Watts Vision returned invalid {key} data"
        raise WattsVisionResponseError(msg) from err
    if not math.isfinite(value):
        msg = f"Watts Vision returned non-finite {key} data"
        raise WattsVisionResponseError(msg)
    return value
