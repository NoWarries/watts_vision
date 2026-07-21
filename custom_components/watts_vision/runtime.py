"""Runtime data for a Watts Vision config entry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .coordinator import WattsVisionDataUpdateCoordinator


@dataclass(frozen=True, slots=True)
class WattsVisionRuntimeData:
    """Keep polling state and Home Assistant registry identity separate."""

    coordinator: WattsVisionDataUpdateCoordinator
    parent_device_ids: Mapping[str, str]
