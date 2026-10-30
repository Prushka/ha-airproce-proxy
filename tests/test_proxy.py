"""Use real loopback sockets to exercise independent cloud and local paths."""

import asyncio
from contextlib import asynccontextmanager, suppress
from dataclasses import replace

import pytest

from custom_components.airproce_proxy.proxy import ControlError, ProxyConfig, PurifierProxy

from .test_protocol import report


async def wait_for(predicate, timeout=2):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


class FakePurifier:
    """An independent wire peer: echo query IDs and apply the ten known operations."""

    def __init__(self):
        self.speed, self.mode = 1, 2
        self.frames = []
        self.respond = True
        self.apply = True
        self.writer = None

    async def connect(self, port):
        self.reader, self.writer = await asyncio.open_connection("127.0.0.1", port)
        self.writer.write(report(speed=self.speed, mode=self.mode, queried=False))
        await self.writer.drain()
        self.task = asyncio.create_task(self.run())

    async def run(self):
        try:
            while True:
                header = await self.reader.readexactly(2)
                frame = header + await self.reader.readexactly(int.from_bytes(header) + 5)
                self.frames.append(frame)
                opcode, seq = int.from_bytes(frame[2:4]), int.from_bytes(frame[4:6])
                if opcode == 7 and self.apply:
                    speed, mode = frame[15:17]
                    if mode == 16:
                        self.speed, self.mode = 255, 18
                    elif mode == 0:
                        self.speed, self.mode = 1, 1
                    else:
                        self.speed, self.mode = speed, mode
                    self.writer.write(report(speed=self.speed, mode=self.mode, queried=False))
                if opcode == 4 and self.respond:
                    self.writer.write(report(sequence=seq, speed=self.speed, mode=self.mode))
                await self.writer.drain()
        except asyncio.IncompleteReadError, ConnectionError:
            pass

    async def close(self):
        self.writer.close()
        await self.writer.wait_closed()
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)


class FakeCloud:
    def __init__(self):
        self.connections = []
        self.received = bytearray()
        self.tasks = []

    def accept(self, reader, writer):
        self.connections.append(writer)
        self.tasks.append(asyncio.create_task(self.read(reader)))

    async def read(self, reader):
        with suppress(ConnectionError):
            while data := await reader.read(65536):
                self.received.extend(data)

    async def close(self):
        for writer in self.connections:
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)


@asynccontextmanager
async def system(**overrides):
    cloud, device = FakeCloud(), FakePurifier()
    cloud_server = await asyncio.start_server(cloud.accept, "127.0.0.1", 0)
    port = cloud_server.sockets[0].getsockname()[1]
    config = ProxyConfig(
        "127.0.0.1",
        0,
        "127.0.0.1",
        cloud_host="127.0.0.1",
        cloud_port=port,
        poll_interval=60,
        query_timeout=0.2,
        retry_delay=0.05,
        fragment_timeout=0.2,
        cloud_idle_timeout=60,
    )
    events = []
    proxy = PurifierProxy(replace(config, **overrides), lambda: events.append(True))
    await proxy.start()
    await device.connect(proxy.server.sockets[0].getsockname()[1])
    try:
        await wait_for(lambda: proxy.available and cloud.connections)
        await wait_for(lambda: bytes(cloud.received) == report(queried=False))
        cloud.received.clear()
        yield proxy, device, cloud
    finally:
        await device.close()
        await proxy.stop()
        await cloud.close()
        cloud_server.close()
        await cloud_server.wait_closed()


async def test_cloud_bytes_and_local_commands_share_stream_without_reply_leaks():
    async with system() as (proxy, device, cloud):
        # Private startup status replies must never appear on the cloud stream.
        assert cloud.received == b""
        await proxy.execute("fan_4")
        assert proxy.state.speed == 4 and proxy.state.mode == "manual"
        notification = report(speed=4, mode=1, queried=False)
        await wait_for(lambda: bytes(cloud.received) == notification)
        # A cloud-owned query must be passed through exactly, and get its reply.
        raw = bytes.fromhex("000800041234250000019fd0e781af")
        cloud.connections[-1].write(raw[:5])
        await cloud.connections[-1].drain()
        await asyncio.sleep(0.02)
        cloud.connections[-1].write(raw[5:])
        await cloud.connections[-1].drain()
        await wait_for(lambda: raw in device.frames)
        expected = notification + report(sequence=0x1234, speed=4, mode=1)
        await wait_for(lambda: bytes(cloud.received) == expected)


