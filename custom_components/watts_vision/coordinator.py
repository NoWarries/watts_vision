"""Data update coordinator for Watts Vision."""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, override

from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    WattsVisionAuthenticationError,
    WattsVisionClient,
    WattsVisionCommunicationStaleError,
    WattsVisionDevice,
    WattsVisionDeviceMode,
    WattsVisionError,
    WattsVisionSmartHome,
    WattsVisionSnapshot,
)
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, LOGGER

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from homeassistant.core import HomeAssistant

    from . import WattsVisionConfigEntry

_COMMAND_CONFIRMATION_TIMEOUT: Final = 90.0
_INITIAL_COMMAND_REFRESH_DELAY: Final = 2.0
_COMMAND_REFRESH_INTERVAL: Final = 5.0
_MAX_COMMAND_COMMUNICATION_AGE_SECONDS: Final = 60
_REMOVAL_CONFIRMATIONS: Final = 3
_RECONCILED_FIELDS: Final = (
    "mode",
    "wire_mode",
    "comfort_temperature",
    "eco_temperature",
    "frost_temperature",
    "manual_temperature",
    "boost_temperature",
)
_PROGRAM_MODES: Final = frozenset(
    {
        WattsVisionDeviceMode.PROGRAM_COMFORT,
        WattsVisionDeviceMode.PROGRAM_ECO,
        WattsVisionDeviceMode.PROGRAM_UNSPECIFIED,
        WattsVisionDeviceMode.PROGRAM_BOOST,
    }
)


