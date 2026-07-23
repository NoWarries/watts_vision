"""Test the Home Assistant-independent Watts Vision API package."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from http import HTTPStatus
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from aiohttp import ClientConnectionError, ClientResponse, ClientSession
from aioresponses import aioresponses

from custom_components.watts_vision.api import (
    WattsVisionAuthenticationError,
    WattsVisionClient,
    WattsVisionCommunicationAge,
    WattsVisionConnectionError,
    WattsVisionDevice,
    WattsVisionDeviceMode,
    WattsVisionResponseError,
    WattsVisionSmartHome,
    WattsVisionSnapshot,
    WattsVisionZone,
)
from custom_components.watts_vision.api.const import API_URL, AUTH_URL

if TYPE_CHECKING:
    from collections.abc import Mapping

AUTH_RESPONSE = {
    "access_token": "access-token",
    "expires_in": 3600,
    "refresh_token": "refresh-token",
    "refresh_expires_in": 7200,
}
SUCCESS_RESPONSE = {"code": {"key": "OK"}, "data": {}}
PUSH_URL = f"{API_URL}/query/push/"
USER_URL = f"{API_URL}/user/read/"
HOME_URL = f"{API_URL}/smarthome/read/"
COMMUNICATION_URL = f"{API_URL}/sandbox/check_last_connexion/"
EXPECTED_AIR_TEMPERATURE = 71.5
REFRESHED_AIR_TEMPERATURE = 70.0
EXPECTED_COMMAND_COUNT = 2
EXPECTED_HOME_COUNT = 2
EXPECTED_MALFORMED_RECORDS = 6


class _Aiohttp314ClientResponse(ClientResponse):
    """Bridge aioresponses to aiohttp's required stream-writer argument."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Supply the argument omitted by aioresponses 0.7.x."""
        kwargs.setdefault("stream_writer", SimpleNamespace(output_size=0))
        super().__init__(*args, **kwargs)


def _post(
    mocked_responses: aioresponses,
    url: str,
    **kwargs: Any,
) -> None:
    """Register a response compatible with aiohttp 3.14."""
    mocked_responses.post(
        url,
        response_class=_Aiohttp314ClientResponse,
        **kwargs,
    )


def _recorded_requests(
    mocked_responses: aioresponses,
    url: str,
) -> list[Any]:
    """Return requests recorded for one URL."""
    return next(
        requests
        for (method, request_url), requests in mocked_responses.requests.items()
        if method == "POST" and str(request_url) == url
    )


def _home(home_id: str = "home-1") -> dict[str, str]:
    """Return API-shaped smart-home data."""
    return {
        "smarthome_id": home_id,
        "label": f"Home {home_id}",
        "mac_address": f"00:11:22:33:44:{home_id[-1]}{home_id[-1]}",
    }


def _device(device_id: str = "home-1#C001-000") -> dict[str, str]:
    """Return API-shaped thermostat data."""
    return {
        "id": device_id,
        "id_device": f"api-{device_id}",
        "gv_mode": "0",
        "heating_up": "1",
        "heat_cool": "0",
        "temperature_air": "715",
        "min_set_point": "500",
        "max_set_point": "900",
        "consigne_eco": "620",
        "consigne_hg": "446",
        "consigne_confort": "680",
        "consigne_manuel": "680",
        "consigne_boost": "720",
        "error_code": "1",
    }


def _success(data: object) -> dict[str, object]:
    """Wrap API data in a successful response."""
    return {"code": {"key": "OK"}, "data": data}


def _previous_snapshot(
    *,
    devices: list[dict[str, str]] | None = None,
) -> WattsVisionSnapshot:
    """Return an established snapshot for partial-update tests."""
    communication = {"diffObj": {"days": 0, "hours": 1, "minutes": 2, "seconds": 3}}
    home = WattsVisionSmartHome.from_api(
        _home(),
        {
            "zones": [
                {
                    "zone_label": "Living room",
                    "devices": devices or [_device()],
                }
            ]
        },
        communication,
    )
    return WattsVisionSnapshot(smart_homes=(home,))


def _request_data(
    mocked_responses: aioresponses,
    url: str,
    index: int = 0,
) -> Mapping[str, str]:
    """Return form data recorded by aioresponses."""
    request = _recorded_requests(mocked_responses, url)[index]
    data: Any = request.kwargs["data"]
    assert isinstance(data, dict)
    return data


