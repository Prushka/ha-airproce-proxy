# Validation record

Development is in progress. Passing simulated and HA runtime tests does not
establish that the official cloud/app path works. Live cloud recovery remains
an acceptance requirement before deployment.

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

The owner subsequently explicitly prohibited changes to or bypasses of
OpenClash. All subsequent live tests use only source-specific purifier DNAT
and the corresponding return-path SNAT. No persistent router rules, DNS
overrides or running-HA configuration changes are part of this delivery.

## Remaining acceptance checks

- Official app status and controls through the final relay on both models.
- Registration replay on a real upstream reconnection.
- Sustained local operation during a cloud outage, including the device's own
  recovery behavior, rather than only a short simulated outage.
- Final removal of all temporary rules/listeners/captures and confirmation of
  the original cloud route after live tests.

Optional PM10/filter-life readings remain unverified and are not exposed.
