# Watts Vision API notes

> Unofficial notes from live traffic and controlled testing. This API can
> change without notice.

These notes are for integration maintainers. They describe what we have seen,
not what the field names appear to mean.

Evidence labels:

- **Confirmed:** repeated or checked through another source.
- **Observed:** seen once.
- **Inferred:** plausible, but not proved.
- **Unknown:** unresolved or contradictory.

## Basics

| Item | Value |
| --- | --- |
| API base | `https://smarthome.wattselectronics.com/api/v0.1/human` |
| Token endpoint | `https://auth.smarthome.wattselectronics.com/realms/watts/protocol/openid-connect/token` |
| Requests | HTTPS `POST`, form URL encoded |
| Responses | JSON |
| Authentication | Bearer token from Keycloak |
| Client ID | `app-front` |

The integration sends `token=true` and `lang=nl_NL` on Human API requests. The
official frontend uses a different value for `token`, so its meaning and
requiredness are **Unknown**.

Successful reads use a `code`/`data` envelope:

```json
{
  "code": {"key": "OK"},
  "data": {}
}
```

The official frontend expects `OK_SET` after a write. Retained integration
fixtures use `OK`; the exact live write key was not captured. The client accepts
both. In either case, the response only acknowledges the request. Confirm a
write with a later room read.

## Endpoints

| Operation | Path | Scope | Status |
| --- | --- | --- | --- |
| Authenticate | Keycloak token endpoint | Account | Confirmed |
| List installations | `/user/read/` | Account | Confirmed |
| Read installation | `/smarthome/read/` | Installation | Confirmed |
| Communication age | `/sandbox/check_last_connexion/` | Installation | Confirmed operation; meaning inferred |
| Send room command | `/query/push/` | Room | Confirmed |
| Render Program timeline | `/sandbox/convert_program/` | Room | Observed; unreliable |

### Authentication

Password grant:

```text
grant_type=password
username=<redacted>
password=<redacted>
client_id=app-front
```

Refresh grant:

```text
grant_type=refresh_token
refresh_token=<redacted>
client_id=app-front
```

Successful responses contain `access_token`, `refresh_token`, `expires_in`, and
`refresh_expires_in`. Live expiry and logout response bodies remain **Unknown**.

### List installations

`POST /user/read/`

```text
token=true
email=<redacted>
lang=nl_NL
```

Minimal response shape:

```json
{
  "code": {"key": "OK"},
  "data": {
    "smarthomes": [{
      "smarthome_id": "<installation-id>",
      "label": "<redacted>",
      "mac_address": "<redacted>"
    }]
  }
}
```

**Confirmed:** `smarthomes` is a list and may contain more than one
installation. Ordering and pagination are **Unknown**.

### Read an installation

`POST /smarthome/read/`

```text
token=true
smarthome_id=<installation-id>
lang=nl_NL
```

Relevant room fields:

```json
{
  "id": "<room-id>",
  "id_device": "<device-id>",
  "gv_mode": "0",
  "temperature_air": "715",
  "consigne_confort": "680",
  "consigne_eco": "620",
  "consigne_hg": "446",
  "consigne_manuel": "680",
  "consigne_boost": "720",
  "min_set_point": "410",
  "max_set_point": "860",
  "heating_up": "1",
  "heat_cool": "0",
  "error_code": "0"
}
```

- **Confirmed:** temperatures are integer-like strings in tenths Fahrenheit.
  `"680"` is 68.0 °F, or 20.0 °C.
- **Confirmed:** `id` identifies the room record; commands use `id_device`.
- **Observed:** `heating_up` and `heat_cool` use `0`/`1` strings. Their physical
  meaning is unknown.
- **Observed:** `error_code=1` matched the official low-battery display.
- **Observed:** Boost records included `time_boost` and `date_start_boost`.
  Neither is a verified countdown.

The service returns more fields than shown here.

### Read communication age

`POST /sandbox/check_last_connexion/`

```text
token=true
smarthome_id=<installation-id>
lang=nl_NL
```

```json
{
  "code": {"key": "OK"},
  "data": {
    "diffObj": {"days": 0, "hours": 0, "minutes": 0, "seconds": 12}
  }
}
```

The values look like time since the central unit last contacted the cloud, but
that interpretation is **Inferred**. The integration blocks a room command when
the parsed age exceeds 60 seconds; that is a client safety policy, not a known
server rule.

### Send a room command

`POST /query/push/`

Common fields used by the integration:

```text
token=true
context=1
smarthome_id=<installation-id>
query[id_device]=<device-id>
query[time_boost]=0
query[gv_mode]=0
query[nv_mode]=0
peremption=15000
lang=nl_NL
```

Requiredness was not tested by removing fields. The official frontend varies
the payload by operation.

| Command | Mode | Extra fields | Result |
| --- | ---: | --- | --- |
| Comfort | `0` | `query[consigne_confort]` | Confirmed |
| Off | `1` | None | Confirmed |
| Frost | `2` | `query[consigne_hg]=446`, `peremption=20000` | Confirmed |
| Eco | `3` | `query[consigne_eco]` | Confirmed |
| Boost | `4` | Duration, `query[consigne_boost]`, `query[consigne_manuel]` | Observed activation |
| Program | `13` | None | Confirmed |

Live findings:

- Normal mode changes appeared in later reads after about 6–21 seconds.
- Narrow Comfort and Eco writes changed only their matching profile.
- Adding `consigne_manuel` to a Comfort request changed that separate stored
  value. Normal writes therefore omit it.
- Program `13` resolved to Program Comfort `8` in the tested schedule phase.
- A three-minute Boost reached mode `4` after about nine seconds.
- Fresh room reads showed the short Boost duration decreasing.
- Natural Boost expiry restored the preceding Comfort, Eco, or Program mode in
  separate tests; it did not overwrite the stored Comfort or Eco target.
- A timer-only `query[time_boost]=0` request did not end Boost and changed the
  reported duration to `7200`.
- Selecting Comfort ended the tested Boost.
- No tested request contained a schedule object or called a schedule-write
  endpoint.

### Render a Program timeline

`POST /sandbox/convert_program/`

The official frontend calls this from Program views with:

```text
device_id=<device-id>
width=278
now=<unix-timestamp>
lang=nl_NL
```

Some views send `height` instead of `width`. One live request returned HTTP
`200` with `code.key=ERR_DB`. A successful response was not retained. The
integration does not use this endpoint; Program activation works through mode
`13`.

## Modes

| Value | Meaning | Status |
| ---: | --- | --- |
| `0` | Comfort | Confirmed |
| `1` | Off | Confirmed |
| `2` | Frost protection | Confirmed |
| `3` | Eco | Confirmed |
| `4` | Boost | Payload confirmed; activation observed |
| `5` | Unknown; official frontend mappings conflict | Unknown |
| `6` | Unknown; official frontend mappings conflict | Unknown |
| `8` | Program using Comfort | Confirmed |
| `11` | Program using Eco | Observed in frontend mapping |
| `13` | Generic Program request | Confirmed |
| `15` | Manual using `consigne_manuel` | Observed in frontend mapping |
| `16` | Program using Boost | Observed in frontend mapping |

Unknown mode values must remain readable and must not become writable controls.
Keep missing values, `null`, empty strings, zero, and false-like values distinct
until their behaviour is known.

## Write confirmation

```text
Send /query/push/
        ↓
Receive acknowledgement
        ↓
Poll /smarthome/read/
        ↓
Confirm mode and relevant target
```

Home Assistant starts confirmation after two seconds, retries every five
seconds, and stops after 90 seconds. This is integration behaviour, not an API
requirement.