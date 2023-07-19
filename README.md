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

Add https://github.com/pwesters/watts_vision to the custom repositories in HACS. A new repository will be found. Click Download and restart Home Assistant. Go to Settings and then to Devices & Services. Click + Add Integration and search for Watts Vision.

## Manual Installation

Copy the watts_vision folder from custom_components to your custom_components folder of your home assistant instance, go to devices & services and click on '+ add integration'. In the new window search for Watts Vision and click on it. Fill out the form with your credentials for the watts vision smart home system.

### Devcontainer
*(Bit tricky)*

A devcontainer is included for development purposes. This is a containerized development environment that can be used with VSCode. See [here](https://code.visualstudio.com/docs/remote/containers) for more information. Running on [Docker](https://www.docker.com/)? 

1. Install the container extension for VSCode [here](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)
2. Install container runtime [here](https://docs.docker.com/get-docker/)
3. Open folder in container through VSCode `> Dev Container: Open Folder in Container`
4. Within this containerized environment run `> Tasks: Run Task` and select `> Run Home Assistant on port 9123` again through VSCode
5. HA should be made available on port 9123 (http://127.0.0.1:9123/)
