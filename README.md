![GitHub release](https://img.shields.io/github/release/nowarries/watts_vision.svg)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

# Watts Vision for Home Assistant

Control Watts Vision room thermostats from Home Assistant. The integration uses
the same cloud service and account as the official Watts application.

Version 1.0.0 is tested with Home Assistant 2026.7.2.

## Install

### HACS

1. Add `https://github.com/nowarries/watts_vision` to HACS as a custom
   integration repository.
2. Download Watts Vision and restart Home Assistant.
3. Open **Settings → Devices & services → Add integration** and select
   **Watts Vision**.

### Manual

Copy `custom_components/watts_vision` to your Home Assistant
`custom_components` directory. Restart Home Assistant, then add Watts Vision
from **Settings → Devices & services**.

## Set up

Sign in with your Watts account. Home Assistant will find every central unit
and room thermostat linked to it.

The integration updates every five minutes by default. You can change the
interval from its options.

## What it supports

Each room gets a climate entity with:

- Heat or Cool, following the season reported by Watts;
- Auto, which resumes the existing weekly program;
- Off;
- Comfort, Eco, Frost protection, and Boost presets;
- temperature control in Comfort, Eco, and Boost.

You also get low-battery status, air temperature, the central unit's last
communication time, and a **Next Boost duration** setting. Less useful
compatibility sensors are disabled by default.

Commands are not instant. Home Assistant shows the requested state, then checks
the Watts API until the thermostat reports the change.

## For maintainers

- [Home Assistant mapping](docs/home-assistant.md)
- [Watts API notes](docs/api.md)

Development checks:

```text
uv sync --group test
uv run pytest
uv run ruff check .
uv run mypy custom_components/watts_vision
```

## Credits

Based on the original
[pwesters/watts_vision](https://github.com/pwesters/watts_vision) integration.
