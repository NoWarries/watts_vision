"""Test architectural boundaries in Watts Vision source files."""

from __future__ import annotations

from pathlib import Path


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


def test_battery_sensor_uses_percentage_unit_enum() -> None:
    """Test the battery unit cannot regress to the deprecated constant."""
    # Arrange - Read the battery sensor platform source.
    sensor_path = (
        Path(__file__).parents[1] / "custom_components" / "watts_vision" / "sensor.py"
    )
    sensor_source = sensor_path.read_text(encoding="utf-8")

    # Act - Locate the supported percentage-unit enum assignment.
    uses_percentage_enum = (
        "_attr_native_unit_of_measurement = UnitOfRatio.PERCENTAGE" in sensor_source
    )

    # Assert - Verify the 2026.7-compatible enum remains in use.
    assert uses_percentage_enum
