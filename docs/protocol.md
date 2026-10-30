# Observed protocol and implementation boundaries

The command templates and status layout originate in the MIT-licensed
[ha-airproce](https://github.com/jackjinke/ha-airproce) and
[home-assistant-airproce-bridge](https://github.com/Griddz/home-assistant-airproce-bridge)
projects. See `THIRD_PARTY_NOTICES`. Live verification was performed on an
AI-370 and AI-600; this is not a claim about every AirProce firmware.

## Framing and status

The big-endian length word excludes the first seven bytes. The following
two bytes identify the operation, and bytes 4–5 correlate requests/replies.
Unknown operation payloads are forwarded without interpreting or rewriting
them. Byte 6 and captured timestamps remain opaque in the command templates.

Known state notifications are 35 bytes (`001c0009`); local query responses are
36 bytes (`001dfffc`) with a 20-byte status tail. Validated fields are:

| Tail offset | Interpretation |
| --- | --- |
| 0–1 | PM2.5, µg/m³ |
| 4–5 | Temperature, tenths of °C |
| 6–7 | Humidity, tenths of % |
| 8–9 | VOC, thousandths of mg/m³ |
| 12 | Speed 1–6; 255 for observed off state |
| 13 | Manual 0x01, Auto 0x02, Sleep 0x20–0x22, off 0x11/0x12 |

Both tested units report `(speed=255, mode=0x12)` after power-off. The older
decoder recognized only 0x11. Captured mode and speed transitions are checked
through fresh queries, not optimistic entity updates.

The units sometimes send a truncated notification prefix before a complete
report. The state observer resynchronizes on validated report envelopes while
the forwarding path preserves the original prefix bytes. Unknown status-tail
fields are not assigned guessed meanings.

## Controls

Six manual speeds, Auto, Sleep, power-off and power-on were verified on both
units. `smart` is the HA preset name for Auto; they are not distinct modes.
Preset commands use the **current** hardware speed, not an earlier saved speed.
When off, preset selection first turns the purifier on and reads its actual
state. Setting manual speed is represented by HA fan percentage.

These units did not emit the older bridge's expected `fff9` control ACK during
testing. The proxy therefore confirms the desired state with correlated local
queries. Changing the two-byte request ID was verified for queries and control
templates on both units. Fresh IDs avoid recently observed cloud requests;
replies to the proxy's own requests are not sent upstream. Normal unsolicited
state reports and cloud-requested responses are forwarded.

## Registration and recovery

A newly connected TCP socket need not immediately produce a registration.
During observed recovery, firmware-version messages (`0103`) retried for about
two minutes before the device opened a new connection and sent operation
`0001`. That frame contains model/firmware, identifiers and an opaque device
authenticator. A `ffff` cloud response with status byte 200 confirmed it.

The relay forwards the device's registration without generating credentials.
For reconnects of the upstream within the same device session, it retains that
one observed frame in RAM and replays it before subsequent device traffic.
It never writes the authenticator to configuration, diagnostics, or logs.
Live replay validation is tracked separately in `validation.md`.

Cloud weather/configuration replies and other unknown operations are passed
through unchanged. Registration exposes a firmware string; other messages
contain additional numbers, but no PM10 or filter-life entity is exposed
without verified field meanings and units.

## Failure isolation

Device reading, local commands and the cloud connection use separate tasks.
The upstream queue is bounded by bytes. Failure, timeout or overflow resets
only the cloud session and drops stale queued data. A cloud message is framed
before it is written to the purifier, preventing local requests from splitting
a fragmented cloud command. A stalled partial cloud message is discarded with
that failed cloud session. Failed local commands raise a HA service error.

The software does not change DNS, module settings, Wi-Fi configuration or
router rules, and performs no HTTP account login or AirProce account API calls.