async def test_password_authentication_is_serialized_and_token_is_reused() -> None:
    """Test concurrent commands use one password authentication request."""
    # Arrange - Register one authentication and reusable command responses.
    with aioresponses() as mocked_responses:
        _post(mocked_responses, AUTH_URL, payload=AUTH_RESPONSE)
        _post(mocked_responses, PUSH_URL, payload=SUCCESS_RESPONSE, repeat=True)
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)

            # Act - Submit two commands concurrently.
            await asyncio.gather(
                client.async_set_temperature(
                    "home-1", "device-1", 68.0, WattsVisionDeviceMode.COMFORT
                ),
                client.async_set_temperature(
                    "home-1", "device-2", 62.0, WattsVisionDeviceMode.ECO
                ),
            )

            # Assert - Verify token reuse and caller ownership of the session.
            assert len(_recorded_requests(mocked_responses, AUTH_URL)) == 1
            assert len(_recorded_requests(mocked_responses, PUSH_URL)) == (
                EXPECTED_COMMAND_COUNT
            )
            assert not session.closed


async def test_expired_token_refresh_rejection_falls_back_to_credentials() -> None:
    """Test a rejected refresh token is retried once with credentials."""
    # Arrange - Expire the first token and reject its refresh request.
    expired_response = {**AUTH_RESPONSE, "expires_in": 0}
    with aioresponses() as mocked_responses:
        _post(mocked_responses, AUTH_URL, payload=expired_response)
        _post(mocked_responses, PUSH_URL, payload=SUCCESS_RESPONSE, repeat=True)
        _post(mocked_responses, AUTH_URL, status=HTTPStatus.UNAUTHORIZED)
        _post(mocked_responses, AUTH_URL, payload=AUTH_RESPONSE)
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)

            # Act - Send one command before and one after access-token expiry.
            await client.async_set_temperature(
                "home-1", "device-1", 68.0, WattsVisionDeviceMode.COMFORT
            )
            await client.async_set_temperature(
                "home-1", "device-1", 62.0, WattsVisionDeviceMode.ECO
            )

        # Assert - Verify password, refresh, then credential-fallback grants.
        grants = [
            request.kwargs["data"]["grant_type"]
            for request in _recorded_requests(mocked_responses, AUTH_URL)
        ]
        assert grants == ["password", "refresh_token", "password"]


async def test_concurrent_expired_token_refresh_is_serialized() -> None:
    """Test concurrent requests share one refresh-token grant."""
    expired_response = {**AUTH_RESPONSE, "expires_in": 0}
    with aioresponses() as mocked_responses:
        _post(mocked_responses, AUTH_URL, payload=expired_response)
        _post(mocked_responses, PUSH_URL, payload=SUCCESS_RESPONSE, repeat=True)
        _post(mocked_responses, AUTH_URL, payload=AUTH_RESPONSE)
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)
            await client.async_set_temperature(
                "home-1", "device-1", 68.0, WattsVisionDeviceMode.COMFORT
            )

            await asyncio.gather(
                client.async_set_temperature(
                    "home-1", "device-1", 62.0, WattsVisionDeviceMode.ECO
                ),
                client.async_set_temperature(
                    "home-1", "device-2", 68.0, WattsVisionDeviceMode.COMFORT
                ),
            )

        grants = [
            request.kwargs["data"]["grant_type"]
            for request in _recorded_requests(mocked_responses, AUTH_URL)
        ]
        assert grants == ["password", "refresh_token"]


async def test_authenticated_request_retries_once_after_unauthorized() -> None:
    """Test an API 401 forces a token refresh and one request retry."""
    refreshed_auth = {**AUTH_RESPONSE, "access_token": "replacement-token"}
    with aioresponses() as mocked_responses:
        _post(mocked_responses, AUTH_URL, payload=AUTH_RESPONSE)
        _post(mocked_responses, PUSH_URL, status=HTTPStatus.UNAUTHORIZED)
        _post(mocked_responses, AUTH_URL, payload=refreshed_auth)
        _post(mocked_responses, PUSH_URL, payload=SUCCESS_RESPONSE)
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)

            await client.async_set_temperature(
                "home-1", "device-1", 68.0, WattsVisionDeviceMode.COMFORT
            )

        assert (
            len(_recorded_requests(mocked_responses, AUTH_URL))
            == EXPECTED_COMMAND_COUNT
        )
        assert [
            request.kwargs["data"]["grant_type"]
            for request in _recorded_requests(mocked_responses, AUTH_URL)
        ] == ["password", "refresh_token"]
        requests = _recorded_requests(mocked_responses, PUSH_URL)
        assert len(requests) == EXPECTED_COMMAND_COUNT
        assert requests[0].kwargs["headers"]["Authorization"] == "Bearer access-token"
        assert requests[1].kwargs["headers"]["Authorization"] == (
            "Bearer replacement-token"
        )


async def test_communication_age_uses_production_preflight_payload() -> None:
    """Test the live command-safety check returns a normalized duration."""
    communication = {
        "diff": "61",
        "diffObj": {"days": 0, "hours": 0, "minutes": 1, "seconds": 1},
    }
    with aioresponses() as mocked_responses:
        _post(mocked_responses, AUTH_URL, payload=AUTH_RESPONSE)
        _post(
            mocked_responses,
            COMMUNICATION_URL,
            payload=_success(communication),
        )
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)

            age = await client.async_get_communication_age("home-1")

    assert age == WattsVisionCommunicationAge(0, 0, 1, 1)
    assert _request_data(mocked_responses, COMMUNICATION_URL) == {
        "token": "true",
        "smarthome_id": "home-1",
        "lang": "nl_NL",
    }