@dataclass(frozen=True, slots=True)
class PendingCommand:
    """Describe an accepted command awaiting cloud confirmation."""

    generation: int
    accepted_at: float
    deadline: float
    baseline: WattsVisionDevice
    optimistic: WattsVisionDevice
    changed_fields: tuple[str, ...]
    transition_values: Mapping[str, tuple[object, ...]]
    requested_mode: WattsVisionDeviceMode
    requested_temperature: float


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Describe the latest command outcome for diagnostics."""

    result: str
    recorded_at: float
    requested_mode: WattsVisionDeviceMode
    requested_temperature: float


class WattsVisionDataUpdateCoordinator(DataUpdateCoordinator[WattsVisionSnapshot]):
    """Coordinate polling for one Watts Vision account."""

    config_entry: WattsVisionConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: WattsVisionConfigEntry,
        client: WattsVisionClient,
        parent_device_ids: dict[str, str],
    ) -> None:
        """Initialize the coordinator."""
        self._client = client
        self._parent_device_ids = parent_device_ids
        self._authoritative_data: WattsVisionSnapshot | None = None
        self._device_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._command_generation: dict[tuple[str, str], int] = {}
        self._pending_commands: dict[tuple[str, str], PendingCommand] = {}
        self._last_command_results: dict[tuple[str, str], CommandResult] = {}
        self._cancel_reconciliation: Callable[[], None] | None = None
        self._known_devices_by_home: dict[str, set[str]] = {}
        self._missing_counts: dict[tuple[str, str], int] = {}
        self._missing_home_counts: dict[str, int] = {}
        self._detached_entity_ids: dict[tuple[str, str], tuple[str, ...]] = {}
        self._warned_unknown_modes: set[str] = set()
        self._last_issue_signature: tuple[object, ...] = ()
        self.last_successful_update: datetime | None = None
        scan_interval = config_entry.options.get(
            CONF_SCAN_INTERVAL,
            config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
            always_update=False,
        )

    @override
    async def _async_update_data(self) -> WattsVisionSnapshot:
        """Fetch, reconcile, and publish an account snapshot."""
        try:
            snapshot = await self._client.async_get_snapshot(self._authoritative_data)
        except WattsVisionAuthenticationError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="authentication_failed",
            ) from err
        except WattsVisionError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
            ) from err

        self._authoritative_data = snapshot
        effective_snapshot = self._reconcile_pending_commands(snapshot)
        self._async_sync_device_registry(snapshot)
        self._log_snapshot_health(snapshot)
        self.last_successful_update = dt_util.utcnow()
        return effective_snapshot

    def _reconcile_pending_commands(
        self,
        snapshot: WattsVisionSnapshot,
    ) -> WattsVisionSnapshot:
        """Overlay pending commands unless fresh data confirms or rejects them."""
        effective = snapshot
        now = time.monotonic()
        for key, pending in tuple(self._pending_commands.items()):
            home_id, device_id = key
            raw_device = snapshot.get_device(home_id, device_id)
            if raw_device is None:
                status = snapshot.home_status.get(home_id)
                if status is not None and status.topology_fresh:
                    self._finish_command(key, pending, "external_override")
                continue
            if not snapshot.is_device_available(home_id, device_id):
                effective = effective.replace_device(home_id, pending.optimistic)
                continue

            if all(
                _field_confirms_command(raw_device, pending, field)
                for field in pending.changed_fields
            ):
                self._finish_command(key, pending, "confirmed")
                continue
            if now >= pending.deadline:
                self._finish_command(key, pending, "timed_out")
                LOGGER.warning(
                    "Watts Vision accepted a thermostat command but did not "
                    "confirm it before the reconciliation deadline"
                )
                continue
            if all(
                any(
                    _values_equal(getattr(raw_device, field), allowed)
                    for allowed in pending.transition_values[field]
                )
                for field in pending.changed_fields
            ):
                effective = effective.replace_device(home_id, pending.optimistic)
                continue
            self._finish_command(key, pending, "external_override")

        return effective

    def _finish_command(
        self,
        key: tuple[str, str],
        pending: PendingCommand,
        result: str,
    ) -> None:
        """Finish a pending command and retain a redacted result summary."""
        self._pending_commands.pop(key, None)
        self._last_command_results[key] = CommandResult(
            result=result,
            recorded_at=time.monotonic(),
            requested_mode=pending.requested_mode,
            requested_temperature=pending.requested_temperature,
        )
        LOGGER.debug("Watts Vision thermostat command reconciliation: %s", result)

    def _async_sync_device_registry(self, snapshot: WattsVisionSnapshot) -> None:
        """Sync registry devices only after repeated complete absence."""
        device_registry = dr.async_get(self.hass)
        current_home_ids = {home.smart_home_id for home in snapshot.smart_homes}

        for smart_home in snapshot.smart_homes:
            home_id = smart_home.smart_home_id
            parent_device = device_registry.async_get_or_create(
                config_entry_id=self.config_entry.entry_id,
                identifiers={(DOMAIN, home_id)},
                connections={
                    (dr.CONNECTION_NETWORK_MAC, dr.format_mac(smart_home.mac_address))
                },
                manufacturer="Watts",
                name=f"Central Unit {smart_home.label}",
                model="BT-CT02-RF",
            )
            self._parent_device_ids[home_id] = parent_device.id
            current_devices = self._restore_present_registry_devices(
                device_registry,
                smart_home,
            )
            status = snapshot.home_status[home_id]
            known_devices = self._known_devices_by_home.setdefault(home_id, set())
            if status.topology_fresh and status.topology_complete:
                for device_id in known_devices - current_devices:
                    key = (home_id, device_id)
                    self._missing_counts[key] = self._missing_counts.get(key, 0) + 1
                    if self._missing_counts[key] >= _REMOVAL_CONFIRMATIONS:
                        self._remove_registry_device(
                            device_registry,
                            device_id,
                            home_id=home_id,
                        )
                        known_devices.discard(device_id)
                        self._missing_counts.pop(key, None)
                for device_id in current_devices:
                    self._missing_counts.pop((home_id, device_id), None)
                known_devices.update(current_devices)
            else:
                for device_id in known_devices:
                    self._missing_counts.pop((home_id, device_id), None)
            self._missing_home_counts.pop(home_id, None)

        for home_id in set(self._known_devices_by_home) - current_home_ids:
            if not snapshot.account_complete:
                self._missing_home_counts.pop(home_id, None)
                continue
            self._missing_home_counts[home_id] = (
                self._missing_home_counts.get(home_id, 0) + 1
            )
            if self._missing_home_counts[home_id] < _REMOVAL_CONFIRMATIONS:
                continue
            for device_id in self._known_devices_by_home.pop(home_id):
                self._remove_registry_device(
                    device_registry,
                    device_id,
                    home_id=home_id,
                )
                self._missing_counts.pop((home_id, device_id), None)
            self._remove_registry_device(device_registry, home_id)
            self._parent_device_ids.pop(home_id, None)
            self._missing_home_counts.pop(home_id, None)

    def _remove_registry_device(
        self,
        device_registry: dr.DeviceRegistry,
        identifier: str,
        *,
        home_id: str | None = None,
    ) -> None:
        """Remove this config entry from one proven-stale registry device."""
        device = next(
            (
                entry
                for entry in dr.async_entries_for_config_entry(
                    device_registry,
                    self.config_entry.entry_id,
                )
                if (DOMAIN, identifier) in entry.identifiers
            ),
            None,
        )
        if device is not None and self.config_entry.entry_id in device.config_entries:
            entity_registry = er.async_get(self.hass)
            detached_entity_ids: list[str] = []
            for entity_entry in er.async_entries_for_device(
                entity_registry,
                device.id,
                include_disabled_entities=True,
            ):
                if entity_entry.config_entry_id == self.config_entry.entry_id:
                    detached_entity_ids.append(entity_entry.entity_id)
                    entity_registry.async_update_entity(
                        entity_entry.entity_id,
                        device_id=None,
                    )
            if home_id is not None and detached_entity_ids:
                self._detached_entity_ids[(home_id, identifier)] = tuple(
                    detached_entity_ids
                )
            device_registry.async_update_device(
                device.id,
                remove_config_entry_id=self.config_entry.entry_id,
            )

    def _restore_registry_device(
        self,
        device_registry: dr.DeviceRegistry,
        home_id: str,
        device_id: str,
        zone_label: str,
    ) -> None:
        """Re-associate preserved entities when a removed thermostat returns."""
        key = (home_id, device_id)
        detached_entity_ids = self._detached_entity_ids.get(key)
        if detached_entity_ids is None:
            return

        device_info: dict[str, object] = {
            "config_entry_id": self.config_entry.entry_id,
            "identifiers": {(DOMAIN, device_id)},
            "manufacturer": "Watts",
            "name": f"Thermostat {zone_label}",
            "suggested_area": zone_label,
        }
        if "via_device_id" in DeviceInfo.__annotations__:
            device_info["via_device_id"] = self._parent_device_ids[home_id]
        else:
            device_info["via_device"] = (DOMAIN, home_id)
        get_or_create: Any = device_registry.async_get_or_create
        restored_device = get_or_create(**device_info)

        entity_registry = er.async_get(self.hass)
        for entity_id in detached_entity_ids:
            if entity_registry.async_get(entity_id) is not None:
                entity_registry.async_update_entity(
                    entity_id,
                    device_id=restored_device.id,
                )
        self._detached_entity_ids.pop(key, None)

    def _restore_present_registry_devices(
        self,
        device_registry: dr.DeviceRegistry,
        smart_home: WattsVisionSmartHome,
    ) -> set[str]:
        """Restore returning devices and return current thermostat identifiers."""
        current_devices: set[str] = set()
        for zone in smart_home.zones:
            for device in zone.devices:
                current_devices.add(device.device_id)
                self._restore_registry_device(
                    device_registry,
                    smart_home.smart_home_id,
                    device.device_id,
                    zone.label,
                )
        return current_devices

    async def async_set_device_temperature(  # noqa: PLR0913
        self,
        smart_home_id: str,
        device_id: str,
        temperature: float,
        mode: WattsVisionDeviceMode,
        *,
        boost_duration: int | None = None,
        update_target: bool,
    ) -> None:
        """Send and optimistically publish a serialized thermostat command."""
        key = (smart_home_id, device_id)
        lock = self._device_locks.setdefault(key, asyncio.Lock())
        async with lock:
            try:
                communication_age = await self._client.async_get_communication_age(
                    smart_home_id
                )
            except WattsVisionAuthenticationError:
                raise
            except WattsVisionError:
                # The production client allows commands when this optional
                # safety check is itself unavailable.
                LOGGER.debug(
                    "Unable to verify Watts Vision communication age before command"
                )
            else:
                age_seconds = int(communication_age.as_timedelta().total_seconds())
                if age_seconds > _MAX_COMMAND_COMMUNICATION_AGE_SECONDS:
                    raise WattsVisionCommunicationStaleError(age_seconds)
            baseline = self.data.get_device(smart_home_id, device_id)
            if baseline is None:
                msg = "Watts Vision thermostat disappeared before command execution"
                raise WattsVisionError(msg)
            optimistic = baseline.with_command(
                mode,
                temperature,
                update_target=update_target,
            )
            try:
                if boost_duration is None:
                    await self._client.async_set_temperature(
                        smart_home_id,
                        baseline.api_device_id,
                        temperature,
                        mode,
                    )
                else:
                    await self._client.async_set_temperature(
                        smart_home_id,
                        baseline.api_device_id,
                        temperature,
                        mode,
                        boost_duration=boost_duration,
                    )
            except WattsVisionError:
                self._last_command_results[key] = CommandResult(
                    result="failed",
                    recorded_at=time.monotonic(),
                    requested_mode=mode,
                    requested_temperature=temperature,
                )
                raise

            old_pending = self._pending_commands.get(key)
            if old_pending is not None:
                self._last_command_results[key] = CommandResult(
                    result="superseded",
                    recorded_at=time.monotonic(),
                    requested_mode=old_pending.requested_mode,
                    requested_temperature=old_pending.requested_temperature,
                )
            changed_fields = tuple(
                field
                for field in _RECONCILED_FIELDS
                if not _values_equal(
                    getattr(baseline, field),
                    getattr(optimistic, field),
                )
            )
            transition_values: dict[str, tuple[object, ...]] = {}
            for field in changed_fields:
                values = [getattr(baseline, field), getattr(optimistic, field)]
                if old_pending is not None:
                    values.extend(old_pending.transition_values.get(field, ()))
                transition_values[field] = tuple(dict.fromkeys(values))

            generation = self._command_generation.get(key, 0) + 1
            self._command_generation[key] = generation
            accepted_at = time.monotonic()
            pending = PendingCommand(
                generation=generation,
                accepted_at=accepted_at,
                deadline=accepted_at + _COMMAND_CONFIRMATION_TIMEOUT,
                baseline=baseline,
                optimistic=optimistic,
                changed_fields=changed_fields,
                transition_values=transition_values,
                requested_mode=mode,
                requested_temperature=temperature,
            )
            self._pending_commands[key] = pending
            self._last_command_results[key] = CommandResult(
                result="accepted_pending",
                recorded_at=accepted_at,
                requested_mode=mode,
                requested_temperature=temperature,
            )
            self.async_set_updated_data(
                self.data.replace_device(smart_home_id, optimistic)
            )
            self._schedule_reconciliation(_INITIAL_COMMAND_REFRESH_DELAY)

    @callback
    def _schedule_reconciliation(self, delay: float) -> None:
        """Schedule a single shared reconciliation refresh."""
        if self._cancel_reconciliation is not None or not self._pending_commands:
            return
        self._cancel_reconciliation = async_call_later(
            self.hass,
            delay,
            self._async_reconciliation_refresh,
        )

    async def _async_reconciliation_refresh(self, _now: datetime) -> None:
        """Run one reconciliation refresh and schedule the next if needed."""
        self._cancel_reconciliation = None
        await self.async_request_refresh()
        now = time.monotonic()
        if any(command.deadline > now for command in self._pending_commands.values()):
            self._schedule_reconciliation(_COMMAND_REFRESH_INTERVAL)

    @callback
    def async_cancel_reconciliation(self) -> None:
        """Cancel command refresh scheduling during config-entry unload."""
        if self._cancel_reconciliation is not None:
            self._cancel_reconciliation()
            self._cancel_reconciliation = None

    def _log_snapshot_health(self, snapshot: WattsVisionSnapshot) -> None:
        """Log new partial-update signatures and unknown modes once."""
        signature: tuple[object, ...] = (
            snapshot.account_complete,
            snapshot.issues,
            tuple(
                sorted(
                    (
                        status.topology_fresh,
                        status.topology_complete,
                        status.communication_fresh,
                        status.malformed_records,
                        status.issues,
                    )
                    for status in snapshot.home_status.values()
                )
            ),
        )
        if signature != self._last_issue_signature:
            has_issues = bool(snapshot.issues) or any(
                status.issues for status in snapshot.home_status.values()
            )
            if has_issues:
                LOGGER.warning(
                    "Watts Vision returned a partial snapshot; trustworthy prior "
                    "data was retained where available"
                )
            elif self._last_issue_signature:
                LOGGER.debug("Watts Vision partial snapshot recovered")
            self._last_issue_signature = signature

        for home in snapshot.smart_homes:
            for zone in home.zones:
                for device in zone.devices:
                    if (
                        device.mode is WattsVisionDeviceMode.UNKNOWN
                        and device.wire_mode not in self._warned_unknown_modes
                    ):
                        self._warned_unknown_modes.add(device.wire_mode)
                        LOGGER.warning(
                            "Watts Vision reported an unknown thermostat mode: %s",
                            device.wire_mode,
                        )

    def diagnostics_data(self) -> dict[str, Any]:
        """Return redacted coordinator diagnostics."""
        now = time.monotonic()
        snapshot = self.data
        return {
            "last_update_success": self.last_update_success,
            "last_successful_update": (
                self.last_successful_update.isoformat()
                if self.last_successful_update is not None
                else None
            ),
            "account_complete": snapshot.account_complete,
            "homes": [
                {
                    "topology_fresh": status.topology_fresh,
                    "topology_complete": status.topology_complete,
                    "communication_fresh": status.communication_fresh,
                    "malformed_records": status.malformed_records,
                    "device_count": sum(len(zone.devices) for zone in home.zones),
                    "issues": status.issues,
                }
                for home in snapshot.smart_homes
                for status in (snapshot.home_status[home.smart_home_id],)
            ],
            "unknown_modes": sorted(self._warned_unknown_modes),
            "pending_commands": [
                {
                    "age_seconds": round(now - command.accepted_at, 1),
                    "mode": command.requested_mode.value,
                    "temperature_fahrenheit": command.requested_temperature,
                    "generation": command.generation,
                }
                for command in self._pending_commands.values()
            ],
            "last_command_results": [
                {
                    "result": result.result,
                    "age_seconds": round(now - result.recorded_at, 1),
                    "mode": result.requested_mode.value,
                }
                for result in self._last_command_results.values()
            ],
            "missing_device_confirmations": sorted(self._missing_counts.values()),
            "missing_home_confirmations": sorted(self._missing_home_counts.values()),
        }


def _values_equal(left: object, right: object) -> bool:
    """Compare wire values while tolerating float representation noise."""
    if isinstance(left, float) and isinstance(right, float):
        return math.isclose(left, right, abs_tol=0.05)
    return left == right


def _field_confirms_command(
    raw_device: WattsVisionDevice,
    pending: PendingCommand,
    field: str,
) -> bool:
    """Accept any resolved Program phase for a generic Program command."""
    actual = getattr(raw_device, field)
    if pending.requested_mode is WattsVisionDeviceMode.PROGRAM_UNSPECIFIED:
        if field == "mode":
            return actual in _PROGRAM_MODES
        if field == "wire_mode":
            return actual in {mode.value for mode in _PROGRAM_MODES}
    return _values_equal(actual, getattr(pending.optimistic, field))
