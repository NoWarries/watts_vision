"""Asynchronous client for the Watts Vision cloud API."""

from __future__ import annotations

import asyncio
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from http import HTTPStatus
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .auth import WattsVisionAuth
from .const import (
    API_URL,
    DEFAULT_BOOST_DURATION_SECONDS,
    MAX_BOOST_DURATION_SECONDS,
    MIN_BOOST_DURATION_SECONDS,
    REQUEST_TIMEOUT,
)
from .exceptions import (
    WattsVisionAuthenticationError,
    WattsVisionConnectionError,
    WattsVisionError,
    WattsVisionResponseError,
)
from .models import (
    JsonObject,
    WattsVisionCommunicationAge,
    WattsVisionDevice,
    WattsVisionDeviceMode,
    WattsVisionHomeStatus,
    WattsVisionSmartHome,
    WattsVisionSnapshot,
    WattsVisionZone,
)

COMMANDABLE_DEVICE_MODES = frozenset(
    {
        WattsVisionDeviceMode.COMFORT,
        WattsVisionDeviceMode.OFF,
        WattsVisionDeviceMode.FROST,
        WattsVisionDeviceMode.ECO,
        WattsVisionDeviceMode.BOOST,
        WattsVisionDeviceMode.PROGRAM_UNSPECIFIED,
    }
)