async def test_concurrent_unauthorized_requests_share_forced_refresh() -> None:
    """Test concurrent 401 responses trigger only one refresh-token grant."""
    refreshed_auth = {**AUTH_RESPONSE, "access_token": "replacement-token"}
    with aioresponses() as mocked_responses:
        _post(mocked_responses, AUTH_URL, payload=AUTH_RESPONSE)
        _post(mocked_responses, AUTH_URL, payload=refreshed_auth)
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)
            rejected_token = await client._auth.async_get_access_token()  # noqa: SLF001
            tokens = await asyncio.gather(
                client._auth.async_get_access_token(  # noqa: SLF001
                    force_refresh=True,
                    rejected_token=rejected_token,
                ),
                client._auth.async_get_access_token(  # noqa: SLF001
                    force_refresh=True,
                    rejected_token=rejected_token,
                ),
            )

        assert tokens == ["replacement-token", "replacement-token"]
        assert len(_recorded_requests(mocked_responses, AUTH_URL)) == (
            EXPECTED_COMMAND_COUNT
        )
        assert [
            request.kwargs["data"]["grant_type"]
            for request in _recorded_requests(mocked_responses, AUTH_URL)
        ] == ["password", "refresh_token"]


async def test_persistent_unauthorized_response_requires_reauthentication() -> None:
    """Test a second API 401 is exposed as an authentication failure."""
    with aioresponses() as mocked_responses:
        _post(mocked_responses, AUTH_URL, payload=AUTH_RESPONSE, repeat=True)
        _post(
            mocked_responses,
            PUSH_URL,
            status=HTTPStatus.UNAUTHORIZED,
            repeat=True,
        )
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)

            with pytest.raises(WattsVisionAuthenticationError):
                await client.async_set_temperature(
                    "home-1", "device-1", 68.0, WattsVisionDeviceMode.COMFORT
                )

        assert len(_recorded_requests(mocked_responses, PUSH_URL)) == (
            EXPECTED_COMMAND_COUNT
        )


@pytest.mark.parametrize(
    ("response_kwargs", "expected_error"),
    [
        ({"status": HTTPStatus.UNAUTHORIZED}, WattsVisionAuthenticationError),
        ({"exception": TimeoutError()}, WattsVisionConnectionError),
        ({"exception": ClientConnectionError()}, WattsVisionConnectionError),
        ({"body": "not-json"}, WattsVisionResponseError),
        ({"status": HTTPStatus.INTERNAL_SERVER_ERROR}, WattsVisionResponseError),
        ({"payload": {"access_token": "incomplete"}}, WattsVisionResponseError),
    ],
    ids=(
        "authentication",
        "timeout",
        "network",
        "malformed-json",
        "http",
        "schema",
    ),
)
async def test_credential_validation_maps_transport_failures(
    response_kwargs: dict[str, object],
    expected_error: type[Exception],
) -> None:
    """Test credential validation exposes typed transport failures."""
    # Arrange - Register the selected authentication failure.
    with aioresponses() as mocked_responses:
        _post(mocked_responses, AUTH_URL, **response_kwargs)
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)

            # Act - Validate credentials against the failing endpoint.
            with pytest.raises(expected_error):
                await client.async_validate_credentials()

        # Assert - Verify exactly one authentication attempt was made.
        assert len(_recorded_requests(mocked_responses, AUTH_URL)) == 1


async def test_snapshot_is_coherent_typed_and_assembled_for_all_homes() -> None:
    """Test snapshot assembly converts every home response to frozen models."""
    # Arrange - Register two complete smart-home response groups.
    homes = [_home("home-1"), _home("home-2")]
    with aioresponses() as mocked_responses:
        _post(mocked_responses, AUTH_URL, payload=AUTH_RESPONSE)
        _post(mocked_responses, USER_URL, payload=_success({"smarthomes": homes}))
        for home in homes:
            home_id = home["smarthome_id"]
            _post(
                mocked_responses,
                HOME_URL,
                payload=_success(
                    {
                        "zones": [
                            {
                                "zone_label": "Living room",
                                "devices": [_device(f"{home_id}#C001-000")],
                                "unknown": "ignored",
                            }
                        ]
                    }
                ),
            )
            _post(
                mocked_responses,
                COMMUNICATION_URL,
                payload=_success(
                    {
                        "diffObj": {
                            "days": "1",
                            "hours": "2",
                            "minutes": "3",
                            "seconds": "4",
                        }
                    }
                ),
            )
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)

            # Act - Fetch one account snapshot.
            snapshot = await client.async_get_snapshot()

        # Assert - Verify typed conversion and immutable snapshot contents.
        assert len(snapshot.smart_homes) == EXPECTED_HOME_COUNT
        device = snapshot.smart_homes[0].zones[0].devices[0]
        assert device.air_temperature == EXPECTED_AIR_TEMPERATURE
        assert device.is_heating
        assert not device.is_cooling
        assert device.battery_low
        assert snapshot.smart_homes[0].last_communication.days == 1
        assert snapshot.get_smart_home("home-1") is snapshot.smart_homes[0]
        assert snapshot.get_device("home-1", device.device_id) is device
        with pytest.raises(FrozenInstanceError):
            device.air_temperature = 20.0


