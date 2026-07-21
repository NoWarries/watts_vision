"""Test architectural boundaries in Watts Vision source files."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any


def test_integration_has_no_synchronous_transport_references() -> None:
    """Test the integration cannot regress to the removed sync transport."""
    # Arrange - Collect every Python source file in the integration.
    source_root = Path(__file__).parents[1] / "custom_components" / "watts_vision"
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in source_root.rglob("*.py")
    )

    # Act - Find forbidden synchronous transport references.
    forbidden_references = {
        reference
        for reference in ("import requests", "async_add_executor_job", "watts_api")
        if reference in source
    }

    # Assert - Verify only the bundled asynchronous API remains.
    assert not forbidden_references


def test_bundled_api_has_no_home_assistant_imports() -> None:
    """Test the bundled API package remains independent of Home Assistant."""
    # Arrange - Collect every bundled API source file.
    api_root = Path(__file__).parents[1] / "custom_components" / "watts_vision" / "api"
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in api_root.rglob("*.py")
    )

    # Act - Detect a Home Assistant import crossing the package boundary.
    has_home_assistant_import = "homeassistant" in source

    # Assert - Verify the API remains reusable outside Home Assistant.
    assert not has_home_assistant_import


def test_integration_uses_forward_compatible_device_registry_api() -> None:
    """Test device topology avoids calls deprecated for Home Assistant 2026.8."""
    # Arrange - Collect every Python source file in the integration.
    source_root = Path(__file__).parents[1] / "custom_components" / "watts_vision"
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in source_root.rglob("*.py")
    )

    # Act - Find direct uses that cannot select the supported API by HA version.
    deprecated_references = {
        reference
        for reference in ("via_device=", ".async_get_device(")
        if reference in source
    }

    # Assert - Verify the compatibility boundary owns all legacy behavior.
    assert not deprecated_references


def test_battery_uses_a_real_binary_sensor_instead_of_percentage() -> None:
    """Test battery state cannot regress to a fabricated percentage."""
    integration_path = (
        Path(__file__).parents[1] / "custom_components" / "watts_vision" / "sensor.py"
    )
    binary_sensor_path = (
        Path(__file__).parents[1]
        / "custom_components"
        / "watts_vision"
        / "binary_sensor.py"
    )
    sensor_source = integration_path.read_text(encoding="utf-8")
    binary_sensor_source = binary_sensor_path.read_text(encoding="utf-8")

    assert "UnitOfRatio.PERCENTAGE" not in sensor_source
    assert "BinarySensorDeviceClass.BATTERY" in binary_sensor_source


def _leaf_paths(
    data: dict[str, Any], prefix: tuple[str, ...] = ()
) -> set[tuple[str, ...]]:
    """Return every leaf path in a nested translation object."""
    paths: set[tuple[str, ...]] = set()
    for key, value in data.items():
        path = (*prefix, key)
        if isinstance(value, dict):
            paths.update(_leaf_paths(value, path))
        else:
            paths.add(path)
    return paths


def test_english_and_dutch_translations_have_matching_structure() -> None:
    """Test both supported languages contain every translation key."""
    translation_root = (
        Path(__file__).parents[1]
        / "custom_components"
        / "watts_vision"
        / "translations"
    )
    english = json.loads((translation_root / "en.json").read_text(encoding="utf-8"))
    dutch = json.loads((translation_root / "nl.json").read_text(encoding="utf-8"))

    assert _leaf_paths(english) == _leaf_paths(dutch)
    assert english["entity"]["binary_sensor"]["battery_low"]["name"] == "Battery"
    assert dutch["entity"]["binary_sensor"]["battery_low"]["name"] == "Batterij"


def test_manifest_and_project_versions_stay_in_sync() -> None:
    """Test release metadata cannot publish conflicting versions."""
    repository_root = Path(__file__).parents[1]
    manifest = json.loads(
        (
            repository_root / "custom_components" / "watts_vision" / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    with (repository_root / "pyproject.toml").open("rb") as project_file:
        project = tomllib.load(project_file)

    assert manifest["version"] == project["project"]["version"]
