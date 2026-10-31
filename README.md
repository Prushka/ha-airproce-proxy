# AirProce Proxy for Home Assistant

Local status and control for AirProce AI-370 and AI-600 purifiers whose Wi-Fi
modules provide no usable incoming local-control port. Home Assistant listens
for their redirected outgoing TCP connection and relays their existing traffic
to and from `tcpaph.airproce.com:8283`.

Local operation needs no AirProce account, app token, or cloud API. The relay
opens an upstream TCP connection solely to carry existing device traffic. It
does not contact `aph.airproce.com` or log into the cloud.

**Validation:** local controls, isolated HA runtime tests, fully offline
registration/reconnection and final official-app status/control all pass on
both tested models. See [docs/validation.md](docs/validation.md). The owner's
authorized HA installation and exact router rules are recorded in
[docs/deployment-20261031.md](docs/deployment-20261031.md).

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
The tested devices send periodic reports approximately every 64 seconds; the
integration also queries local status every 30 seconds after the first valid
report. Controls request fresh status immediately.

## Installation

1. Copy `custom_components/airproce_proxy` into your HA configuration's
   `custom_components` directory and restart HA.
2. Add **AirProce Proxy** through Settings → Devices & services. Supply the
   purifier name, model, MAC and LAN IP, HA's LAN address, a dedicated unused
   listening port, and the expected source address after any router SNAT.
3. Have an agent audit and manually configure the router following
   [router-setup.md](docs/router-setup.md). No router changes are automatic.
4. Add the other purifier using a different listening port. Verify both local
   controls and the official app before retaining the routing changes.

The listener port is opened by this integration, not by HA by default. First
attachment can take approximately three minutes while the purifier completes
its registration cycle; later device reconnects can take about a minute. Until
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
discarded when a cloud session fails. The relay keeps its local tasks responsive
and cannot guarantee delivery of every cloud byte during an outage. If the
cloud does not answer, the proxy supplies the three verified registration,
installed-version and status acknowledgements needed for local recovery.
It announces only the firmware version already reported by the purifier and
does not send firmware images, update URLs, weather data or configuration.
The observed device registration stays in memory until the integration unloads;
no credentials are saved to disk.

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

Run `python scripts/build.py` to create `dist/ha-airproce-proxy-0.1.0.zip`.
The archive contains only the integration and license notices. Private test
captures, configuration, and development environments are excluded.
