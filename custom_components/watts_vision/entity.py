"""Base entities for Watts Vision."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WattsVisionDataUpdateCoordinator

if TYPE_CHECKING:
    from .api import WattsVisionDevice


class WattsVisionEntity(CoordinatorEntity[WattsVisionDataUpdateCoordinator]):
    """Base entity for a Watts Vision thermostat."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WattsVisionDataUpdateCoordinator,
        smart_home_id: str,
        device_id: str,
        zone: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._smart_home_id = smart_home_id
        self._device_id = device_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_id)},
            manufacturer="Watts",
            name=f"Thermostat {zone}",
            model="BT-D03-RF",
            via_device=(DOMAIN, smart_home_id),
            suggested_area=zone,
        )

    @property
    def available(self) -> bool:
        """Return whether the coordinator and device are available."""
        return super().available and self._device() is not None

    def _device(self) -> WattsVisionDevice | None:
        """Return the device from the latest coordinator snapshot."""
        return self.coordinator.data.get_device(
            self._smart_home_id,
            self._device_id,
        )