class WattsVisionClient:
    """Communicate with the Watts Vision cloud API."""

    def __init__(
        self,
        username: str,
        password: str,
        *,
        session: ClientSession,
    ) -> None:
        """Initialize the client with a caller-owned web session."""
        self._username = username
        self._session = session
        self._auth = WattsVisionAuth(username, password, session=session)

    async def async_validate_credentials(self) -> None:
        """Validate the configured account credentials."""
        await self._auth.async_get_access_token(force_login=True)

    async def async_get_snapshot(
        self,
        previous_snapshot: WattsVisionSnapshot | None = None,
    ) -> WattsVisionSnapshot:
        """Return an account snapshot with failures isolated by smart home."""
        user_data = await self._async_post_data(
            "/user/read/",
            data={"token": "true", "email": self._username, "lang": "nl_NL"},
        )
        homes = user_data.get("smarthomes")
        if not isinstance(homes, list):
            msg = "Watts Vision returned invalid smart-home data"
            raise WattsVisionResponseError(msg)
        valid_homes: list[JsonObject] = []
        returned_home_ids: set[str] = set()
        issues: list[str] = []
        account_complete = True
        for raw_home in homes:
            try:
                home = _as_object(raw_home, "smart-home")
                home_id = _required_text(home, "smarthome_id")
            except WattsVisionResponseError:
                account_complete = False
                issues.append("malformed_smart_home")
                continue
            valid_homes.append(home)
            returned_home_ids.add(home_id)

        results = await asyncio.gather(
            *(
                self._async_get_smart_home(
                    home,
                    previous_snapshot.get_smart_home(
                        _required_text(home, "smarthome_id")
                    )
                    if previous_snapshot is not None
                    else None,
                )
                for home in valid_homes
            ),
            return_exceptions=True,
        )
        smart_homes: list[WattsVisionSmartHome] = []
        statuses: dict[str, WattsVisionHomeStatus] = {}
        fresh_devices: set[tuple[str, str]] = set()
        for home, result in zip(valid_homes, results, strict=True):
            home_id = _required_text(home, "smarthome_id")
            if isinstance(result, WattsVisionAuthenticationError):
                raise result
            if isinstance(result, BaseException):
                if not isinstance(result, WattsVisionError):
                    raise result
                previous_home = (
                    previous_snapshot.get_smart_home(home_id)
                    if previous_snapshot is not None
                    else None
                )
                if previous_home is None:
                    issues.append("smart_home_unavailable")
                    continue
                smart_homes.append(previous_home)
                statuses[home_id] = WattsVisionHomeStatus(
                    topology_fresh=False,
                    topology_complete=False,
                    communication_fresh=False,
                    issues=("smart_home_unavailable",),
                )
                continue
            parsed_home, status, home_fresh_devices = result
            smart_homes.append(parsed_home)
            statuses[home_id] = status
            fresh_devices.update(
                (home_id, device_id) for device_id in home_fresh_devices
            )

        if not account_complete and previous_snapshot is not None:
            for previous_home in previous_snapshot.smart_homes:
                home_id = previous_home.smart_home_id
                if home_id in returned_home_ids:
                    continue
                smart_homes.append(previous_home)
                statuses[home_id] = WattsVisionHomeStatus(
                    topology_fresh=False,
                    topology_complete=False,
                    communication_fresh=False,
                    issues=("account_topology_incomplete",),
                )

        if previous_snapshot is None and not smart_homes:
            msg = "Watts Vision returned no usable smart-home data"
            raise WattsVisionResponseError(msg)
        return WattsVisionSnapshot(
            smart_homes=tuple(smart_homes),
            account_complete=account_complete,
            home_status=statuses,
            fresh_devices=frozenset(fresh_devices),
            issues=tuple(issues),
        )

    async def async_set_temperature(
        self,
        smart_home_id: str,
        device_id: str,
        temperature: float,
        mode: WattsVisionDeviceMode,
        *,
        boost_duration: int = DEFAULT_BOOST_DURATION_SECONDS,
    ) -> None:
        """Set a thermostat temperature and mode."""
        if mode not in COMMANDABLE_DEVICE_MODES:
            msg = f"Cannot command Watts Vision thermostat mode {mode.value}"
            raise WattsVisionResponseError(msg)
        value = _encode_temperature_tenths(temperature)
        if mode is WattsVisionDeviceMode.BOOST and (
            not MIN_BOOST_DURATION_SECONDS
            <= boost_duration
            <= MAX_BOOST_DURATION_SECONDS
            or boost_duration % 60
        ):
            msg = "Boost duration must be a whole minute within device limits"
            raise WattsVisionResponseError(msg)
        payload = {
            "token": "true",
            "context": "1",
            "smarthome_id": smart_home_id,
            "query[id_device]": device_id,
            "query[time_boost]": "0",
            "query[gv_mode]": mode.value,
            "query[nv_mode]": mode.value,
            "peremption": "15000",
            "lang": "nl_NL",
        }
        mode_payloads: dict[WattsVisionDeviceMode, dict[str, str]] = {
            WattsVisionDeviceMode.COMFORT: {"query[consigne_confort]": value},
            WattsVisionDeviceMode.OFF: {},
            WattsVisionDeviceMode.FROST: {
                "query[consigne_hg]": "446",
                "peremption": "20000",
            },
            WattsVisionDeviceMode.ECO: {"query[consigne_eco]": value},
            WattsVisionDeviceMode.BOOST: {
                "query[time_boost]": str(boost_duration),
                "query[consigne_boost]": value,
                "query[consigne_manuel]": value,
            },
            # The central unit resolves this generic Program request to the
            # current weekly phase; no schedule or setpoint fields are sent.
            WattsVisionDeviceMode.PROGRAM_UNSPECIFIED: {},
        }
        payload.update(mode_payloads[mode])
        await self._async_post("/query/push/", data=payload)

    async def async_get_communication_age(
        self,
        smart_home_id: str,
    ) -> WattsVisionCommunicationAge:
        """Return a central unit's current server communication age."""
        data = await self._async_post_data(
            "/sandbox/check_last_connexion/",
            data={
                "token": "true",
                "smarthome_id": smart_home_id,
                "lang": "nl_NL",
            },
        )
        return WattsVisionCommunicationAge.from_api(data)

    async def _async_get_smart_home(
        self,
        home_data: JsonObject,
        previous_home: WattsVisionSmartHome | None,
    ) -> tuple[WattsVisionSmartHome, WattsVisionHomeStatus, set[str]]:
        """Fetch one smart home while isolating topology and metadata failures."""
        smart_home_id = _required_text(home_data, "smarthome_id")
        label = _required_text(home_data, "label", allow_empty=True)
        mac_address = _required_text(home_data, "mac_address")
        zones_result, communication_result = await asyncio.gather(
            self._async_post_data(
                "/smarthome/read/",
                data={
                    "token": "true",
                    "smarthome_id": smart_home_id,
                    "lang": "nl_NL",
                },
            ),
            self._async_post_data(
                "/sandbox/check_last_connexion/",
                data={
                    "token": "true",
                    "smarthome_id": smart_home_id,
                    "lang": "nl_NL",
                },
            ),
            return_exceptions=True,
        )
        for result in (zones_result, communication_result):
            if isinstance(result, WattsVisionAuthenticationError):
                raise result
            if isinstance(result, BaseException) and not isinstance(
                result, WattsVisionError
            ):
                raise result

        issues: list[str] = []
        malformed_records = 0
        topology_fresh = not isinstance(zones_result, BaseException)
        topology_complete = topology_fresh
        fresh_devices: set[str] = set()
        if isinstance(zones_result, BaseException):
            if previous_home is None:
                raise zones_result
            zones = previous_home.zones
            issues.append("topology_unavailable")
        else:
            zones, fresh_devices, malformed_records = _parse_zones(
                zones_result,
                previous_home,
            )
            if malformed_records and not fresh_devices and previous_home is None:
                msg = "Watts Vision returned no usable thermostat records"
                raise WattsVisionResponseError(msg)
            topology_complete = malformed_records == 0
            if malformed_records:
                issues.append("malformed_thermostat_records")

        communication_fresh = not isinstance(communication_result, BaseException)
        if isinstance(communication_result, BaseException):
            communication = (
                previous_home.last_communication if previous_home is not None else None
            )
            issues.append("communication_unavailable")
        else:
            try:
                communication = WattsVisionCommunicationAge.from_api(
                    communication_result
                )
            except WattsVisionResponseError:
                communication_fresh = False
                communication = (
                    previous_home.last_communication
                    if previous_home is not None
                    else None
                )
                issues.append("communication_malformed")

        return (
            WattsVisionSmartHome(
                smart_home_id=smart_home_id,
                label=label,
                mac_address=mac_address,
                zones=zones,
                last_communication=communication,
            ),
            WattsVisionHomeStatus(
                topology_fresh=topology_fresh,
                topology_complete=topology_complete,
                communication_fresh=communication_fresh,
                malformed_records=malformed_records,
                issues=tuple(issues),
            ),
            fresh_devices,
        )

    async def _async_post_data(
        self,
        path: str,
        *,
        data: dict[str, str],
    ) -> JsonObject:
        """Post to an API endpoint and return its data object."""
        response_data = await self._async_post(path, data=data)
        result = response_data.get("data")
        if not isinstance(result, dict):
            msg = "Watts Vision returned invalid response data"
            raise WattsVisionResponseError(msg)
        return result

    async def _async_post(
        self,
        path: str,
        *,
        data: dict[str, str],
    ) -> JsonObject:
        """Post to an authenticated API endpoint."""
        rejected_token: str | None = None
        for attempt in range(2):
            access_token = await self._auth.async_get_access_token(
                force_refresh=attempt == 1,
                rejected_token=rejected_token,
            )
            try:
                async with self._session.post(
                    f"{API_URL}{path}",
                    headers={"Authorization": f"Bearer {access_token}"},
                    data=data,
                    timeout=ClientTimeout(total=REQUEST_TIMEOUT),
                ) as response:
                    response_status = response.status
                    response_data: Any = (
                        await response.json(content_type=None)
                        if response_status == HTTPStatus.OK
                        else None
                    )
            except (TimeoutError, ClientError) as err:
                msg = "Unable to contact the Watts Vision API"
                raise WattsVisionConnectionError(msg) from err
            except (TypeError, ValueError) as err:
                msg = "Watts Vision returned malformed JSON"
                raise WattsVisionResponseError(msg) from err

            if response_status == HTTPStatus.UNAUTHORIZED and attempt == 0:
                rejected_token = access_token
                continue
            if response_status == HTTPStatus.UNAUTHORIZED:
                msg = "Watts Vision authentication is no longer valid"
                raise WattsVisionAuthenticationError(msg)
            if response_status != HTTPStatus.OK:
                msg = f"Watts Vision returned HTTP status {response_status}"
                raise WattsVisionResponseError(msg)

            if not isinstance(response_data, dict):
                msg = "Watts Vision returned a non-object JSON response"
                raise WattsVisionResponseError(msg)
            code = response_data.get("code")
            if not isinstance(code, dict) or "OK" not in str(code.get("key", "")):
                msg = f"Watts Vision rejected the request: {code}"
                raise WattsVisionResponseError(msg)
            return response_data

        msg = "Watts Vision authentication is no longer valid"
        raise WattsVisionAuthenticationError(msg)


