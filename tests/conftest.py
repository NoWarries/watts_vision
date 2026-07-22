"""Fixtures for the Watts Vision integration tests."""

from __future__ import annotations

from contextlib import suppress
from copy import deepcopy
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.watts_vision.api import (
    WattsVisionCommunicationAge,
    WattsVisionDeviceMode,
    WattsVisionSmartHome,
    WattsVisionSnapshot,
)
from custom_components.watts_vision.const import DOMAIN

if TYPE_CHECKING:
    from collections.abc import Generator
    from unittest.mock import MagicMock

    from homeassistant.core import HomeAssistant

SMART_HOMES = [
    {
        "smarthome_id": "home-1",
        "label": "Home",
        "mac_address": "00:11:22:33:44:55",
        "zones": [
            {
                "zone_label": "Living room",
                "devices": [
                    {
                        "id": "home-1#C001-000",
                        "id_device": "api-device-1",
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
                ],
            }
        ],
    }
]

LAST_COMMUNICATION = {
    "diffObj": {
        "days": 0,
        "hours": 1,
        "minutes": 2,
        "seconds": 3,
    }
}


def snapshot_from_data(
    smart_homes: list[dict[str, object]] | None = None,
    last_communication: dict[str, object] | None = None,
) -> WattsVisionSnapshot:
    """Build an immutable snapshot from API-shaped test data."""
    homes = deepcopy(smart_homes if smart_homes is not None else SMART_HOMES)
    communication = deepcopy(
        last_communication if last_communication is not None else LAST_COMMUNICATION
    )
    return WattsVisionSnapshot(
        smart_homes=tuple(
            WattsVisionSmartHome.from_api(
                home,
                {"zones": home["zones"]},
                communication,
            )
            for home in homes
        )
    )


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(request: pytest.FixtureRequest) -> None:
    """Enable custom integrations when the Home Assistant plugin is available."""
    # The API-only suite intentionally runs without the Unix-only HA plugin.
    with suppress(pytest.FixtureLookupError):
        request.getfixturevalue("enable_custom_integrations")


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create a Watts Vision config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="user@example.com",
        data={
            CONF_USERNAME: "user@example.com",
            CONF_PASSWORD: "secret",
        },
        options={CONF_SCAN_INTERVAL: 300},
        unique_id="user@example.com",
        version=1,
        minor_version=3,
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mock_watts_client() -> Generator[MagicMock]:
    """Return a mocked asynchronous Watts Vision client."""
    with patch(
        "custom_components.watts_vision.WattsVisionClient",
        autospec=True,
    ) as api_class:
        client: MagicMock = api_class.return_value
        client.async_get_snapshot = AsyncMock(return_value=snapshot_from_data())
        client.async_get_current_program_mode = AsyncMock(
            return_value=WattsVisionDeviceMode.PROGRAM_ECO
        )
        client.async_get_communication_age = AsyncMock(
            return_value=WattsVisionCommunicationAge(0, 0, 0, 0)
        )
        client.async_set_temperature = AsyncMock(return_value=None)
        yield client


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> MockConfigEntry:
    """Set up the Watts Vision integration."""
    _ = mock_watts_client
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