async def test_snapshot_rejects_invalid_home_collection() -> None:
    """Test account topology must be returned as a list."""
    with aioresponses() as mocked_responses:
        _post(mocked_responses, AUTH_URL, payload=AUTH_RESPONSE)
        _post(
            mocked_responses,
            USER_URL,
            payload=_success({"smarthomes": {"invalid": True}}),
        )
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)
            with pytest.raises(WattsVisionResponseError):
                await client.async_get_snapshot()


async def test_malformed_account_home_retains_previous_topology() -> None:
    """Test an unidentifiable account record cannot prove a home was removed."""
    previous = _previous_snapshot()
    with aioresponses() as mocked_responses:
        _post(mocked_responses, AUTH_URL, payload=AUTH_RESPONSE)
        _post(
            mocked_responses,
            USER_URL,
            payload=_success({"smarthomes": [None]}),
        )
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)
            snapshot = await client.async_get_snapshot(previous)

    assert not snapshot.account_complete
    assert snapshot.get_smart_home("home-1") is previous.smart_homes[0]
    assert not snapshot.is_home_available("home-1")
    assert snapshot.issues == ("malformed_smart_home",)


async def test_failed_home_topology_retains_only_that_home() -> None:
    """Test a home request failure retains its previous topology as unavailable."""
    previous = _previous_snapshot()
    communication = {"diffObj": {"days": 0, "hours": 0, "minutes": 0, "seconds": 0}}
    with aioresponses() as mocked_responses:
        _post(mocked_responses, AUTH_URL, payload=AUTH_RESPONSE)
        _post(
            mocked_responses,
            USER_URL,
            payload=_success({"smarthomes": [_home()]}),
        )
        _post(mocked_responses, HOME_URL, exception=TimeoutError())
        _post(mocked_responses, COMMUNICATION_URL, payload=_success(communication))
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)
            snapshot = await client.async_get_snapshot(previous)

    status = snapshot.home_status["home-1"]
    assert not status.topology_fresh
    assert not status.topology_complete
    assert status.communication_fresh
    assert not snapshot.is_device_available("home-1", "home-1#C001-000")


async def test_one_home_failure_does_not_affect_another_home() -> None:
    """Test account polling accepts one home while retaining a failed sibling."""
    communication = {"diffObj": {"days": 0, "hours": 0, "minutes": 0, "seconds": 0}}
    previous_homes = tuple(
        WattsVisionSmartHome.from_api(
            _home(home_id),
            {
                "zones": [
                    {
                        "zone_label": "Living room",
                        "devices": [_device(f"{home_id}#C001-000")],
                    }
                ]
            },
            communication,
        )
        for home_id in ("home-1", "home-2")
    )
    previous = WattsVisionSnapshot(smart_homes=previous_homes)
    with aioresponses() as mocked_responses:
        _post(mocked_responses, AUTH_URL, payload=AUTH_RESPONSE)
        _post(
            mocked_responses,
            USER_URL,
            payload=_success({"smarthomes": [_home("home-1"), _home("home-2")]}),
        )
        _post(mocked_responses, HOME_URL, exception=TimeoutError())
        _post(
            mocked_responses,
            HOME_URL,
            payload=_success(
                {
                    "zones": [
                        {
                            "zone_label": "Living room",
                            "devices": [_device("home-2#C001-000")],
                        }
                    ]
                }
            ),
        )
        _post(
            mocked_responses,
            COMMUNICATION_URL,
            payload=_success(communication),
            repeat=2,
        )
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)
            snapshot = await client.async_get_snapshot(previous)

    assert not snapshot.is_home_available("home-1")
    assert snapshot.is_home_available("home-2")
    assert snapshot.is_device_available("home-2", "home-2#C001-000")


async def test_invalid_home_metadata_retains_previous_home() -> None:
    """Test malformed metadata for an identifiable home is isolated."""
    previous = _previous_snapshot()
    invalid_home = {"smarthome_id": "home-1", "mac_address": "00:11:22:33:44:55"}
    with aioresponses() as mocked_responses:
        _post(mocked_responses, AUTH_URL, payload=AUTH_RESPONSE)
        _post(
            mocked_responses,
            USER_URL,
            payload=_success({"smarthomes": [invalid_home]}),
        )
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)
            snapshot = await client.async_get_snapshot(previous)

    assert snapshot.get_smart_home("home-1") is previous.smart_homes[0]
    assert snapshot.home_status["home-1"].issues == ("smart_home_unavailable",)


