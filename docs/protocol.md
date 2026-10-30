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
them. Byte 6 is the XOR of all four bytes of CRC32 over the payload starting at
byte 7. This matched all eleven captured local request templates and thirty
distinct captured nonzero checksums, with no mismatches. Device-originated
frames on the tested units commonly contain zero in that field. Timestamps in
the captured control templates are retained; changing a preset's speed context
requires recalculating its payload checksum.

The module can first emit the literal text `AT+CIPSENDRAW` followed by a
carriage return. This observed preamble is forwarded immediately and unchanged,
before applying binary framing to subsequent bytes. Treating its ASCII letters
as a binary length delayed and combined it with the registration message.

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

The next cloud frame waits for an outstanding local query/reply exchange to
finish (bounded by the query timeout), preventing simultaneous messages from
competing in the shared UART parser. Only confirmation queries are retried;
the control command itself is not automatically resent.

## Registration and recovery

A newly connected TCP socket need not immediately produce a registration.
During observed recovery, firmware-version messages (`0103`) retried for about
two minutes before the device opened a new connection and sent operation
`0001`. That frame contains model/firmware, identifiers and an opaque device
authenticator. A `ffff` cloud response with status byte 200 confirmed it.

The relay forwards the device's registration without generating credentials.
For upstream and device TCP reconnects, it retains that one observed frame in
RAM for the lifetime of the integration entry and replays it before subsequent
device traffic. Unloading the entry clears it; it is never saved to disk.
It never writes the authenticator to configuration, diagnostics, or logs.
Live replay validation is tracked separately in `validation.md`.

Three known acknowledgements can be answered locally if the cloud has not
answered within one second (plus any bounded local query already in progress):

| Device request | Local fallback | Contents |
| --- | --- | --- |
| `0001`, registration for AI-370/AI-600 | `ffff` | Success and the device's own installed firmware string |
| `0103`, firmware version check | `fefd` | Success, current UTC milliseconds twice, same installed firmware string |
| `0009`, validated status report | `fff7` | Success and current UTC milliseconds |

These use the observed server correlation ID `0001`, whole-second timestamps,
and a recalculated folded CRC32. No firmware image, update URL or different
version is supplied. Weather and unknown requests are not emulated. The
pending work is bounded to three operations; retries do not postpone an
existing deadline. A timely checksummed cloud reply cancels its fallback.
Late cloud replies are still forwarded unchanged, as are the original requests.

On first attachment, version retries are allowed to finish the device's
natural registration cycle before version fallback is enabled. Otherwise a
device can stay locally responsive without ever identifying itself to the
upstream server. First attachment or an HA restart can therefore take a few
minutes. Once observed, the registration remains available across device TCP
reconnects without needing any cloud response or account login.

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
