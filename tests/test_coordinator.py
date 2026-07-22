"""Test Watts Vision command reconciliation."""

# ruff: noqa: PLR2004

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from custom_components.watts_vision.api import (
    WattsVisionCommunicationAge,
    WattsVisionCommunicationStaleError,
    WattsVisionConnectionError,
    WattsVisionDeviceMode,
    WattsVisionError,
    WattsVisionHomeStatus,
    WattsVisionSnapshot,
)

from .conftest import SMART_HOMES, snapshot_from_data

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from homeassistant.core import HomeAssistant
    from pytest_homeassistant_custom_component.common import MockConfigEntry


def _snapshot_with_target(target: str) -> WattsVisionSnapshot:
    """Return a Comfort snapshot with matching target and manual fields."""
    device = {
        **SMART_HOMES[0]["zones"][0]["devices"][0],
        "consigne_confort": target,
        "consigne_manuel": target,
    }
    homes = [
        {
            **SMART_HOMES[0],
            "zones": [
                {
                    **SMART_HOMES[0]["zones"][0],
                    "devices": [device],
                }
            ],
        }
    ]
    return snapshot_from_data(homes)


async def test_stale_polls_are_overlaid_until_command_confirmation(
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test several stale snapshots cannot replace an accepted command."""
    coordinator = setup_integration.runtime_data.coordinator
    await coordinator.async_set_device_temperature(
        "home-1",
        "home-1#C001-000",
        68.9,
        WattsVisionDeviceMode.COMFORT,
        update_target=True,
    )

    mock_watts_client.async_get_snapshot.return_value = snapshot_from_data()
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    pending_device = coordinator.data.get_device("home-1", "home-1#C001-000")
    assert pending_device is not None
    assert pending_device.comfort_temperature == 68.9
    assert coordinator._pending_commands  # noqa: SLF001

    mock_watts_client.async_get_snapshot.return_value = _snapshot_with_target("689")
    await coordinator.async_refresh()
    confirmed = coordinator.data.get_device("home-1", "home-1#C001-000")
    assert confirmed is not None
    assert confirmed.comfort_temperature == 68.9
    assert not coordinator._pending_commands  # noqa: SLF001
    assert (
        next(
            iter(coordinator._last_command_results.values())  # noqa: SLF001
        ).result
        == "confirmed"
    )


async def test_confirmation_window_covers_observed_twelve_minute_delivery(
    setup_integration: MockConfigEntry,
) -> None:
    """Test accepted commands remain pending beyond the live delivery delay."""
    coordinator = setup_integration.runtime_data.coordinator
    key = ("home-1", "home-1#C001-000")

    await coordinator.async_set_device_temperature(
        *key,
        68.9,
        WattsVisionDeviceMode.COMFORT,
        update_target=True,
    )

    pending = coordinator._pending_commands[key]  # noqa: SLF001
    assert pending.deadline - pending.accepted_at == 15 * 60
    assert pending.deadline - pending.accepted_at > 12 * 60


async def test_degraded_snapshot_cannot_confirm_or_expire_command(
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test retained thermostat data cannot decide a pending command."""
    coordinator = setup_integration.runtime_data.coordinator
    await coordinator.async_set_device_temperature(
        "home-1",
        "home-1#C001-000",
        68.9,
        WattsVisionDeviceMode.COMFORT,
        update_target=True,
    )
    degraded = replace(
        snapshot_from_data(),
        home_status={
            "home-1": WattsVisionHomeStatus(
                topology_fresh=False,
                topology_complete=False,
                communication_fresh=True,
                issues=("topology_unavailable",),
            )
        },
        fresh_devices=frozenset(),
    )
    mock_watts_client.async_get_snapshot.return_value = degraded
    await coordinator.async_refresh()

    device = coordinator.data.get_device("home-1", "home-1#C001-000")
    assert device is not None
    assert device.comfort_temperature == 68.9
    assert coordinator._pending_commands  # noqa: SLF001


async def test_complete_device_absence_clears_pending_command(
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test a complete snapshot proving absence clears optimistic state."""
    coordinator = setup_integration.runtime_data.coordinator
    await coordinator.async_set_device_temperature(
        "home-1",
        "home-1#C001-000",
        68.9,
        WattsVisionDeviceMode.COMFORT,
        update_target=True,
    )
    empty_home = [
        {
            **SMART_HOMES[0],
            "zones": [{**SMART_HOMES[0]["zones"][0], "devices": []}],
        }
    ]
    mock_watts_client.async_get_snapshot.return_value = snapshot_from_data(empty_home)
    await coordinator.async_refresh()

    assert coordinator.data.get_device("home-1", "home-1#C001-000") is None
    assert not coordinator._pending_commands  # noqa: SLF001


async def test_poll_already_in_flight_keeps_accepted_optimistic_state(
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test a stale poll started before a command cannot overwrite it."""
    coordinator = setup_integration.runtime_data.coordinator
    poll_started = asyncio.Event()
    release_poll = asyncio.Event()

    async def delayed_stale_snapshot(
        _previous: WattsVisionSnapshot | None,
    ) -> WattsVisionSnapshot:
        poll_started.set()
        await release_poll.wait()
        return snapshot_from_data()

    mock_watts_client.async_get_snapshot.side_effect = delayed_stale_snapshot
    refresh_task = asyncio.create_task(coordinator.async_refresh())
    await poll_started.wait()
    await coordinator.async_set_device_temperature(
        "home-1",
        "home-1#C001-000",
        68.9,
        WattsVisionDeviceMode.COMFORT,
        update_target=True,
    )
    release_poll.set()
    await refresh_task

    device = coordinator.data.get_device("home-1", "home-1#C001-000")
    assert device is not None
    assert device.comfort_temperature == 68.9


async def test_newer_command_supersedes_older_pending_state(
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test the newest accepted command remains visible across old snapshots."""
    coordinator = setup_integration.runtime_data.coordinator
    for temperature in (68.9, 69.8):
        await coordinator.async_set_device_temperature(
            "home-1",
            "home-1#C001-000",
            temperature,
            WattsVisionDeviceMode.COMFORT,
            update_target=True,
        )

    mock_watts_client.async_get_snapshot.return_value = _snapshot_with_target("689")
    await coordinator.async_refresh()
    device = coordinator.data.get_device("home-1", "home-1#C001-000")
    assert device is not None
    assert device.comfort_temperature == 69.8

    mock_watts_client.async_get_snapshot.return_value = _snapshot_with_target("698")
    await coordinator.async_refresh()
    assert not coordinator._pending_commands  # noqa: SLF001


async def test_external_change_wins_during_reconciliation(
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test a value outside the command transition set is not hidden."""
    coordinator = setup_integration.runtime_data.coordinator
    await coordinator.async_set_device_temperature(
        "home-1",
        "home-1#C001-000",
        68.9,
        WattsVisionDeviceMode.COMFORT,
        update_target=True,
    )
    mock_watts_client.async_get_snapshot.return_value = _snapshot_with_target("700")
    await coordinator.async_refresh()

    device = coordinator.data.get_device("home-1", "home-1#C001-000")
    assert device is not None
    assert device.comfort_temperature == 70
    assert not coordinator._pending_commands  # noqa: SLF001
    assert (
        next(
            iter(coordinator._last_command_results.values())  # noqa: SLF001
        ).result
        == "external_override"
    )


async def test_unconfirmed_command_times_out_and_rolls_back(
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test an accepted command that never appears returns to cloud state."""
    coordinator = setup_integration.runtime_data.coordinator
    key = ("home-1", "home-1#C001-000")
    await coordinator.async_set_device_temperature(
        *key,
        68.9,
        WattsVisionDeviceMode.COMFORT,
        update_target=True,
    )
    coordinator._pending_commands[key] = replace(  # noqa: SLF001
        coordinator._pending_commands[key],  # noqa: SLF001
        deadline=0,
    )
    mock_watts_client.async_get_snapshot.return_value = snapshot_from_data()
    await coordinator.async_refresh()

    device = coordinator.data.get_device(*key)
    assert device is not None
    assert device.comfort_temperature == 68
    assert "did not confirm" in caplog.text


async def test_failed_command_leaves_state_unchanged(
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test a rejected transport operation never publishes optimistic state."""
    coordinator = setup_integration.runtime_data.coordinator
    original = coordinator.data
    mock_watts_client.async_set_temperature.side_effect = WattsVisionConnectionError(
        "offline"
    )

    with pytest.raises(WattsVisionConnectionError):
        await coordinator.async_set_device_temperature(
            "home-1",
            "home-1#C001-000",
            68.9,
            WattsVisionDeviceMode.COMFORT,
            update_target=True,
        )

    assert coordinator.data is original
    assert not coordinator._pending_commands  # noqa: SLF001


async def test_stale_central_unit_rejects_command_before_push(
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test live communication older than 60 seconds prevents false optimism."""
    coordinator = setup_integration.runtime_data.coordinator
    original = coordinator.data
    mock_watts_client.async_get_communication_age.return_value = (
        WattsVisionCommunicationAge(0, 0, 1, 1)
    )

    with pytest.raises(WattsVisionCommunicationStaleError) as error:
        await coordinator.async_set_device_temperature(
            "home-1",
            "home-1#C001-000",
            62.0,
            WattsVisionDeviceMode.ECO,
            update_target=False,
        )

    assert error.value.age_seconds == 61
    assert coordinator.data is original
    mock_watts_client.async_set_temperature.assert_not_awaited()


async def test_command_preflight_allows_exact_threshold_and_check_failure(
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test the production client's exact boundary and fail-open behavior."""
    coordinator = setup_integration.runtime_data.coordinator
    mock_watts_client.async_get_communication_age.return_value = (
        WattsVisionCommunicationAge(0, 0, 1, 0)
    )
    await coordinator.async_set_device_temperature(
        "home-1",
        "home-1#C001-000",
        62.0,
        WattsVisionDeviceMode.ECO,
        update_target=False,
    )
    mock_watts_client.async_get_communication_age.side_effect = WattsVisionError(
        "communication check unavailable"
    )
    await coordinator.async_set_device_temperature(
        "home-1",
        "home-1#C001-000",
        68.0,
        WattsVisionDeviceMode.COMFORT,
        update_target=False,
    )

    assert mock_watts_client.async_set_temperature.await_count == 2


async def test_command_for_missing_thermostat_fails_before_api_call(
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test a stale entity cannot command a thermostat absent from effective data."""
    coordinator = setup_integration.runtime_data.coordinator
    with pytest.raises(WattsVisionError, match="disappeared"):
        await coordinator.async_set_device_temperature(
            "home-1",
            "missing-device",
            68.9,
            WattsVisionDeviceMode.COMFORT,
            update_target=True,
        )
    mock_watts_client.async_set_temperature.assert_not_awaited()


async def test_complete_home_absence_requires_three_snapshots(
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test parent-home cleanup uses the same complete-absence threshold."""
    coordinator = setup_integration.runtime_data.coordinator
    mock_watts_client.async_get_snapshot.return_value = WattsVisionSnapshot(
        smart_homes=()
    )
    for _ in range(3):
        await coordinator.async_refresh()
    assert "home-1" not in coordinator._parent_device_ids  # noqa: SLF001
    assert "home-1" not in coordinator._known_devices_by_home  # noqa: SLF001


async def test_unknown_mode_warning_is_emitted_once(
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test future wire modes remain reportable without log spam."""
    coordinator = setup_integration.runtime_data.coordinator
    homes = [
        {
            **SMART_HOMES[0],
            "zones": [
                {
                    **SMART_HOMES[0]["zones"][0],
                    "devices": [
                        {
                            **SMART_HOMES[0]["zones"][0]["devices"][0],
                            "gv_mode": "future-mode",
                        }
                    ],
                }
            ],
        }
    ]
    mock_watts_client.async_get_snapshot.return_value = snapshot_from_data(homes)
    await coordinator.async_refresh()
    await coordinator.async_refresh()

    warnings = [
        record
        for record in caplog.records
        if "unknown thermostat mode" in record.getMessage()
    ]
    assert len(warnings) == 1


async def test_commands_to_separate_thermostats_run_concurrently(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_watts_client: MagicMock,
) -> None:
    """Test per-device locks do not serialize independent thermostats."""
    coordinator = setup_integration.runtime_data.coordinator
    second_device = {
        **SMART_HOMES[0]["zones"][0]["devices"][0],
        "id": "home-1#C002-000",
        "id_device": "api-device-2",
    }
    expanded = [
        {
            **SMART_HOMES[0],
            "zones": [
                {
                    **SMART_HOMES[0]["zones"][0],
                    "devices": [
                        SMART_HOMES[0]["zones"][0]["devices"][0],
                        second_device,
                    ],
                }
            ],
        }
    ]
    mock_watts_client.async_get_snapshot.return_value = snapshot_from_data(expanded)
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    both_started = asyncio.Event()
    release = asyncio.Event()
    active = 0

    async def delayed_command(*_args: object) -> None:
        nonlocal active
        active += 1
        if active == 2:
            both_started.set()
        await release.wait()
        active -= 1

    mock_watts_client.async_set_temperature.side_effect = delayed_command
    commands = [
        asyncio.create_task(
            coordinator.async_set_device_temperature(
                "home-1",
                device_id,
                68.9,
                WattsVisionDeviceMode.COMFORT,
                update_target=True,
            )
        )
        for device_id in ("home-1#C001-000", "home-1#C002-000")
    ]
    await asyncio.wait_for(both_started.wait(), timeout=1)
    release.set()
    await asyncio.gather(*commands)

    assert len(coordinator._pending_commands) == 2  # noqa: SLF001
