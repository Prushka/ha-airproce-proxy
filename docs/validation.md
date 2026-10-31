# Validation record

Local status/control, fully offline startup/recovery, cloud reconnection and
official-app status/control passed on physical AI-370 and AI-600 units running
AI-7.3.5. Deployment into Home Assistant 2026.10.4 also passed. These results
describe the tested models and firmware, not every AirProce device.

This public record contains reusable technical findings. Device identities,
addresses, deployment rules, private captures and individual installation
records are deliberately excluded.

## Confirmed on physical devices

| Operation | AI-370 | AI-600 |
| --- | --- | --- |
| Manual speeds 1, 2, 3, 4, 5, 6 | Fresh queried state confirmed | Fresh queried state confirmed |
| Smart/Auto | Confirmed | Confirmed |
| Sleep | Confirmed | Confirmed |
| Power off and on | Confirmed | Confirmed |
| Temperature, humidity, PM2.5, VOC, fan state | Read successfully | Read successfully |
| Correlation ID changes on queries/controls | Confirmed | Confirmed |
| Official-app status and controls through the relay | Confirmed | Confirmed |
| Offline startup and device reconnection | Confirmed | Confirmed |

The full control matrix required two fresh matching query replies per
operation. Purifiers were restored to Auto after testing. No filter reset,
Wi-Fi configuration, module provisioning, factory reset or firmware update
was performed.

Power-off exposed raw state `(255, 0x12)` on both units, which the older
integration did not decode. Optional PM10/filter-life readings remain
unverified and are not exposed.

## Automated tests

- Real loopback TCP peers exercise bidirectional forwarding, unknown frame
  preservation, fragmentation, malformed notification recovery, private reply
  isolation, query ID collisions, upstream loss/reconnection, bounded queues,
  failed-command reporting, peer rejection, connection replacement and cleanup.
- Startup tests require passive device readiness before any local query.
- Synthetic device registration tests verify framing through the observed
  `AT+CIPSENDRAW` preamble and replay on an upstream reconnect. Test identities
  and authentication fields are synthetic; no live registration is included.
- Home Assistant 2026.10.4 runs on Linux in a dedicated test environment, with
  temporary HA configuration directories and loopback HTTP/TCP ports. Tests
  cover both models, five entities, real fan services, sensor units/readings,
  configuration validation, options validation, registry identity and reload.
- Core tests also run on Windows/Python 3.14 without Home Assistant installed.
  HA-specific tests skip there. Ruff is run across the source and tests.
- Offline recovery tests use peers that refuse to report state until they
  receive valid registration/version replies. They cover fresh startup, device
  reconnection, retained registration, timely/late cloud replies, silent cloud
  sockets, bounded pending work and cleanup.

Recorded results: Linux 32 passed; Windows core 28 passed with the HA module
skipped; Ruff passed. Automated tests do not install into a running HA instance.

## Protocol findings and failure recovery

Short relay tests initially showed local control while the official app was
stale. A connected upstream TCP socket was insufficient: a real device
registration had to be accepted by the cloud. The tested firmware could retry
for several minutes before opening a fresh connection and registering.

Immediate local queries during startup could interfere with initialization.
Local polling now waits for a validated device report. Module preamble bytes
are forwarded immediately. Query/reply serialization and bounded confirmation
retries resolved a command-readback timeout while preserving cloud frames.

Short cloud outages did not establish fully offline recovery. After a device
reconnect without upstream access, the firmware waited for startup replies and
repeatedly reset its connection. Correct local acknowledgements require a
checksum formed by XOR-folding all four CRC32 bytes over the payload.

Only the three verified registration, installed-version and status
acknowledgements are supplied locally after a bounded cloud-response timeout.
On first attachment, status/version fallback waits until registration is
observed; acknowledging reports too early could prevent cloud identification.
The version reply announces only the firmware already installed on the device.

Both models then passed extended offline operation for more than eight minutes,
including fresh registration and forced device reconnection, with current local
status and speed/Auto controls. Restoring forwarding recovered cloud
registration without requiring another device reconnect. Idle cloud
timeout/reconnect was also observed to recover while local state stayed
available on the same device connection.

The final build passed official-app live status, manual speeds and Smart mode
on both models, with corresponding changes independently observed in local
state. HA deployment checks confirmed five entities per device, live sensors,
HA manual speed control and restoration to Smart, plus official-app control.

## Deployment boundary

Each deployment requires a new manual audit and explicit authorization under
`AGENTS.md` and [router-setup.md](router-setup.md). Test results do not authorize
changes to any other installation. Private before/after router snapshots and
exact deployment/rollback records must stay outside tracked files.
