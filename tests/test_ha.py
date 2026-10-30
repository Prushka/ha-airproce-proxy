"""Real Home Assistant 2026.10 runtime, registries, flows and entity services."""

import asyncio
import functools
import shutil
import socket
from pathlib import Path

import pytest

pytest.importorskip("homeassistant")

from homeassistant import bootstrap, loader  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.helpers import entity_registry as er  # noqa: E402

from custom_components.airproce_proxy import runtime  # noqa: E402
from custom_components.airproce_proxy.proxy import ProxyConfig  # noqa: E402
from tests.test_proxy import FakeCloud, FakePurifier, wait_for  # noqa: E402

pytestmark = pytest.mark.ha


@pytest.fixture
async def ha(tmp_path, monkeypatch):
    cloud = FakeCloud()
    server = await asyncio.start_server(cloud.accept, "127.0.0.1", 0)
    monkeypatch.setattr(
        runtime,
        "ProxyConfig",
        functools.partial(
            ProxyConfig,
            cloud_host="127.0.0.1",
            cloud_port=server.sockets[0].getsockname()[1],
        ),
    )
    config = tmp_path / "ha"
    shutil.copytree(
        Path(__file__).parents[1] / "custom_components",
        config / "custom_components",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    hass = HomeAssistant(str(config))
    hass.config.skip_pip = True
    loader.async_setup(hass)
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        http_port = reserve.getsockname()[1]
    try:
        assert (
            await bootstrap.async_from_config_dict(
                {
                    "http": {"server_host": "127.0.0.1", "server_port": http_port},
                    "homeassistant": {
                        "name": "Isolated AirProce test",
                        "latitude": 0,
                        "longitude": 0,
                        "elevation": 0,
                        "unit_system": "metric",
                        "time_zone": "UTC",
                        "country": "US",
                    },
                },
                hass,
            )
            is hass
        )
        await hass.async_start()
        await hass.async_block_till_done()
        yield hass
    finally:
        await hass.async_stop()
        await cloud.close()
        server.close()
        await server.wait_closed()


def configuration(model="AI-600", mac="02:00:00:00:00:01"):
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    return {
        "name": model,
        "model": model,
        "mac": mac,
        "purifier_host": "127.0.0.2",
        "listen_host": "127.0.0.1",
        "allowed_peer": "127.0.0.1",
        "listen_port": port,
    }


@pytest.mark.parametrize("model", ["AI-370", "AI-600"])
async def test_real_entities_services_reload_and_registry_identity(ha, model):
    data = configuration(model)
    flow = await ha.config_entries.flow.async_init("airproce_proxy", context={"source": "user"})
    result = await ha.config_entries.flow.async_configure(flow["flow_id"], data)
    assert result["type"] == "create_entry", result
    entry = result["result"]
    await ha.async_block_till_done()
    registry = er.async_get(ha)
    registered = er.async_entries_for_config_entry(registry, entry.entry_id)
    ids = {item.unique_id: item.entity_id for item in registered}
    assert len(ids) == 5
    fan_id = ids[f"{data['mac']}-fan"]
    assert ha.states.get(fan_id).state == "unavailable"
    assert {item.domain for item in registered} == {"fan", "sensor"}
    device = FakePurifier()
    await device.connect(data["listen_port"])
    try:
        await wait_for(lambda: ha.states.get(fan_id).state == "on")
        await ha.services.async_call(
            "fan",
            "set_percentage",
            {
                "entity_id": fan_id,
                "percentage": 50,
            },
            blocking=True,
        )
        assert device.speed == 3 and ha.states.get(fan_id).attributes["percentage"] == 50
        assert ha.states.get(fan_id).attributes["preset_mode"] is None
        for preset in ("sleep", "smart"):
            await ha.services.async_call(
                "fan",
                "set_preset_mode",
                {
                    "entity_id": fan_id,
                    "preset_mode": preset,
                },
                blocking=True,
            )
            assert ha.states.get(fan_id).attributes["preset_mode"] == preset
        await ha.services.async_call("fan", "turn_off", {"entity_id": fan_id}, blocking=True)
        assert ha.states.get(fan_id).state == "off"
        await ha.services.async_call("fan", "turn_on", {"entity_id": fan_id}, blocking=True)
        assert ha.states.get(fan_id).state == "on"
        assert ha.states.get(ids[f"{data['mac']}-temp"]).state == "24.5"
        assert ha.states.get(ids[f"{data['mac']}-humidity"]).state == "65.4"
        assert ha.states.get(ids[f"{data['mac']}-pm25"]).state == "7"
        assert ha.states.get(ids[f"{data['mac']}-voc"]).state == "0.015"
        assert await ha.config_entries.async_reload(entry.entry_id)
        await ha.async_block_till_done()
        assert {
            item.unique_id: item.entity_id
            for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        } == ids
        assert ha.states.get(fan_id).state == "unavailable"
        assert await ha.config_entries.async_unload(entry.entry_id)
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", data["listen_port"]))
    finally:
        await device.close()


async def test_config_rejects_duplicates_invalid_addresses_and_occupied_ports(ha):
    data = configuration()
    flow = await ha.config_entries.flow.async_init("airproce_proxy", context={"source": "user"})
    bad = await ha.config_entries.flow.async_configure(
        flow["flow_id"], {**data, "listen_host": "0.0.0.0"}
    )
    assert bad["errors"] == {"base": "invalid_config"}
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", data["listen_port"]))
        occupied.listen()
        bad = await ha.config_entries.flow.async_configure(flow["flow_id"], data)
        assert bad["errors"] == {"base": "cannot_bind"}
    good = await ha.config_entries.flow.async_configure(flow["flow_id"], data)
    assert good["type"] == "create_entry"
    await ha.async_block_till_done()
    flow2 = await ha.config_entries.flow.async_init("airproce_proxy", context={"source": "user"})
    duplicate = await ha.config_entries.flow.async_configure(flow2["flow_id"], data)
    assert duplicate["type"] == "abort" and duplicate["reason"] == "already_configured"
    flow3 = await ha.config_entries.flow.async_init("airproce_proxy", context={"source": "user"})
    duplicate_port = await ha.config_entries.flow.async_configure(
        flow3["flow_id"],
        {**data, "mac": "02:00:00:00:00:02"},
    )
    assert duplicate_port["errors"] == {"base": "port_in_use"}


async def test_options_validate_bind_before_replacing_working_listener(ha):
    data = configuration()
    flow = await ha.config_entries.flow.async_init("airproce_proxy", context={"source": "user"})
    result = await ha.config_entries.flow.async_configure(flow["flow_id"], data)
    entry = result["result"]
    await ha.async_block_till_done()
    original = entry.runtime_data.proxy
    options = await ha.config_entries.options.async_init(entry.entry_id)
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        invalid = await ha.config_entries.options.async_configure(
            options["flow_id"],
            {
                **data,
                "listen_port": occupied.getsockname()[1],
            },
        )
        assert invalid["errors"] == {"base": "cannot_bind"}
    assert entry.runtime_data.proxy is original and original.server is not None
    assert entry.data["listen_port"] == data["listen_port"]
    updated = await ha.config_entries.options.async_configure(
        options["flow_id"],
        {
            **data,
            "name": "Bedroom purifier",
        },
    )
    assert updated["type"] == "create_entry"
    await ha.async_block_till_done()
    assert entry.title == "Bedroom purifier" and original.server is None
    assert entry.runtime_data.proxy.server is not None