async def test_malformed_communication_metadata_is_isolated() -> None:
    """Test invalid communication JSON retains the previous communication age."""
    previous = _previous_snapshot()
    with aioresponses() as mocked_responses:
        _post(mocked_responses, AUTH_URL, payload=AUTH_RESPONSE)
        _post(
            mocked_responses,
            USER_URL,
            payload=_success({"smarthomes": [_home()]}),
        )
        _post(
            mocked_responses,
            HOME_URL,
            payload=_success(
                {"zones": [{"zone_label": "Living room", "devices": [_device()]}]}
            ),
        )
        _post(
            mocked_responses,
            COMMUNICATION_URL,
            payload=_success({"diffObj": {"days": "invalid"}}),
        )
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)
            snapshot = await client.async_get_snapshot(previous)

    assert not snapshot.is_communication_available("home-1")
    assert (
        snapshot.smart_homes[0].last_communication
        == previous.smart_homes[0].last_communication
    )


async def test_malformed_zone_shapes_do_not_discard_valid_siblings() -> None:
    """Test strict record parsing isolates several malformed zone shapes."""
    first = _device("home-1#C001-000")
    second = _device("home-1#C002-000")
    previous = _previous_snapshot(devices=[first, second])
    malformed_second = {**second, "temperature_air": "invalid"}
    zones: list[object] = [
        None,
        {"zone_label": {}, "devices": []},
        {"zone_label": "Broken", "devices": {}},
        {
            "zone_label": "Living room",
            "devices": [None, first, first, malformed_second],
        },
    ]
    communication = {"diffObj": {"days": 0, "hours": 0, "minutes": 0, "seconds": 0}}
    with aioresponses() as mocked_responses:
        _post(mocked_responses, AUTH_URL, payload=AUTH_RESPONSE)
        _post(
            mocked_responses,
            USER_URL,
            payload=_success({"smarthomes": [_home()]}),
        )
        _post(mocked_responses, HOME_URL, payload=_success({"zones": zones}))
        _post(mocked_responses, COMMUNICATION_URL, payload=_success(communication))
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)
            snapshot = await client.async_get_snapshot(previous)

    status = snapshot.home_status["home-1"]
    assert status.malformed_records == EXPECTED_MALFORMED_RECORDS
    assert snapshot.is_device_available("home-1", "home-1#C001-000")
    assert not snapshot.is_device_available("home-1", "home-1#C002-000")
    assert snapshot.get_device("home-1", "home-1#C002-000") is not None


@pytest.mark.parametrize(
    "invalid_device_update",
    [
        {"temperature_air": "not-a-number"},
        {"temperature_air": "nan"},
        {"max_set_point": "inf"},
        {"heating_up": "unsupported"},
        {"error_code": None},
        {"id": " "},
        {"id_device": ""},
        {"min_set_point": "901", "max_set_point": "900"},
    ],
    ids=(
        "temperature",
        "not-a-number",
        "non-finite",
        "boolean",
        "missing-flag",
        "empty-device-id",
        "empty-api-id",
        "inverted-range",
    ),
)
async def test_snapshot_rejects_malformed_required_device_values(
    invalid_device_update: dict[str, object],
) -> None:
    """Test malformed device fields reject the complete snapshot."""
    # Arrange - Register a snapshot containing one malformed required value.
    invalid_device = {**_device(), **invalid_device_update}
    with aioresponses() as mocked_responses:
        _post(mocked_responses, AUTH_URL, payload=AUTH_RESPONSE)
        _post(
            mocked_responses,
            USER_URL,
            payload=_success({"smarthomes": [_home()]}),
        )
        _post(
            mocked_responses,
            HOME_URL,
            payload=_success(
                {"zones": [{"zone_label": "Living room", "devices": [invalid_device]}]}
            ),
        )
        _post(
            mocked_responses,
            COMMUNICATION_URL,
            payload=_success(
                {
                    "diffObj": {
                        "days": 0,
                        "hours": 0,
                        "minutes": 0,
                        "seconds": 0,
                    }
                }
            ),
        )
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)

            # Act - Fetch the invalid snapshot.
            with pytest.raises(WattsVisionResponseError):
                await client.async_get_snapshot()

        # Assert - Verify all three snapshot subrequests were attempted.
        assert len(_recorded_requests(mocked_responses, USER_URL)) == 1
        assert len(_recorded_requests(mocked_responses, HOME_URL)) == 1
        assert len(_recorded_requests(mocked_responses, COMMUNICATION_URL)) == 1


