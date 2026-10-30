"""Offline startup and transparent cloud recovery over real TCP sockets."""

import asyncio
import struct
import zlib

import pytest

from custom_components.airproce_proxy.proxy import ProxyConfig, PurifierProxy
from custom_components.airproce_proxy.recovery import (
    answered_operation,
    recovery_reply,
    recovery_request,
)

from .test_protocol import report
from .test_proxy import FakePurifier, system, wait_for

FIRMWARE = b"AI-7.3.5"


def request(opcode, payload):
    return struct.pack("!HHHB", len(payload), opcode, 0x1234, 0) + payload


def field(value):
    return len(value).to_bytes(2, "big") + value


def registration(model=b"AI-600"):
    # No real serial, MAC or authenticator. Only the string layout is meaningful.
    return request(
        1,
        b"\x10" + field(model) + bytes(8)
        + field(b"TESTMODULE") + field(b"TESTSERIAL") + field(FIRMWARE) + bytes(32),
    )


VERSION_REQUEST = request(0x103, b"\x10" + bytes(8) + field(FIRMWARE))


def test_replies_match_captures_and_only_announce_installed_version():
    assert recovery_reply(1, FIRMWARE, 0).hex() == "000cffff000117c80a000841492d372e332e35"
    stamp = int("000001a18e631e98", 16)
    assert recovery_reply(0x103, FIRMWARE, stamp).hex() == (
        "001cfefd000115c80a000001a18e631e98000001a18e631e98000841492d372e332e35"
    )
    assert recovery_reply(9, b"", int("000001a18e8b5390", 16)).hex() == (
        "0009fff700012fc8000001a18e8b5390"
    )
    for model in (b"AI-370", b"AI-600"):
        assert recovery_request(registration(model)) == (1, FIRMWARE)
    assert recovery_request(VERSION_REQUEST) == (0x103, FIRMWARE)
    assert recovery_request(report(queried=False)) == (9, b"")
    for bad in (
        registration(b"AI-999"), registration()[:40], report(),
        request(0x103, b"\x10" + bytes(8) + field(b"https://firmware")),
        request(0x10A, bytes(22)), request(0x10D, bytes(9)),
        VERSION_REQUEST + b"extra", request(7, bytes(16)),
    ):
        assert recovery_request(bad) is None
    with pytest.raises(ValueError):
        recovery_reply(0x103, b"", 0)


async def read_frame(reader):
    header = await reader.readexactly(2)
    return header + await reader.readexactly(int.from_bytes(header, "big") + 5)


class BootingPurifier(FakePurifier):
    async def connect(self, port):
        self.reader, self.writer = await asyncio.open_connection("127.0.0.1", port)
        for packet, opcode in ((registration(), 0xFFFF), (VERSION_REQUEST, 0xFEFD)):
            # Wait for the startup reply before permitting state/control traffic.
            self.writer.write(packet)
            await self.writer.drain()
            async with asyncio.timeout(1):
                reply = await read_frame(self.reader)
            assert int.from_bytes(reply[2:4], "big") == opcode
            assert reply[4:6] == b"\x00\x01" and reply[7:9] == b"\xc8\x0a"
            crc = zlib.crc32(reply[7:]).to_bytes(4, "big")
            assert reply[6] == crc[0] ^ crc[1] ^ crc[2] ^ crc[3]
            assert reply.endswith(field(FIRMWARE))
        self.writer.write(report(queried=False))
        await self.writer.drain()
        self.task = asyncio.create_task(self.run())


async def test_fresh_start_and_device_reconnection_work_without_cloud():
    reserve = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    unused_port = reserve.sockets[0].getsockname()[1]
    reserve.close()
    await reserve.wait_closed()
    proxy = PurifierProxy(
        ProxyConfig(
            "127.0.0.1", 0, "127.0.0.1", cloud_host="127.0.0.1", cloud_port=unused_port,
            retry_delay=0.05, acknowledgement_timeout=0.05,
        ),
        lambda: None,
    )
    await proxy.start()
    try:
        for _ in range(2):
            device = BootingPurifier()
            await device.connect(proxy.server.sockets[0].getsockname()[1])
            try:
                await wait_for(lambda: proxy.available)
                await proxy.execute("fan_3")
                assert proxy.state.speed == 3
                await proxy.execute("auto")
                assert proxy.state.mode == "auto"
                assert not proxy.cloud_connected and not proxy.session.cloud_bytes_received
                await wait_for(lambda d=device: any(f[2:4] == b"\xff\xf7" for f in d.frames))
            finally:
                await device.close()
                await wait_for(lambda: proxy.session is None)
    finally:
        await proxy.stop()
    assert not proxy._tasks


