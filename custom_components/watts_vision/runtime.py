"""Runtime data for a Watts Vision config entry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .coordinator import WattsVisionDataUpdateCoordinator


@dataclass(slots=True)
class WattsVisionRuntimeData:
    """Keep polling state and Home Assistant registry identity separate."""

    coordinator: WattsVisionDataUpdateCoordinator
    parent_device_ids: dict[str, str]
    boost_durations: dict[tuple[str, str], int]