async def test_partial_stalled_cloud_command_cannot_block_or_corrupt_local_control():
    async with system(fragment_timeout=0.1) as (proxy, device, cloud):
        partial = bytes.fromhex("00100007123425")
        cloud.connections[-1].write(partial)
        await cloud.connections[-1].drain()
        async with asyncio.timeout(1):
            await proxy.execute("fan_2")
        assert proxy.state.speed == 2
        assert not any(frame.startswith(partial) for frame in device.frames)
        await wait_for(lambda: len(cloud.connections) >= 2)
        assert proxy.available


async def test_cloud_disconnect_reconnects_without_device_reconnect():
    async with system() as (proxy, device, cloud):
        session = proxy.session
        cloud.connections[-1].close()
        await cloud.connections[-1].wait_closed()
        await proxy.execute("sleep")
        await wait_for(lambda: len(cloud.connections) >= 2)
        assert proxy.session is session and proxy.available
        assert proxy.state.mode == "sleep"


async def test_cloud_reconnect_replays_only_observed_device_registration():
    # Synthetic registration with no real serial, MAC, or authenticator.
    registration = bytes.fromhex("005e000100010010000641492d363030") + bytes(85)
    async with system() as (proxy, device, cloud):
        device.writer.write(registration)
        await device.writer.drain()
        await wait_for(lambda: bytes(cloud.received) == registration)
        session = proxy.session
        cloud.connections[-1].close()
        await cloud.connections[-1].wait_closed()
        await wait_for(lambda: len(cloud.connections) >= 2)
        await wait_for(lambda: bytes(cloud.received) == registration * 2)
        assert proxy.session is session and proxy.available
        await proxy.execute("fan_3")
        assert proxy.state.speed == 3


async def test_local_status_does_not_depend_on_any_cloud_server():
    # Reserve then close a port: real connection refusal, no patched networking.
    reserve = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
    port = reserve.sockets[0].getsockname()[1]
    reserve.close()
    await reserve.wait_closed()
    proxy = PurifierProxy(
        ProxyConfig(
            "127.0.0.1", 0, "127.0.0.1", cloud_host="127.0.0.1", cloud_port=port, retry_delay=0.05
        ),
        lambda: None,
    )
    device = FakePurifier()
    await proxy.start()
    await device.connect(proxy.server.sockets[0].getsockname()[1])
    try:
        await wait_for(lambda: proxy.available)
        await proxy.execute("power_off")
        assert not proxy.state.power and not proxy.cloud_connected
        await proxy.execute("auto")
        assert proxy.state.power and proxy.state.mode == "auto"
    finally:
        await device.close()
        await proxy.stop()


async def test_false_confirmation_and_timeout_are_reported_without_optimistic_state():
    async with system() as (proxy, device, cloud):
        device.apply = False
        with pytest.raises(ControlError, match="did not confirm"):
            await proxy.execute("fan_6")
        assert proxy.state.mode == "auto" and proxy.state.speed == 1
        device.respond = False
        with pytest.raises(ControlError, match="did not answer"):
            await proxy.execute("fan_3")


async def test_overflow_is_bounded_and_requests_cloud_reset():
    async with system(queue_bytes=100) as (proxy, device, cloud):
        session = proxy.session
        session._forward(b"x" * 101)
        assert session._outgoing.size == 0 and session._reset_cloud.is_set()
        await proxy.execute("fan_1")
        assert proxy.available
        await wait_for(lambda: len(cloud.connections) >= 2)


