"""Asynchronous client for the Watts Vision cloud API."""

from __future__ import annotations

import asyncio
from http import HTTPStatus
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .auth import WattsVisionAuth
from .const import API_URL, REQUEST_TIMEOUT
from .exceptions import (
    WattsVisionAuthenticationError,
    WattsVisionConnectionError,
    WattsVisionResponseError,
)
from .models import (
    JsonObject,
    WattsVisionDeviceMode,
    WattsVisionSmartHome,
    WattsVisionSnapshot,
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

    async def async_get_snapshot(self) -> WattsVisionSnapshot:
        """Return a coherent account snapshot."""
        user_data = await self._async_post_data(
            "/user/read/",
            data={"token": "true", "email": self._username, "lang": "nl_NL"},
        )
        homes = user_data.get("smarthomes")
        if not isinstance(homes, list):
            msg = "Watts Vision returned invalid smart-home data"
            raise WattsVisionResponseError(msg)
        home_objects = tuple(_as_object(home, "smart-home") for home in homes)
        smart_homes = await asyncio.gather(
            *(self._async_get_smart_home(home) for home in home_objects)
        )
        return WattsVisionSnapshot(smart_homes=tuple(smart_homes))

    async def async_set_temperature(
        self,
        smart_home_id: str,
        device_id: str,
        temperature: float,
        mode: WattsVisionDeviceMode,
    ) -> None:
        """Set a thermostat temperature and mode."""
        if mode is WattsVisionDeviceMode.UNKNOWN:
            msg = "Cannot send an unknown Watts Vision thermostat mode"
            raise WattsVisionResponseError(msg)
        value = str(round(temperature * 10))
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
            WattsVisionDeviceMode.COMFORT: {
                "query[consigne_confort]": value,
                "query[consigne_manuel]": value,
            },
            WattsVisionDeviceMode.OFF: {"query[consigne_manuel]": "0"},
            WattsVisionDeviceMode.FROST: {
                "query[consigne_hg]": "446",
                "query[consigne_manuel]": "446",
                "peremption": "20000",
            },
            WattsVisionDeviceMode.ECO: {
                "query[consigne_eco]": value,
                "query[consigne_manuel]": value,
            },
            WattsVisionDeviceMode.BOOST: {
                "query[time_boost]": "7200",
                "query[consigne_boost]": value,
                "query[consigne_manuel]": value,
            },
            WattsVisionDeviceMode.PROGRAM_ECO: {"query[consigne_manuel]": value},
            WattsVisionDeviceMode.MANUAL: {"query[consigne_manuel]": value},
        }
        payload.update(mode_payloads.get(mode, {}))
        await self._async_post("/query/push/", data=payload)

    async def _async_get_smart_home(
        self,
        home_data: JsonObject,
    ) -> WattsVisionSmartHome:
        """Fetch and parse one complete smart home."""
        smart_home_id = home_data.get("smarthome_id")
        if smart_home_id is None or isinstance(smart_home_id, (dict, list)):
            msg = "Watts Vision returned invalid smarthome_id data"
            raise WattsVisionResponseError(msg)
        smart_home_id = str(smart_home_id)
        zones_data, communication_data = await asyncio.gather(
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
        )
        return WattsVisionSmartHome.from_api(
            home_data,
            zones_data,
            communication_data,
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
        access_token = await self._auth.async_get_access_token()
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


def _as_object(value: object, label: str) -> JsonObject:
    """Return a JSON object or raise a response error."""
    if not isinstance(value, dict):
        msg = f"Watts Vision returned invalid {label} data"
        raise WattsVisionResponseError(msg)
    return value