async def test_snapshot_isolates_one_malformed_thermostat() -> None:
    """Test a malformed thermostat retains only its own previous record."""
    first_device = _device("home-1#C001-000")
    second_device = _device("home-1#C002-000")
    communication = {"diffObj": {"days": 0, "hours": 0, "minutes": 0, "seconds": 0}}
    previous_home = WattsVisionSmartHome.from_api(
        _home(),
        {
            "zones": [
                {
                    "zone_label": "Living room",
                    "devices": [first_device, second_device],
                }
            ]
        },
        communication,
    )
    previous = WattsVisionSnapshot(smart_homes=(previous_home,))
    malformed_second = {**second_device, "temperature_air": "invalid"}

    with aioresponses() as mocked_responses:
        _post(mocked_responses, AUTH_URL, payload=AUTH_RESPONSE)
        _post(
            mocked_responses,
            USER_URL,
            payload=_success({"smarthomes": [_home()]}),
        )
        _post(
            mocked_responses,
            HOME_URL,
            payload=_success(
                {
                    "zones": [
                        {
                            "zone_label": "Living room",
                            "devices": [
                                {**first_device, "temperature_air": "700"},
                                malformed_second,
                            ],
                        }
                    ]
                }
            ),
        )
        _post(mocked_responses, COMMUNICATION_URL, payload=_success(communication))
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)
            snapshot = await client.async_get_snapshot(previous)

    assert (
        snapshot.get_device("home-1", "home-1#C001-000").air_temperature
        == REFRESHED_AIR_TEMPERATURE
    )
    assert snapshot.get_device("home-1", "home-1#C002-000") is not None
    assert snapshot.is_device_available("home-1", "home-1#C001-000")
    assert not snapshot.is_device_available("home-1", "home-1#C002-000")
    assert not snapshot.home_status["home-1"].topology_complete
    assert snapshot.home_status["home-1"].malformed_records == 1


async def test_communication_failure_does_not_invalidate_thermostat() -> None:
    """Test communication metadata failure leaves fresh climate data available."""
    communication = {"diffObj": {"days": 0, "hours": 1, "minutes": 2, "seconds": 3}}
    previous_home = WattsVisionSmartHome.from_api(
        _home(),
        {"zones": [{"zone_label": "Living room", "devices": [_device()]}]},
        communication,
    )
    previous = WattsVisionSnapshot(smart_homes=(previous_home,))
    with aioresponses() as mocked_responses:
        _post(mocked_responses, AUTH_URL, payload=AUTH_RESPONSE)
        _post(
            mocked_responses,
            USER_URL,
            payload=_success({"smarthomes": [_home()]}),
        )
        _post(
            mocked_responses,
            HOME_URL,
            payload=_success(
                {"zones": [{"zone_label": "Living room", "devices": [_device()]}]}
            ),
        )
        _post(mocked_responses, COMMUNICATION_URL, exception=TimeoutError())
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)
            snapshot = await client.async_get_snapshot(previous)

    assert snapshot.is_device_available("home-1", "home-1#C001-000")
    assert not snapshot.is_communication_available("home-1")
    assert (
        snapshot.smart_homes[0].last_communication == previous_home.last_communication
    )


@pytest.mark.parametrize("field", ["days", "hours", "minutes", "seconds"])
def test_communication_age_rejects_negative_values(field: str) -> None:
    """Test every negative communication-age component is rejected."""
    values = {"days": 0, "hours": 0, "minutes": 0, "seconds": 0, field: -1}

    with pytest.raises(WattsVisionResponseError):
        WattsVisionCommunicationAge.from_api({"diffObj": values})


def test_snapshot_rejects_duplicate_identifiers() -> None:
    """Test immutable indexes reject ambiguous home and thermostat IDs."""
    device = WattsVisionDevice.from_api(_device())
    communication = WattsVisionCommunicationAge(0, 0, 0, 0)
    home = WattsVisionSmartHome(
        smart_home_id="home-1",
        label="Home",
        mac_address="00:11:22:33:44:55",
        zones=(WattsVisionZone(label="Living", devices=(device, device)),),
        last_communication=communication,
    )
    with pytest.raises(WattsVisionResponseError):
        WattsVisionSnapshot(smart_homes=(home,))

    snapshot_home = WattsVisionSmartHome(
        smart_home_id="home-2",
        label="Other",
        mac_address="00:11:22:33:44:66",
        zones=(),
        last_communication=communication,
    )
    with pytest.raises(WattsVisionResponseError):
        WattsVisionSnapshot(smart_homes=(snapshot_home, snapshot_home))