async def test_timed_out_local_query_collision_does_not_cancel_cloud_or_device():
    async with system() as (proxy, device, cloud):
        device.respond = False
        query_task = asyncio.create_task(proxy.session.read_state())
        await wait_for(lambda: bool(proxy.session._pending))
        seq = next(iter(proxy.session._pending))
        cloud_query = b"\x00\x08\x00\x04" + seq.to_bytes(2) + bytes(9)
        cloud.connections[-1].write(cloud_query)
        await cloud.connections[-1].drain()
        with pytest.raises(ControlError):
            await query_task
        await wait_for(lambda: cloud_query in device.frames)
        device.respond = True
        await proxy.execute("fan_2")
        assert proxy.available and proxy.cloud_connected


async def test_cloud_frame_waits_for_local_query_reply_without_being_rewritten():
    async with system(query_timeout=0.5) as (proxy, device, cloud):
        device.respond = False
        query_task = asyncio.create_task(proxy.session.read_state())
        await wait_for(lambda: bool(proxy.session._pending))
        seq = next(iter(proxy.session._pending))
        cloud_query = bytes.fromhex("000800041234250000019fd0e781af")
        cloud.connections[-1].write(cloud_query)
        await cloud.connections[-1].drain()
        await asyncio.sleep(0.05)
        assert cloud_query not in device.frames
        device.writer.write(report(sequence=seq))
        await device.writer.drain()
        assert (await query_task).mode == "auto"
        await wait_for(lambda: cloud_query in device.frames)


async def test_shutdown_releases_port_and_all_tasks():
    async with system() as (proxy, device, cloud):
        port = proxy.server.sockets[0].getsockname()[1]
        await proxy.stop()
        assert not proxy.available and not proxy._tasks
        replacement = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", port)
        replacement.close()
        await replacement.wait_closed()


async def test_replacement_device_connection_cannot_be_cleared_by_old_cleanup():
    async with system() as (proxy, device, cloud):
        other = FakePurifier()
        old = proxy.session
        await other.connect(proxy.server.sockets[0].getsockname()[1])
        try:
            await wait_for(lambda: proxy.session is not old and proxy.available)
            await proxy.execute("fan_5")
            assert other.speed == 5 and proxy.available
        finally:
            await other.close()


async def test_untrusted_peer_is_rejected_before_upstream_connect():
    proxy = PurifierProxy(ProxyConfig("127.0.0.1", 0, "127.0.0.2"), lambda: None)
    await proxy.start()
    reader, writer = await asyncio.open_connection(
        "127.0.0.1", proxy.server.sockets[0].getsockname()[1]
    )
    try:
        assert await asyncio.wait_for(reader.read(), 1) == b""
        assert proxy.session is None
    finally:
        writer.close()
        await writer.wait_closed()
        await proxy.stop()


async def test_startup_waits_for_device_report_before_injecting_any_local_bytes():
    cloud = FakeCloud()
    server = await asyncio.start_server(cloud.accept, "127.0.0.1", 0)
    proxy = PurifierProxy(
        ProxyConfig(
            "127.0.0.1",
            0,
            "127.0.0.1",
            cloud_host="127.0.0.1",
            cloud_port=server.sockets[0].getsockname()[1],
            query_timeout=0.1,
        ),
        lambda: None,
    )
    await proxy.start()
    reader, writer = await asyncio.open_connection(
        "127.0.0.1", proxy.server.sockets[0].getsockname()[1]
    )
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(reader.read(1), 0.15)
        registration = bytes.fromhex("005e000100010010000641492d363030") + bytes(85)
        startup = b"AT+CIPSENDRAW\r" + registration
        writer.write(startup)
        await writer.drain()
        await wait_for(lambda: bytes(cloud.received) == startup)
        assert proxy.session._registration == registration
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(reader.read(1), 0.15)
        writer.write(report(queried=False))
        await writer.drain()
        assert (await asyncio.wait_for(reader.readexactly(15), 1))[2:4] == b"\x00\x04"
    finally:
        writer.close()
        await writer.wait_closed()
        await proxy.stop()
        await cloud.close()
        server.close()
        await server.wait_closed()
