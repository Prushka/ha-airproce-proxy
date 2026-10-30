# AirProce Proxy for Home Assistant

Local status and control for AirProce AI-370 and AI-600 purifiers whose Wi-Fi
modules provide no usable incoming local-control port. Home Assistant listens
for their redirected outgoing TCP connection and relays their existing traffic
to and from `tcpaph.airproce.com:8283`.

Local operation needs no AirProce account, app token, or cloud API. The relay
opens an upstream TCP connection solely to carry existing device traffic. It
does not contact `aph.airproce.com` or log into the cloud.

**Development status:** local controls and isolated HA runtime tests pass.
Live cloud forwarding is still under investigation. Do not deploy until the
remaining validation in [docs/validation.md](docs/validation.md) is complete.

## Entities

Each purifier has one fan and four measurement sensors, using the same naming
pattern and units as the local mode of
[ha-airproce](https://github.com/jackjinke/ha-airproce):

| Entity | Supported behavior |
| --- | --- |
| Fan | Power on/off, six manual speeds, Smart/Auto, Sleep |
| Temperature | °C |
| Humidity | % |
| PM2.5 | µg/m³ |
| VOC | mg/m³ |

Smart and Auto are the same verified hardware mode. Choose a fan percentage to
select a manual speed; manual operation has no preset, following HA's fan
entity conventions. There are no filter-reset buttons or unverified controls.
PM10, filter life, and other unknown status bytes are not exposed.

Controls use a fresh local query to confirm the result. A successful write to a
socket is not treated as successful control. Local availability depends on the
device connection and recent validated status, independently of cloud state.

## Installation, when ready

1. Copy `custom_components/airproce_proxy` into your HA configuration's
   `custom_components` directory and restart HA.
2. Add **AirProce Proxy** through Settings → Devices & services. Supply the
   purifier name, model, MAC and LAN IP, HA's LAN address, a dedicated unused
   listening port, and the expected source address after any router SNAT.
3. Have an agent audit and manually configure the router following
   [router-setup.md](docs/router-setup.md). No router changes are automatic.
4. Add the other purifier using a different listening port. Verify both local
   controls and the official app before retaining the routing changes.

The listener port is opened by this integration, not by HA by default. Until
the redirected device connects, its entities remain unavailable. The listener
binds only the explicitly configured IPv4 address and accepts only the expected
peer IP. This plaintext device protocol has no local authentication: keep the
listener restricted to the trusted LAN and never expose it to the internet.

HA Container must be able to bind the selected LAN address (normally host
networking). If HA stops while redirection remains active, cloud access through
that path also stops. Removing the task-owned router rules restores the original
direct path. The integration cannot repair router configuration automatically.

## Cloud failure behavior

The device reader never waits for upstream connection or queue capacity.
Cloud forwarding has a 256 KiB queue per purifier, bounded connection/write
timeouts, and reconnects after a stall or overflow. Stale queued bytes are
discarded when a cloud session fails. Thus local control stays responsive, but
the relay cannot guarantee delivery of every cloud byte during an outage.

Normal cloud messages keep their content and correlation IDs. Replies to
HA-generated queries are kept local; ordinary device reports continue to the
cloud. Cloud frames are assembled before writing to the purifier so a local
command cannot be inserted into the middle of a fragmented cloud command.

## Development and tests

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
```

For real HA tests, use an isolated Linux environment and additionally install
`requirements-ha-test.txt`. These tests create their own HA config directories
and loopback listeners; they do not use a running HA installation or real cloud.
See [protocol notes](docs/protocol.md) and [validation](docs/validation.md).
