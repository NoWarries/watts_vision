"""Synchronous client for the Watts Vision cloud API."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import requests

_LOGGER = logging.getLogger(__name__)

AUTH_URL = (
    "https://auth.smarthome.wattselectronics.com/realms/watts/protocol/"
    "openid-connect/token"
)
API_URL = "https://smarthome.wattselectronics.com/api/v0.1/human"
REQUEST_TIMEOUT = 30

type JsonObject = dict[str, Any]


class WattsApiError(Exception):
    """Base error raised by the Watts Vision API client."""


class WattsAuthenticationError(WattsApiError):
    """Raised when Watts Vision credentials are rejected."""


class WattsApi:
    """Interface to the Watts Vision cloud API."""

    def __init__(self, username: str, password: str) -> None:
        """Initialize the API client."""
        self._username = username
        self._password = password
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._refresh_token: str | None = None
        self._refresh_expires_at = 0.0
        self._refresh_lock = threading.Lock()
        self._smart_home_data: list[JsonObject] = []

    def test_authentication(self) -> bool:
        """Return whether the configured credentials can authenticate."""
        try:
            self.get_login_token(force_login=True)
        except WattsApiError:
            return False
        return True

    def get_login_token(self, *, force_login: bool = False) -> str:
        """Return a valid access token, using login or refresh as needed."""
        now = time.monotonic()
        if (
            force_login
            or self._refresh_token is None
            or self._refresh_expires_at <= now
        ):
            _LOGGER.debug("Logging in to obtain an access token")
            payload = {
                "grant_type": "password",
                "username": self._username,
                "password": self._password,
                "client_id": "app-front",
            }
        elif self._token is not None and self._token_expires_at > now:
            return self._token
        else:
            _LOGGER.debug("Refreshing the Watts Vision access token")
            payload = {
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id": "app-front",
            }

        try:
            response = requests.post(
                AUTH_URL,
                data=payload,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as err:
            msg = "Unable to contact the Watts Vision authentication service"
            raise WattsApiError(msg) from err

        if response.status_code != requests.codes.ok:
            if payload["grant_type"] == "refresh_token":
                _LOGGER.warning(
                    "Token refresh failed; retrying with account credentials"
                )
                return self.get_login_token(force_login=True)
            msg = (
                f"Watts Vision authentication failed with status {response.status_code}"
            )
            raise WattsAuthenticationError(msg)

        response_data = self._json_object(response)
        try:
            token = str(response_data["access_token"])
            expires_in = float(response_data["expires_in"])
            refresh_token = str(response_data["refresh_token"])
            refresh_expires_in = float(response_data["refresh_expires_in"])
        except (KeyError, TypeError, ValueError) as err:
            msg = "Watts Vision returned an invalid authentication response"
            raise WattsApiError(msg) from err

        self._token = token
        self._token_expires_at = now + expires_in
        self._refresh_token = refresh_token
        self._refresh_expires_at = now + refresh_expires_in
        _LOGGER.debug("Received a Watts Vision access token")
        return token

    def load_data(self) -> bool:
        """Load smart homes and their devices."""
        self._smart_home_data = self.load_smart_homes()
        return self.reload_devices()

    def load_smart_homes(self) -> list[JsonObject]:
        """Load the smart homes associated with the account."""
        self._refresh_token_if_expired()
        response = self._post(
            f"{API_URL}/user/read/",
            data={"token": "true", "email": self._username, "lang": "nl_NL"},
        )
        response_data = self._validated_data(response)
        smart_homes = response_data.get("smarthomes")
        if not isinstance(smart_homes, list):
            msg = "Watts Vision returned invalid smart-home data"
            raise WattsApiError(msg)
        return smart_homes

    def load_devices(self, smart_home_id: str) -> list[JsonObject]:
        """Load all zones and devices for a smart home."""
        self._refresh_token_if_expired()
        response = self._post(
            f"{API_URL}/smarthome/read/",
            data={
                "token": "true",
                "smarthome_id": smart_home_id,
                "lang": "nl_NL",
            },
        )
        zones = self._validated_data(response).get("zones")
        if not isinstance(zones, list):
            msg = "Watts Vision returned invalid zone data"
            raise WattsApiError(msg)
        return zones

    def _refresh_token_if_expired(self) -> None:
        """Refresh an expired access token without concurrent refreshes."""
        if self._token is not None and self._token_expires_at > time.monotonic():
            return
        with self._refresh_lock:
            if self._token is None or self._token_expires_at <= time.monotonic():
                self.get_login_token()

    def reload_devices(self) -> bool:
        """Reload devices for every known smart home."""
        for smart_home in self._smart_home_data:
            smart_home_id = str(smart_home["smarthome_id"])
            smart_home["zones"] = self.load_devices(smart_home_id)
        return True

    def get_smart_homes(self) -> list[JsonObject]:
        """Return the cached smart homes."""
        return self._smart_home_data

    def get_device(self, smart_home_id: str, device_id: str) -> JsonObject | None:
        """Return a cached device by smart-home and device ID."""
        for smart_home in self._smart_home_data:
            if smart_home.get("smarthome_id") != smart_home_id:
                continue
            for zone in smart_home.get("zones") or []:
                for device in zone.get("devices") or []:
                    if device.get("id") == device_id:
                        return device
        return None

    def push_temperature(
        self,
        smart_home_id: str,
        device_id: str,
        value: str,
        device_mode: str,
    ) -> bool:
        """Push a temperature and mode to a Watts Vision device."""
        self._refresh_token_if_expired()
        payload = {
            "token": "true",
            "context": "1",
            "smarthome_id": smart_home_id,
            "query[id_device]": device_id,
            "query[time_boost]": "0",
            "query[gv_mode]": device_mode,
            "query[nv_mode]": device_mode,
            "peremption": "15000",
            "lang": "nl_NL",
        }
        mode_payloads: dict[str, dict[str, str]] = {
            "0": {
                "query[consigne_confort]": value,
                "query[consigne_manuel]": value,
            },
            "1": {"query[consigne_manuel]": "0"},
            "2": {
                "query[consigne_hg]": "446",
                "query[consigne_manuel]": "446",
                "peremption": "20000",
            },
            "3": {
                "query[consigne_eco]": value,
                "query[consigne_manuel]": value,
            },
            "4": {
                "query[time_boost]": "7200",
                "query[consigne_boost]": value,
                "query[consigne_manuel]": value,
            },
            "11": {"query[consigne_manuel]": value},
        }
        payload.update(mode_payloads.get(device_mode, {}))
        _LOGGER.debug(
            "Pushing temperature %s in mode %s to device %s",
            value,
            device_mode,
            device_id,
        )
        response = self._post(f"{API_URL}/query/push/", data=payload)
        return self.check_response(response)

    def get_last_communication(self, smart_home_id: str) -> JsonObject:
        """Return the last-communication data for a smart home."""
        self._refresh_token_if_expired()
        response = self._post(
            f"{API_URL}/sandbox/check_last_connexion/",
            data={
                "token": "true",
                "smarthome_id": smart_home_id,
                "lang": "nl_NL",
            },
        )
        return self._validated_data(response)

    def _post(self, url: str, *, data: dict[str, str]) -> requests.Response:
        """Make an authenticated POST request."""
        if self._token is None:
            msg = "A Watts Vision access token is not available"
            raise WattsAuthenticationError(msg)
        try:
            return requests.post(
                url,
                headers={"Authorization": f"Bearer {self._token}"},
                data=data,
                timeout=REQUEST_TIMEOUT,
            )
        except requests.RequestException as err:
            msg = "Unable to contact the Watts Vision API"
            raise WattsApiError(msg) from err

    @classmethod
    def _validated_data(cls, response: requests.Response) -> JsonObject:
        """Validate a response and return its data object."""
        if response.status_code == requests.codes.unauthorized:
            msg = "Watts Vision authentication is no longer valid"
            raise WattsAuthenticationError(msg)
        if not cls.check_response(response):
            msg = "Watts Vision returned an unsuccessful response"
            raise WattsApiError(msg)
        response_data = cls._json_object(response)
        data = response_data.get("data")
        if not isinstance(data, dict):
            msg = "Watts Vision returned invalid response data"
            raise WattsApiError(msg)
        return data

    @staticmethod
    def check_response(response: requests.Response) -> bool:
        """Return whether a Watts Vision API response indicates success."""
        try:
            response_data = WattsApi._json_object(response)
        except WattsApiError:
            _LOGGER.exception("Watts Vision returned malformed JSON")
            return False

        if response.status_code == requests.codes.ok:
            code = response_data.get("code")
            if isinstance(code, dict) and "OK" in str(code.get("key", "")):
                return True
            _LOGGER.error("Watts Vision rejected the request: %s", code)
            return False

        _LOGGER.error("Watts Vision returned HTTP status %s", response.status_code)
        return False

    @staticmethod
    def _json_object(response: requests.Response) -> JsonObject:
        """Decode a response as a JSON object."""
        try:
            response_data = response.json()
        except requests.JSONDecodeError as err:
            msg = "Watts Vision returned malformed JSON"
            raise WattsApiError(msg) from err
        if not isinstance(response_data, dict):
            msg = "Watts Vision returned a non-object JSON response"
            raise WattsApiError(msg)
        return response_data