def _as_object(value: object, label: str) -> JsonObject:
    """Return a JSON object or raise a response error."""
    if not isinstance(value, dict):
        msg = f"Watts Vision returned invalid {label} data"
        raise WattsVisionResponseError(msg)
    return value


def _required_text(
    data: JsonObject,
    key: str,
    *,
    allow_empty: bool = False,
) -> str:
    """Return a required scalar response field as text."""
    try:
        value = data[key]
    except KeyError as err:
        msg = f"Watts Vision response is missing {key}"
        raise WattsVisionResponseError(msg) from err
    if value is None or isinstance(value, (dict, list)):
        msg = f"Watts Vision returned invalid {key} data"
        raise WattsVisionResponseError(msg)
    text = str(value).strip()
    if not allow_empty and not text:
        msg = f"Watts Vision returned empty {key} data"
        raise WattsVisionResponseError(msg)
    return text


def _parse_zones(  # noqa: PLR0912, PLR0915
    zones_data: JsonObject,
    previous_home: WattsVisionSmartHome | None,
) -> tuple[tuple[WattsVisionZone, ...], set[str], int]:
    """Parse thermostat records independently and retain trustworthy old data."""
    raw_zones = zones_data.get("zones")
    if not isinstance(raw_zones, list):
        msg = "Watts Vision returned invalid zones data"
        raise WattsVisionResponseError(msg)

    previous_devices = {
        device.device_id: (zone.label, device)
        for zone in (() if previous_home is None else previous_home.zones)
        for device in zone.devices
    }
    zone_devices: dict[str, list[WattsVisionDevice]] = {}
    zone_order: list[str] = []
    seen_devices: set[str] = set()
    fresh_devices: set[str] = set()
    malformed_records = 0

    for raw_zone in raw_zones:
        if not isinstance(raw_zone, dict):
            malformed_records += 1
            continue
        try:
            zone_label = _required_text(raw_zone, "zone_label", allow_empty=True)
        except WattsVisionResponseError:
            malformed_records += 1
            continue
        raw_devices = raw_zone.get("devices")
        if not isinstance(raw_devices, list):
            malformed_records += 1
            continue
        if zone_label not in zone_devices:
            zone_devices[zone_label] = []
            zone_order.append(zone_label)

        for raw_device in raw_devices:
            device_id: str | None = None
            if isinstance(raw_device, dict):
                raw_device_id = raw_device.get("id")
                if raw_device_id is not None and not isinstance(
                    raw_device_id, (dict, list)
                ):
                    device_id = str(raw_device_id).strip() or None
            try:
                device = WattsVisionDevice.from_api(
                    _as_object(raw_device, "thermostat")
                )
            except WattsVisionResponseError:
                malformed_records += 1
                if device_id is not None and device_id in previous_devices:
                    old_zone, previous_device = previous_devices[device_id]
                    target_zone = zone_label or old_zone
                    if previous_device.device_id not in seen_devices:
                        zone_devices.setdefault(target_zone, []).append(previous_device)
                        if target_zone not in zone_order:
                            zone_order.append(target_zone)
                        seen_devices.add(previous_device.device_id)
                continue
            if device.device_id in seen_devices:
                malformed_records += 1
                continue
            zone_devices[zone_label].append(device)
            seen_devices.add(device.device_id)
            fresh_devices.add(device.device_id)

    if malformed_records and previous_home is not None:
        for previous_zone in previous_home.zones:
            for previous_device in previous_zone.devices:
                if previous_device.device_id in seen_devices:
                    continue
                zone_devices.setdefault(previous_zone.label, []).append(previous_device)
                if previous_zone.label not in zone_order:
                    zone_order.append(previous_zone.label)
                seen_devices.add(previous_device.device_id)

    return (
        tuple(
            WattsVisionZone(label=label, devices=tuple(zone_devices[label]))
            for label in zone_order
        ),
        fresh_devices,
        malformed_records,
    )


def _encode_temperature_tenths(temperature: float) -> str:
    """Encode an already-quantized Fahrenheit temperature as wire tenths."""
    try:
        value = Decimal(str(temperature))
    except InvalidOperation as err:
        msg = "Cannot encode an invalid thermostat temperature"
        raise WattsVisionResponseError(msg) from err
    if not value.is_finite():
        msg = "Cannot encode a non-finite thermostat temperature"
        raise WattsVisionResponseError(msg)
    return str((value * Decimal(10)).to_integral_value(rounding=ROUND_HALF_UP))
