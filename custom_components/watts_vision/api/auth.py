"""Authentication handling for the Watts Vision cloud API."""

from __future__ import annotations

import asyncio
import math
import time
from http import HTTPStatus
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import (
    AUTH_REJECTION_STATUSES,
    AUTH_URL,
    REQUEST_TIMEOUT,
    TOKEN_EXPIRY_SAFETY_MARGIN,
)
from .exceptions import (
    WattsVisionAuthenticationError,
    WattsVisionConnectionError,
    WattsVisionResponseError,
)


class WattsVisionAuth:
    """Manage Watts Vision access and refresh tokens."""

    def __init__(
        self,
        username: str,
        password: str,
        *,
        session: ClientSession,
    ) -> None:
        """Initialize authentication state."""
        self._username = username
        self._password = password
        self._session = session
        self._access_token: str | None = None
        self._access_token_expires_at = 0.0
        self._refresh_token: str | None = None
        self._refresh_token_expires_at = 0.0
        self._lock = asyncio.Lock()

    async def async_get_access_token(
        self,
        *,
        force_login: bool = False,
        force_refresh: bool = False,
        rejected_token: str | None = None,
    ) -> str:
        """Return a valid access token."""
        now = time.monotonic()
        if (
            not force_login
            and not force_refresh
            and self._access_token is not None
            and self._access_token_expires_at > now
        ):
            return self._access_token

        async with self._lock:
            now = time.monotonic()
            if (
                force_refresh
                and rejected_token is not None
                and self._access_token is not None
                and self._access_token != rejected_token
                and self._access_token_expires_at > now
            ):
                return self._access_token
            if (
                not force_login
                and not force_refresh
                and self._access_token is not None
                and self._access_token_expires_at > now
            ):
                return self._access_token

            use_refresh_token = (
                not force_login
                and self._refresh_token is not None
                and self._refresh_token_expires_at > now
            )
            try:
                return await self._async_request_token(
                    use_refresh_token=use_refresh_token
                )
            except WattsVisionAuthenticationError:
                if not use_refresh_token:
                    raise
                return await self._async_request_token(use_refresh_token=False)

    async def _async_request_token(self, *, use_refresh_token: bool) -> str:
        """Request a new access token."""
        if use_refresh_token:
            payload = {
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id": "app-front",
            }
        else:
            payload = {
                "grant_type": "password",
                "username": self._username,
                "password": self._password,
                "client_id": "app-front",
            }

        try:
            async with self._session.post(
                AUTH_URL,
                data=payload,
                timeout=ClientTimeout(total=REQUEST_TIMEOUT),
            ) as response:
                response_status = response.status
                response_data: Any = (
                    await response.json(content_type=None)
                    if response_status == HTTPStatus.OK
                    else None
                )
        except (TimeoutError, ClientError) as err:
            msg = "Unable to contact the Watts Vision authentication service"
            raise WattsVisionConnectionError(msg) from err
        except (TypeError, ValueError) as err:
            msg = "Watts Vision returned malformed authentication JSON"
            raise WattsVisionResponseError(msg) from err

        if response_status != HTTPStatus.OK:
            if response_status in AUTH_REJECTION_STATUSES:
                msg = (
                    f"Watts Vision authentication failed with status {response_status}"
                )
                raise WattsVisionAuthenticationError(msg)
            msg = (
                f"Watts Vision authentication service returned status {response_status}"
            )
            raise WattsVisionResponseError(msg)

        if not isinstance(response_data, dict):
            msg = "Watts Vision returned a non-object authentication response"
            raise WattsVisionResponseError(msg)
        try:
            access_token = _required_token(response_data, "access_token")
            access_expires_in = _required_duration(response_data, "expires_in")
            refresh_token = _required_token(response_data, "refresh_token")
            refresh_expires_in = _required_duration(
                response_data,
                "refresh_expires_in",
            )
        except (KeyError, TypeError, ValueError) as err:
            msg = "Watts Vision returned an invalid authentication response"
            raise WattsVisionResponseError(msg) from err

        now = time.monotonic()
        self._access_token = access_token
        self._access_token_expires_at = now + _safe_expiry_duration(access_expires_in)
        self._refresh_token = refresh_token
        self._refresh_token_expires_at = now + _safe_expiry_duration(refresh_expires_in)
        return access_token


def _required_token(data: dict[str, Any], key: str) -> str:
    """Return a required non-empty token string."""
    value = data[key]
    if not isinstance(value, str) or not value:
        raise ValueError
    return value


def _required_duration(data: dict[str, Any], key: str) -> float:
    """Return a required finite, non-negative expiry duration."""
    value = float(data[key])
    if not math.isfinite(value) or value < 0:
        raise ValueError
    return value


def _safe_expiry_duration(duration: float) -> float:
    """Return an expiry duration with a clock and network safety margin."""
    return max(duration - TOKEN_EXPIRY_SAFETY_MARGIN, duration * 0.9)