@pytest.mark.parametrize(
    ("wire_mode", "expected_mode", "expected_target"),
    [
        ("0", WattsVisionDeviceMode.COMFORT, 68.0),
        ("1", WattsVisionDeviceMode.OFF, None),
        ("2", WattsVisionDeviceMode.FROST, 44.6),
        ("3", WattsVisionDeviceMode.ECO, 62.0),
        ("4", WattsVisionDeviceMode.BOOST, 72.0),
        ("5", WattsVisionDeviceMode.MODE_5, None),
        ("6", WattsVisionDeviceMode.MODE_6, None),
        ("8", WattsVisionDeviceMode.PROGRAM_COMFORT, 68.0),
        ("11", WattsVisionDeviceMode.PROGRAM_ECO, 62.0),
        ("13", WattsVisionDeviceMode.PROGRAM_UNSPECIFIED, None),
        ("15", WattsVisionDeviceMode.MANUAL, 68.0),
        ("16", WattsVisionDeviceMode.PROGRAM_BOOST, 72.0),
        ("future-mode", WattsVisionDeviceMode.UNKNOWN, None),
    ],
)
def test_device_model_supports_all_known_and_future_modes(
    wire_mode: str,
    expected_mode: WattsVisionDeviceMode,
    expected_target: float | None,
) -> None:
    """Test every known mode and an unknown future mode remain parseable."""
    # Arrange - Build a device response with the selected wire mode.
    device_data = {**_device(), "gv_mode": wire_mode}

    # Act - Parse the immutable API model.
    device = WattsVisionDevice.from_api(device_data)

    # Assert - Verify semantic mode, raw value, and target selection.
    assert device.mode is expected_mode
    assert device.wire_mode == wire_mode
    assert device.target_temperature == expected_target


@pytest.mark.parametrize(
    ("mode", "temperature", "mode_fields"),
    [
        (
            WattsVisionDeviceMode.COMFORT,
            68.0,
            {"query[consigne_confort]": "680"},
        ),
        (WattsVisionDeviceMode.OFF, 50.0, {}),
        (
            WattsVisionDeviceMode.FROST,
            44.6,
            {
                "query[consigne_hg]": "446",
                "peremption": "20000",
            },
        ),
        (
            WattsVisionDeviceMode.ECO,
            62.0,
            {"query[consigne_eco]": "620"},
        ),
        (
            WattsVisionDeviceMode.BOOST,
            72.0,
            {
                "query[time_boost]": "7200",
                "query[consigne_boost]": "720",
                "query[consigne_manuel]": "720",
            },
        ),
        (WattsVisionDeviceMode.PROGRAM_UNSPECIFIED, 68.0, {}),
    ],
)
async def test_temperature_command_preserves_exact_mode_payload(
    mode: WattsVisionDeviceMode,
    temperature: float,
    mode_fields: dict[str, str],
) -> None:
    """Test each thermostat mode retains its wire payload."""
    # Arrange - Register successful authentication and command responses.
    with aioresponses() as mocked_responses:
        _post(mocked_responses, AUTH_URL, payload=AUTH_RESPONSE)
        _post(mocked_responses, PUSH_URL, payload=SUCCESS_RESPONSE)
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)

            # Act - Send the selected thermostat command.
            await client.async_set_temperature(
                "home-1", "api-device-1", temperature, mode
            )

        # Assert - Verify every base and mode-specific request field.
        expected_payload = {
            "token": "true",
            "context": "1",
            "smarthome_id": "home-1",
            "query[id_device]": "api-device-1",
            "query[time_boost]": "0",
            "query[gv_mode]": mode.value,
            "query[nv_mode]": mode.value,
            "peremption": "15000",
            "lang": "nl_NL",
            **mode_fields,
        }
        assert _request_data(mocked_responses, PUSH_URL) == expected_payload


async def test_temperature_command_rejects_unknown_mode_without_request() -> None:
    """Test an unrecognized future mode is never written back to the API."""
    # Arrange - Create a client with no registered network responses.
    with aioresponses() as mocked_responses:
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)

            # Act - Attempt to send the unknown-mode sentinel.
            with pytest.raises(WattsVisionResponseError):
                await client.async_set_temperature(
                    "home-1",
                    "device-1",
                    68.0,
                    WattsVisionDeviceMode.UNKNOWN,
                )

            # Assert - Verify validation occurred before authentication or I/O.
            assert not mocked_responses.requests


@pytest.mark.parametrize(
    "mode",
    [
        WattsVisionDeviceMode.MODE_5,
        WattsVisionDeviceMode.MODE_6,
        WattsVisionDeviceMode.PROGRAM_COMFORT,
        WattsVisionDeviceMode.PROGRAM_ECO,
        WattsVisionDeviceMode.PROGRAM_BOOST,
        WattsVisionDeviceMode.MANUAL,
        WattsVisionDeviceMode.UNKNOWN,
    ],
)
async def test_temperature_command_rejects_unverified_modes_without_request(
    mode: WattsVisionDeviceMode,
) -> None:
    """Test parsed reporting modes are not treated as command capabilities."""
    with aioresponses() as mocked_responses:
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)

            with pytest.raises(WattsVisionResponseError):
                await client.async_set_temperature(
                    "home-1",
                    "device-1",
                    68.0,
                    mode,
                )

        assert not mocked_responses.requests