async def test_timely_cloud_reply_prevents_duplicate_and_traffic_is_unchanged():
    async with system(acknowledgement_timeout=0.15) as (proxy, device, cloud):
        device.writer.write(registration())
        device.writer.write(VERSION_REQUEST)
        await device.writer.drain()
        await wait_for(lambda: VERSION_REQUEST in cloud.received)
        ack = recovery_reply(0x103, FIRMWARE, 123000)
        cloud.connections[-1].write(ack)
        await cloud.connections[-1].drain()
        await wait_for(lambda: ack in device.frames)
        await asyncio.sleep(0.2)
        assert [f for f in device.frames if f[2:4] == b"\xfe\xfd"] == [ack]
        assert bytes(cloud.received) == registration() + VERSION_REQUEST


async def test_silent_cloud_uses_fallback_and_late_reply_is_still_forwarded():
    async with system(acknowledgement_timeout=0.05) as (proxy, device, cloud):
        device.writer.write(registration())
        device.writer.write(VERSION_REQUEST)
        await device.writer.drain()
        await wait_for(lambda: any(f[2:4] == b"\xfe\xfd" for f in device.frames))
        assert proxy.cloud_connected  # A live TCP socket need not answer requests.
        fallback = next(f for f in device.frames if f[2:4] == b"\xfe\xfd")
        assert answered_operation(fallback) == 0x103
        assert bytes(cloud.received) == registration() + VERSION_REQUEST
        late = recovery_reply(0x103, FIRMWARE, 123000)
        cloud.connections[-1].write(late)
        await cloud.connections[-1].drain()
        await wait_for(lambda: late in device.frames)
        await proxy.execute("fan_2")
        assert proxy.state.speed == 2
        assert [f for f in device.frames if f[2:4] == b"\xfe\xfd"] == [fallback, late]


async def test_repeated_requests_do_not_postpone_fallback_or_grow_pending_work():
    async with system(acknowledgement_timeout=0.1) as (proxy, device, cloud):
        device.writer.write(registration())
        for _ in range(20):
            device.writer.write(VERSION_REQUEST)
            await device.writer.drain()
            await asyncio.sleep(0.01)
            assert len(proxy.session._acknowledgements) <= 3
        assert any(f[2:4] == b"\xfe\xfd" for f in device.frames)
        assert bytes(cloud.received) == registration() + VERSION_REQUEST * 20


async def test_initial_version_retries_cannot_prevent_first_registration():
    async with system(acknowledgement_timeout=0.05) as (proxy, device, cloud):
        device.writer.write(VERSION_REQUEST)
        await device.writer.drain()
        await asyncio.sleep(0.1)
        assert not any(f[2:4] == b"\xfe\xfd" for f in device.frames)
        assert not any(f[2:4] == b"\xff\xf7" for f in device.frames)
        assert bytes(cloud.received) == VERSION_REQUEST
        device.writer.write(registration() + VERSION_REQUEST)
        await device.writer.drain()
        await wait_for(lambda: any(f[2:4] == b"\xfe\xfd" for f in device.frames))


async def test_device_reconnect_retains_observed_registration_for_cloud_recovery():
    async with system(acknowledgement_timeout=0.05) as (proxy, device, cloud):
        device.writer.write(registration())
        await device.writer.drain()
        await wait_for(lambda: proxy._registration is not None)
        other = FakePurifier()
        old = proxy.session
        await other.connect(proxy.server.sockets[0].getsockname()[1])
        try:
            await wait_for(lambda: proxy.session is not old and proxy.available)
            await wait_for(lambda: bytes(cloud.received).count(registration()) == 2)
            other.writer.write(VERSION_REQUEST)
            await other.writer.drain()
            await wait_for(lambda: any(f[2:4] == b"\xfe\xfd" for f in other.frames))
            await proxy.execute("fan_2")
        finally:
            await other.close()
        await proxy.stop()
        assert proxy._registration is None
