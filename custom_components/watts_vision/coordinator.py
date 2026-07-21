"""Data update coordinator for Watts Vision."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, override

from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    WattsVisionAuthenticationError,
    WattsVisionClient,
    WattsVisionDevice,
    WattsVisionDeviceMode,
    WattsVisionError,
    WattsVisionSnapshot,
)
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, LOGGER

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import WattsVisionConfigEntry


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
        self._known_device_identifiers: set[str] = set()
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
        """Fetch a complete account snapshot."""
        try:
            snapshot = await self._client.async_get_snapshot()
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
        self._async_sync_device_registry(snapshot)
        return snapshot

    def _async_sync_device_registry(self, snapshot: WattsVisionSnapshot) -> None:
        """Create new hub devices and remove devices absent from a full snapshot."""
        device_registry = dr.async_get(self.hass)
        current_identifiers: set[str] = set()
        current_home_ids: set[str] = set()

        for smart_home in snapshot.smart_homes:
            smart_home_id = smart_home.smart_home_id
            current_home_ids.add(smart_home_id)
            current_identifiers.add(smart_home_id)
            parent_device = device_registry.async_get_or_create(
                config_entry_id=self.config_entry.entry_id,
                identifiers={(DOMAIN, smart_home_id)},
                connections={
                    (
                        dr.CONNECTION_NETWORK_MAC,
                        dr.format_mac(smart_home.mac_address),
                    )
                },
                manufacturer="Watts",
                name=f"Central Unit {smart_home.label}",
                model="BT-CT02-RF",
            )
            self._parent_device_ids[smart_home_id] = parent_device.id
            current_identifiers.update(
                device.device_id for zone in smart_home.zones for device in zone.devices
            )

        if self._known_device_identifiers:
            stale_identifiers = self._known_device_identifiers - current_identifiers
            if stale_identifiers:
                entity_registry = er.async_get(self.hass)
                for device_entry in dr.async_entries_for_config_entry(
                    device_registry,
                    self.config_entry.entry_id,
                ):
                    if any(
                        domain == DOMAIN and identifier in stale_identifiers
                        for domain, identifier in device_entry.identifiers
                    ):
                        for entity_entry in er.async_entries_for_device(
                            entity_registry,
                            device_entry.id,
                            include_disabled_entities=True,
                        ):
                            if (
                                entity_entry.config_entry_id
                                == self.config_entry.entry_id
                            ):
                                entity_registry.async_update_entity(
                                    entity_entry.entity_id,
                                    device_id=None,
                                )
                        device_registry.async_update_device(
                            device_entry.id,
                            remove_config_entry_id=self.config_entry.entry_id,
                        )

        for smart_home_id in set(self._parent_device_ids) - current_home_ids:
            self._parent_device_ids.pop(smart_home_id)
        self._known_device_identifiers = current_identifiers

    async def async_set_device_temperature(
        self,
        smart_home_id: str,
        api_device_id: str,
        temperature: float,
        mode: WattsVisionDeviceMode,
        updated_device: WattsVisionDevice,
    ) -> None:
        """Send a command and atomically publish its optimistic device state."""
        await self._client.async_set_temperature(
            smart_home_id,
            api_device_id,
            temperature,
            mode,
        )
        self.async_set_updated_data(
            self.data.replace_device(smart_home_id, updated_device),
        )
