![GitHub release](https://img.shields.io/github/release/nowarries/watts_vision.svg) [![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

# Watts (RE)Vision for Home Assistant
A relatively more maintained version of the [Watts Vision integration](https://github.com/pwesters/watts_vision) for Home Assistant. This version forkend and based on the original version by 
[pwesters](https://github.com/pwesters/). And does souly exist because the original version is no longer maintained. 

This version is not a complete rewrite, but rather a refactored version of the original version. 

This version includes the following:
-   [x] Refactored token handling
-   [x] Assocation of CU's to devices (and entities)
-   [x] Proper labeling (friendly names) of entities, devices and (hubs/accounts)
-   [x] Support for multiple Watts Vision accounts
-   [x] API (un/re)loading
-   [x] Account editing (reauthentication)
-   [x] Battery tracking
    - Will display 0% when battery is empty otherwise will display 100% when battery is full (technical limitation)
### Author
- [pwesters](https://github.com/pwesters/watts_visio)

### Maintainers (of this standalone version)
- [nowarries](https://github.com/nowarries/) 
- [mirakels](https://github.com/mirakels/)

# Installation

## Requirements
A Watts Vision system Cental unit is required to be able to see the settings remotely. See [Watts Vision Smart Home](https://wattswater.eu/catalog/regulation-and-control/watts-vision-smart-home/) and watch the [guide on youtube (Dutch)](https://www.youtube.com/watch?v=BLNqxkH7Td8).

> You will be logging in with your account this is a cloud polling api intergration

## HACS

Add https://github.com/nowarries/watts_vision to the custom repositories in HACS. A new repository will be found. Click Download and restart Home Assistant. Go to Settings and then to Devices & Services. Click + Add Integration and search for Watts Vision.

## Manual Installation

Copy the watts_vision folder from custom_components to your custom_components folder of your home assistant instance, go to devices & services and click on '+ add integration'. In the new window search for Watts Vision and click on it. Fill out the form with your credentials for the watts vision smart home system.

## Development

Development uses [uv](https://docs.astral.sh/uv/) for Python tooling
environment and Docker Compose for Home Assistant. Install uv and Docker.