# Home Assistant mapping

This page explains the choices that are not obvious from the Home Assistant
interface. Wire details live in [the API notes](api.md).

## Climate entity

| Home Assistant | Watts state or command | Notes |
| --- | --- | --- |
| Current temperature | `temperature_air` | Converted from tenths of a degree Fahrenheit. |
| Target temperature | Target selected from the current mode | Writable in Comfort, Eco, and Boost. |
| Heat or Cool | Comfort mode `0` | The season comes from `heat_cool`; selecting it does not change the season. |
| Auto | Program request `13` | Watts chooses the active weekly-program phase. |
| Off | Mode `1` | Disables the room until another mode is selected. |
| `comfort` | Mode `0` | Uses and can update the stored Comfort target. |
| `eco` | Mode `3` | Uses and can update the stored Eco target. |
| `frost_protection` | Mode `2` | Uses the tested 7 °C frost target. |
| `boost` | Mode `4` | Sends a duration and coupled Boost/Manual targets. |

Program phases reported as `8`, `11`, or `16` appear as Auto. Their target is
read-only because the weekly schedule owns the phase.

The preset keys use Home Assistant's built-in values where available. Home
Assistant translates their labels; `frost_protection` has integration-provided
English and Dutch labels.

Raw modes `5` and `6` have conflicting meanings in the official frontend and
are reported as Unknown. Manual mode `15` is also read-only.

## Target selection

The API has no single effective-target field. The integration uses the target
that belongs to the reported mode:

| Mode | Target |
| --- | --- |
| Comfort `0`, Program Comfort `8` | `consigne_confort` |
| Eco `3`, Program Eco `11` | `consigne_eco` |
| Frost `2` | `consigne_hg` |
| Boost `4`, Program Boost `16` | `consigne_boost` |
| Manual `15` | `consigne_manuel` |
| Off, generic Program, or unknown | None |

Writable temperatures are rounded to Home Assistant's 0.5 °C step and clamped
to the limits reported by the room.

## Boost

Selecting Boost uses the room's **Next Boost duration** setting. The start
target is at least one 0.5 °C step beyond the measured room temperature in the
active heating or cooling direction, unless the reported room limit prevents
that. This avoids a heating Boost below room temperature and reverses the rule
correctly in cooling season.

Changing the climate target while Boost is active sends a new Boost command and
starts the configured duration again. Changing **Next Boost duration** alone
does not alter a running Boost.

Natural expiry returned to the pre-Boost mode in live tests from Comfort, Eco,
and Program. Home Assistant does not send a fallback command when the timer
ends.

## On and off

`turn_off` selects Watts Off mode. `turn_on` restores the last stable Comfort,
Eco, Frost protection, or Program mode observed by that climate entity. If
Home Assistant first discovers the room while it is already Off, `turn_on`
falls back to Comfort because the earlier mode is unavailable.

## Command confirmation

Watts commands are asynchronous:

1. The API acknowledges the request.
2. Home Assistant shows a provisional state.
3. The integration refreshes after two seconds, then every five seconds.
4. A later room read confirms or replaces the provisional state.

Confirmation stops after 90 seconds. Fresh Watts state always wins if it
differs from the requested state.

## Availability

- A failed full refresh makes coordinator entities unavailable.
- A bad room record does not prevent other rooms from updating.
- A previously known bad room may be retained internally, but is not presented
  as fresh state.
- A room command is blocked when the reported communication age exceeds
  60 seconds.
- Unknown modes remain readable but cannot be sent back to Watts.
- Missing devices are removed only after three complete snapshots confirm
  their absence.

## Entities

| Entity | Default | Purpose |
| --- | --- | --- |
| Climate | Enabled | Primary room control and current HVAC state. |
| Air temperature sensor | Enabled | Recorder- and automation-friendly room temperature. |
| Low battery binary sensor | Enabled | Diagnostic flag from `error_code == "1"`. |
| Last communication sensor | Enabled | Diagnostic timestamp derived from `diffObj`. |
| Next Boost duration number | Enabled | Local duration used by the next Boost request. |
| Heating binary sensor | Disabled | Duplicate of the reported climate action. |
| Target temperature sensor | Disabled | Compatibility view of the active target. |
| Preset and temperature-mode sensors | Disabled | Raw compatibility views for troubleshooting. |

The activity fields have not been matched to a physical relay or boiler. Treat
them as reported demand, not proof that equipment is running.