def test_optimistic_update_preserves_manual_temperature() -> None:
    """Test a normal target command never changes the Program/manual field."""
    device = WattsVisionDevice.from_api(_device())
    requested_temperature = 68.9

    updated = device.with_command(
        WattsVisionDeviceMode.COMFORT,
        requested_temperature,
        update_target=True,
    )

    assert updated.mode is WattsVisionDeviceMode.COMFORT
    assert updated.wire_mode == "0"
    assert updated.manual_temperature == device.manual_temperature
    assert updated.comfort_temperature == requested_temperature


def test_optimistic_boost_update_matches_official_coupled_fields() -> None:
    """Test Boost optimism follows the two target fields sent on the wire."""
    device = WattsVisionDevice.from_api(_device())
    requested_temperature = 73.4

    updated = device.with_command(
        WattsVisionDeviceMode.BOOST,
        requested_temperature,
        update_target=True,
    )

    assert updated.mode is WattsVisionDeviceMode.BOOST
    assert updated.manual_temperature == requested_temperature
    assert updated.boost_temperature == requested_temperature


@pytest.mark.parametrize("boost_duration", [120, 181, 3_801_600])
async def test_boost_command_rejects_invalid_duration_without_request(
    boost_duration: int,
) -> None:
    """Test Boost duration validation happens before network I/O."""
    with aioresponses() as mocked_responses:
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)
            with pytest.raises(WattsVisionResponseError):
                await client.async_set_temperature(
                    "home-1",
                    "device-1",
                    72.0,
                    WattsVisionDeviceMode.BOOST,
                    boost_duration=boost_duration,
                )
        assert not mocked_responses.requests


async def test_temperature_command_encodes_fahrenheit_tenths_once() -> None:
    """Test a Celsius half-step converted to Fahrenheit is preserved on the wire."""
    with aioresponses() as mocked_responses:
        _post(mocked_responses, AUTH_URL, payload=AUTH_RESPONSE)
        _post(mocked_responses, PUSH_URL, payload=SUCCESS_RESPONSE)
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)
            await client.async_set_temperature(
                "home-1",
                "device-1",
                68.9,
                WattsVisionDeviceMode.COMFORT,
            )

        payload = _request_data(mocked_responses, PUSH_URL)
        assert payload["query[consigne_confort]"] == "689"
        assert "query[consigne_manuel]" not in payload


@pytest.mark.parametrize("temperature", [float("nan"), float("inf")])
async def test_temperature_command_rejects_non_finite_values(
    temperature: float,
) -> None:
    """Test invalid temperatures are rejected before authentication or I/O."""
    with aioresponses() as mocked_responses:
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)
            with pytest.raises(WattsVisionResponseError):
                await client.async_set_temperature(
                    "home-1",
                    "device-1",
                    temperature,
                    WattsVisionDeviceMode.COMFORT,
                )
        assert not mocked_responses.requests


@pytest.mark.parametrize(
    ("api_response", "expected_error"),
    [
        (
            {"status": HTTPStatus.UNAUTHORIZED},
            WattsVisionAuthenticationError,
        ),
        (
            {"status": HTTPStatus.INTERNAL_SERVER_ERROR},
            WattsVisionResponseError,
        ),
        ({"exception": TimeoutError()}, WattsVisionConnectionError),
        ({"exception": ClientConnectionError()}, WattsVisionConnectionError),
        ({"body": "not-json"}, WattsVisionResponseError),
        (
            {"payload": {"code": {"key": "REJECTED"}, "data": {}}},
            WattsVisionResponseError,
        ),
    ],
    ids=("authentication", "http", "timeout", "network", "malformed-json", "rejected"),
)
async def test_temperature_command_raises_response_error(
    api_response: dict[str, object],
    expected_error: type[Exception],
) -> None:
    """Test unsuccessful command responses raise a typed response error."""
    # Arrange - Register an unsuccessful command response.
    with aioresponses() as mocked_responses:
        _post(mocked_responses, AUTH_URL, payload=AUTH_RESPONSE, repeat=True)
        _post(mocked_responses, PUSH_URL, repeat=True, **api_response)
        async with ClientSession() as session:
            client = WattsVisionClient("user@example.com", "secret", session=session)

            # Act - Send a command to the failing endpoint.
            with pytest.raises(expected_error):
                await client.async_set_temperature(
                    "home-1", "device-1", 68.0, WattsVisionDeviceMode.COMFORT
                )

        # Assert - Verify the command was attempted once.
        expected_requests = (
            EXPECTED_COMMAND_COUNT
            if api_response.get("status") == HTTPStatus.UNAUTHORIZED
            else 1
        )
        assert len(_recorded_requests(mocked_responses, PUSH_URL)) == expected_requests
