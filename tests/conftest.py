"""Fixtures for the Watts Vision integration tests."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

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


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom integrations in every test."""


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
        minor_version=2,
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mock_watts_api() -> Generator[MagicMock]:
    """Return a mocked Watts Vision API client."""
    with patch(
        "custom_components.watts_vision.WattsApi",
        autospec=True,
    ) as api_class:
        client: MagicMock = api_class.return_value
        client.load_data.return_value = True
        client.get_smart_homes.side_effect = lambda: deepcopy(SMART_HOMES)
        client.get_last_communication.return_value = deepcopy(LAST_COMMUNICATION)
        client.push_temperature.return_value = True
        yield client


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_watts_api: MagicMock,
) -> MockConfigEntry:
    """Set up the Watts Vision integration."""
    _ = mock_watts_api
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
