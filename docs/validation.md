# Validation record

Development is in progress. The owner confirmed live official app status and
controls through the relay on both models. A stricter outage test exposed a
remaining firmware startup/recovery dependency; deployment is still blocked
on the fully local requirement described below.

## Confirmed on physical devices, 2026-10-30

| Operation | AI-370 | AI-600 |
| --- | --- | --- |
| Manual speeds 1, 2, 3, 4, 5, 6 | Fresh queried state confirmed | Fresh queried state confirmed |
| Smart/Auto | Confirmed | Confirmed |
| Sleep | Confirmed | Confirmed |
| Power off and on | Confirmed | Confirmed |
| Temperature, humidity, PM2.5, VOC, fan state | Read successfully | Read successfully |
| Correlation ID changes on queries/controls | Confirmed | Confirmed |

The control matrix required two fresh matching query replies per operation.
Both purifiers were restored to Auto. Power-off exposed raw state `(255, 0x12)`
on both units, which the older integration did not decode. No filter reset,
Wi-Fi configuration, module provisioning or factory-reset operation was sent.

## Automated tests

- Real loopback TCP peers exercise bidirectional forwarding, unknown frame
  preservation, fragmentation, malformed notification recovery, private reply
  isolation, query ID collisions, upstream loss/reconnection, bounded queues,
  failed-command reporting, peer rejection, connection replacement and cleanup.
- Startup tests require passive device readiness before any local query.
- Synthetic device registration tests verify framing through the observed
  `AT+CIPSENDRAW` preamble and replay on an upstream reconnect. All credentials
  in those tests are synthetic.
- Home Assistant 2026.10.4 runs on Linux in a dedicated test environment, with
  temporary HA configuration directories and loopback HTTP/TCP ports. Tests
  cover both models, five entities, real fan services, sensor units/readings,
  configuration validation, options validation, registry identity and reload.
- Core tests also run on Windows/Python 3.14 without Home Assistant installed.
  HA-specific tests skip there. Ruff is run across the source and tests.

No test installs this integration into the owner's running HA instance.

## Findings that required additional live testing

1. Short relay tests initially showed local control but no official app
   updates. The upstream TCP socket was connected but not registered.
2. A router reboot and concurrent changes by a different agent overlapped
   early tests. Those results cannot establish the final network behavior.
3. A later stable-network capture showed firmware retries for approximately
   two minutes, followed by a new connection and a device registration frame.
   A normal cloud reply accepted that registration.
4. Immediate local queries during new connections coincided with failed
   startup and module-command text in the TCP stream. Local polling now waits
   for a validated device report. Preamble bytes are preserved, not discarded.
5. Stable live tests established registered cloud sessions on both models.
   The AI-370 exposed a command-readback timeout. After bounded confirmation
   retries and query/reply serialization were added, AI-600 local speed control
   and restoration to Auto passed with its cloud session still registered.
6. The owner confirmed that AI-600 official app status and controls work
   through the corrected relay. App-issued manual speed and preset changes
   were also observed in the proxy's live local state.
7. An intentional AI-600 upstream reconnect retained the same device TCP
   session. Local speed control succeeded during reconnect, Auto was restored,
   and the cloud accepted the replayed device registration.
8. During a 180-second AI-600 upstream outage, fresh local status continued
   without a device TCP reconnect. Cloud registration recovered afterward.
9. A separate AI-600 test started with the upstream unavailable. Local speed 3
   and restoration to Auto both succeeded with zero cloud bytes sent/received.
10. Final-code AI-370 local speed control passed and Auto was restored. The
    owner confirmed its app status and controls through the relay. App-issued
    manual speed, Auto and Sleep changes appeared in local state.

## Offline startup/recovery issue (not resolved)

The established AI-600 session survived the three-minute outage above, but that
does not prove indefinite cloud independence. After an intentional device TCP
reconnect without upstream access, the AI-600 repeatedly registered and reset
its connection without resuming valid status. An AI-370 outage also caused its
own connection to reset after roughly two minutes, despite earlier successful
local control during the outage.

A read-only status query during startup did not resolve this. An isolated
experiment using the observed registration acknowledgement restored AI-600
status/control temporarily. Firmware-version request/reply handling remains
unverified; modified replies did not establish stable recovery. None of that
experimental emulation is included in the integration. No firmware image,
provisioning, filter-reset or Wi-Fi-setting command was sent.

Both purifiers subsequently returned to their original direct cloud routes;
passive capture confirmed both powered on in Auto. All temporary test NAT
tables, listeners and captures were stopped. The isolated test environment
and private captures remain outside the running HA configuration and Git.

The owner subsequently explicitly prohibited changes to or bypasses of
OpenClash. All subsequent live tests use only source-specific purifier DNAT
and the corresponding return-path SNAT. No persistent router rules, DNS
overrides or running-HA configuration changes are part of this delivery.

## Remaining acceptance checks

- Resolve and verify device startup/recovery without cloud access on both
  models, including a sustained outage and a device TCP reconnect.
- Recheck normal app forwarding after any protocol fallback changes.

Optional PM10/filter-life readings remain unverified and are not exposed.
