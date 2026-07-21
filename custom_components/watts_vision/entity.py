"""Base entities for Watts Vision."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast, override

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import WattsVisionDataUpdateCoordinator

if TYPE_CHECKING:
    from .api import WattsVisionDevice


@dataclass(frozen=True, slots=True)
class WattsVisionEntityContext:
    """Identify a thermostat and its Home Assistant device topology."""

    smart_home_id: str
    device_id: str
    zone: str
    parent_device_id: str


def _thermostat_device_info(context: WattsVisionEntityContext) -> DeviceInfo:
    """Build device topology compatible with Home Assistant 2026.7 and 2026.8."""
    device_info: dict[str, object] = {
        "identifiers": {(DOMAIN, context.device_id)},
        "manufacturer": "Watts",
        "name": f"Thermostat {context.zone}",
        "model": "BT-D03-RF",
        "suggested_area": context.zone,
    }
    # Home Assistant 2026.8 replaces identifier-based parents with registry IDs.
    if "via_device_id" in DeviceInfo.__annotations__:
        device_info["via_device_id"] = context.parent_device_id
    else:
        device_info["via_device"] = (DOMAIN, context.smart_home_id)
    return cast("DeviceInfo", device_info)


class WattsVisionEntity(CoordinatorEntity[WattsVisionDataUpdateCoordinator]):
    """Base entity for a Watts Vision thermostat."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WattsVisionDataUpdateCoordinator,
        context: WattsVisionEntityContext,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._smart_home_id = context.smart_home_id
        self._device_id = context.device_id
        self._attr_device_info = _thermostat_device_info(context)

    @property
    @override
    def available(self) -> bool:
        """Return whether the coordinator and device are available."""
        return super().available and self._device() is not None

    def _device(self) -> WattsVisionDevice | None:
        """Return the device from the latest coordinator snapshot."""
        return self.coordinator.data.get_device(
            self._smart_home_id,
            self._device_id,
        )
