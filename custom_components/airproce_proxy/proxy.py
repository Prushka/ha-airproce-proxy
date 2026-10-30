"""Independent local control and bounded, bidirectional cloud forwarding."""

from __future__ import annotations

import asyncio
import logging
import secrets
import socket
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass

from .protocol import DeviceState, StateObserver, command, matches, query
from .recovery import answered_operation, recovery_reply, recovery_request
from .stream import ByteQueue, QueueFullError, WireFramer, response_sequence

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProxyConfig:
    """One listener per physical purifier; NAT may hide its original source IP."""

    listen_host: str
    listen_port: int
    allowed_peer: str
    cloud_host: str = "tcpaph.airproce.com"
    cloud_port: int = 8283
    connect_timeout: float = 5
    write_timeout: float = 3
    cloud_idle_timeout: float = 180
    fragment_timeout: float = 3
    query_timeout: float = 2
    poll_interval: float = 30
    stale_after: float = 150
    queue_bytes: int = 262144
    retry_delay: float = 2
    acknowledgement_timeout: float = 1


class ControlError(Exception):
    """The purifier did not confirm a requested local operation."""


async def _close(writer: asyncio.StreamWriter) -> None:
    writer.close()
    with suppress(Exception):
        async with asyncio.timeout(1):
            await writer.wait_closed()


class PurifierProxy:
    """Own a listener and publish only locally observed purifier state."""

    def __init__(self, config: ProxyConfig, changed: Callable[[], None]) -> None:
        self.config = config
        self.changed = changed
        self.state: DeviceState | None = None
        self.last_seen = 0.0
        self.session: DeviceSession | None = None
        self.server: asyncio.Server | None = None
        self._tasks: set[asyncio.Task] = set()
        self._closing = False
        # Retain only in RAM across device TCP reconnects, until integration unload.
        self._registration: bytes | None = None

    @property
    def available(self) -> bool:
        return (
            self.session is not None
            and not self.session.closed
            and self.state is not None
            and self.last_seen > 0
            and time.monotonic() - self.last_seen < self.config.stale_after
        )

    @property
    def cloud_connected(self) -> bool:
        return self.session is not None and self.session.cloud_connected

    async def start(self) -> None:
        self.server = await asyncio.start_server(
            self._accept,
            self.config.listen_host,
            self.config.listen_port,
            family=socket.AF_INET,
        )

    def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.create_task(self._connection(reader, writer))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _connection(self, reader, writer) -> None:
        peer = writer.get_extra_info("peername")
        if self._closing or not peer or peer[0] != self.config.allowed_peer:
            await _close(writer)
            return
        previous = self.session
        session = DeviceSession(self, reader, writer)
        self.session = session
        self.last_seen = 0
        self.changed()
        if previous:
            previous.stop()
        try:
            await session.run()
        except (OSError, TimeoutError, ConnectionError) as err:
            _LOGGER.debug("Purifier connection ended: %s", type(err).__name__)
        finally:
            if self.session is session:
                self.session = None
                self.changed()

    async def execute(self, name: str) -> None:
        session = self.session
        if session is None or session.closed:
            raise ControlError("The purifier is not connected to its local proxy")
        await session.execute(name)

    async def stop(self) -> None:
        self._closing = True
        server, self.server = self.server, None
        if server:
            server.close()
        for task in tuple(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if server:
            # Python 3.13+ waits for client transports too. Stop sessions first.
            server.close_clients()
            await server.wait_closed()
        self._tasks.clear()
        self.session = None
        self._registration = None


class DeviceSession:
    """A device connection survives upstream failure and reconnect attempts."""

    def __init__(self, owner, reader, writer) -> None:
        self.owner: PurifierProxy = owner
        self.config = owner.config
        self.reader = reader
        self.writer = writer
        self.closed = False
        self.cloud_connected = False
        self.cloud_registered = False
        self.cloud_bytes_received = 0
        self.cloud_bytes_sent = 0
        # Only the device's own observed registration. Never synthesize
        # credentials or persist this payload outside this integration's RAM.
        self._registration = owner._registration
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()
        self._reset_cloud = asyncio.Event()
        self._outgoing = ByteQueue(self.config.queue_bytes)
        self._write_lock = asyncio.Lock()
        self._transaction_lock = asyncio.Lock()
        self._control_lock = asyncio.Lock()
        self._query_lock = asyncio.Lock()
        self._pending: dict[int, asyncio.Future[DeviceState]] = {}
        self._owned: dict[int, float] = {}
        self._cloud_ids: dict[int, float] = {}
        # At most one pending acknowledgement per known operation (three total).
        self._acknowledgements: dict[int, tuple[float, bytes]] = {}
        self._acknowledgements_changed = asyncio.Event()
        self._sequence = 0xD000 + secrets.randbelow(0x3000)

    def stop(self) -> None:
        self.closed = True
        self._stop.set()

    async def run(self) -> None:
        tasks = [
            asyncio.create_task(fn())
            for fn in (
                self._device_reader,
                self._cloud_manager,
                self._poll,
                self._recover,
                self._stop.wait,
            )
        ]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            self.closed = True
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(ControlError("Purifier disconnected"))
            await _close(self.writer)

    def _allocate(self) -> int:
        now = time.monotonic()
        self._owned = {key: expiry for key, expiry in self._owned.items() if expiry > now}
        self._cloud_ids = {key: expiry for key, expiry in self._cloud_ids.items() if expiry > now}
        for _ in range(0x3000):
            self._sequence = 0xD000 + (self._sequence + 1 - 0xD000) % 0x3000
            if self._sequence not in self._owned and self._sequence not in self._cloud_ids:
                self._owned[self._sequence] = now + 180
                return self._sequence
        raise ControlError("No unused local request ID is available")

    async def _send(self, data: bytes) -> None:
        if self.closed:
            raise ControlError("Purifier disconnected")
        # Only complete cloud frames reach here. Local requests cannot split one.
        async with self._write_lock:
            try:
                async with asyncio.timeout(self.config.write_timeout):
                    self.writer.write(data)
                    await self.writer.drain()
            except (TimeoutError, OSError) as err:
                self.stop()
                raise ControlError("The purifier stopped accepting data") from err

    async def read_state(self) -> DeviceState:
        if not self._ready.is_set():
            raise ControlError("The purifier is still initializing its connection")
        async with self._query_lock, self._transaction_lock:
            seq = self._allocate()
            future = asyncio.get_running_loop().create_future()
            self._pending[seq] = future
            try:
                await self._send(query(seq))
                async with asyncio.timeout(self.config.query_timeout):
                    return await future
            except TimeoutError as err:
                raise ControlError("The purifier did not answer a local status query") from err
            finally:
                self._pending.pop(seq, None)
                future.cancel()

    async def execute(self, name: str) -> None:
        # No optimistic state, retransmission of toggles, or reliance on missing ACKs.
        async with self._control_lock:
            state = await self.read_state()
            if name in ("auto", "sleep") and not state.power:
                await self._apply("power_on", state)
                state = await self.read_state()
            await self._apply(name, state)

    async def _apply(self, name: str, state: DeviceState) -> None:
        frame = command(name, context_speed=state.raw_speed, sequence=self._allocate())
        async with self._transaction_lock:
            await self._send(frame)
        # Firmware changes can take several reports to settle. A fresh query must
        # confirm the requested target; unsolicited notifications are insufficient.
        for _ in range(3):
            await asyncio.sleep(0.4)
            try:
                current = await self.read_state()
            except ControlError:
                continue
            if matches(current, name):
                return
        raise ControlError(f"The purifier did not confirm {name}")

    async def _poll(self) -> None:
        # TCP accept can precede UART passthrough initialization. Wait for
        # validated device data before injecting local requests.
        await self._ready.wait()
        while not self.closed:
            try:
                await self.read_state()
            except ControlError:
                self.owner.changed()
            await asyncio.sleep(self.config.poll_interval)

    def _forward(self, data: bytes) -> None:
        if self._reset_cloud.is_set():
            return
        try:
            self._outgoing.put(data)
        except QueueFullError:
            self._outgoing.clear()
            self._reset_cloud.set()

    async def _recover(self) -> None:
        """Bound the firmware's wait for cloud startup/status acknowledgements."""
        while not self.closed:
            self._acknowledgements_changed.clear()
            if not self._acknowledgements:
                await self._acknowledgements_changed.wait()
                continue
            opcode = min(self._acknowledgements, key=lambda op: self._acknowledgements[op][0])
            deadline, _ = self._acknowledgements[opcode]
            delay = deadline - time.monotonic()
            if delay > 0:
                with suppress(TimeoutError):
                    async with asyncio.timeout(delay):
                        await self._acknowledgements_changed.wait()
                continue
            # The cloud may answer while we wait for a local query to finish.
            async with self._transaction_lock:
                if (pending := self._acknowledgements.pop(opcode, None)) is not None:
                    await self._send(recovery_reply(opcode, pending[1], int(time.time()) * 1000))

    async def _device_reader(self) -> None:
        observer, frames = StateObserver(), WireFramer(module_preamble=True)
        while not self.closed:
            try:
                async with asyncio.timeout(self.config.fragment_timeout if frames.buffer else None):
                    data = await self.reader.read(16384)
            except TimeoutError:
                # Preserve a device's malformed/truncated notification prefix.
                self._forward(frames.finish())
                continue
            if not data:
                self._forward(frames.finish())
                return
            for report in observer.feed(data):
                self._ready.set()
                if self.owner.session is self:
                    self.owner.state = report.state
                    self.owner.last_seen = time.monotonic()
                    self.owner.changed()
                pending = self._pending.get(report.sequence) if report.queried else None
                if pending is not None and not pending.done():
                    pending.set_result(report.state)
            for frame in frames.feed(data):
                if (request := recovery_request(frame)) is not None:
                    opcode, firmware = request
                    # On first attachment, let firmware finish its natural
                    # registration cycle. Acknowledging reports/retries before
                    # registration can prevent it ever identifying to the cloud.
                    if opcode == 1 or self._registration is not None:
                        self._acknowledgements.setdefault(
                            opcode,
                            (time.monotonic() + self.config.acknowledgement_timeout, firmware),
                        )
                        self._acknowledgements_changed.set()
                if (
                    40 <= len(frame) <= 4096
                    and frame[2:4] == b"\x00\x01"
                    and frame[7:10] == b"\x10\x00\x06"
                    and frame[10:16] in (b"AI-370", b"AI-600")
                ):
                    self._registration = frame
                    self.owner._registration = frame
                seq = response_sequence(frame)
                if seq is None or self._owned.get(seq, 0) <= time.monotonic():
                    self._forward(frame)

    async def _cloud_manager(self) -> None:
        first_attempt = self._registration is None
        while not self.closed:
            writer = None
            tasks = []
            self._reset_cloud.clear()
            try:
                async with asyncio.timeout(self.config.connect_timeout):
                    reader, writer = await asyncio.open_connection(
                        self.config.cloud_host,
                        self.config.cloud_port,
                        family=socket.AF_INET,
                    )
                self.cloud_connected = True
                self.owner.changed()
                registration = self._registration if not first_attempt else None
                if registration:
                    self._outgoing.discard_one(registration)
                tasks = [
                    asyncio.create_task(self._cloud_reader(reader)),
                    asyncio.create_task(self._cloud_writer(writer, registration)),
                    asyncio.create_task(self._reset_cloud.wait()),
                ]
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            except (OSError, TimeoutError, ConnectionError, ControlError) as err:
                _LOGGER.debug("Cloud relay reconnecting: %s", type(err).__name__)
            finally:
                first_attempt = False
                self.cloud_connected = False
                self.cloud_registered = False
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                if writer:
                    await _close(writer)
                self._outgoing.clear()
                self.owner.changed()
            await asyncio.sleep(self.config.retry_delay)

    async def _cloud_writer(self, writer, registration: bytes | None = None) -> None:
        if registration:
            async with asyncio.timeout(self.config.write_timeout):
                writer.write(registration)
                await writer.drain()
                self.cloud_bytes_sent += len(registration)
        while True:
            data = await self._outgoing.get()
            async with asyncio.timeout(self.config.write_timeout):
                writer.write(data)
                await writer.drain()
                self.cloud_bytes_sent += len(data)

    async def _cloud_reader(self, reader) -> None:
        frames = WireFramer()
        while True:
            timeout = (
                self.config.fragment_timeout if frames.buffer else self.config.cloud_idle_timeout
            )
            async with asyncio.timeout(timeout):
                data = await reader.read(16384)
            if not data:
                # A partial upstream command is never injected into the device stream.
                return
            self.cloud_bytes_received += len(data)
            for frame in frames.feed(data):
                if (opcode := answered_operation(frame)) is not None:
                    self._acknowledgements.pop(opcode, None)
                    self._acknowledgements_changed.set()
                if len(frame) >= 8 and frame[2:4] == b"\xff\xff":
                    self.cloud_registered = frame[7] == 200
                    self.owner.changed()
                if len(frame) >= 6:
                    seq = int.from_bytes(frame[4:6], "big")
                    self._cloud_ids[seq] = time.monotonic() + 180
                    # Never rewrite a cloud ID. Let an existing local query finish
                    # first, then return ownership of this ID to the cloud.
                    if (pending := self._pending.get(seq)) is not None:
                        # wait() does not propagate a local query's cancellation
                        # into the independent cloud reader.
                        await asyncio.wait({pending}, timeout=self.config.query_timeout)
                    self._owned.pop(seq, None)
                # These units share a UART parser between local requests and
                # cloud traffic. Let a bounded local query/reply finish before
                # forwarding the next cloud frame; never split or rewrite it.
                async with self._transaction_lock:
                    await self._send(frame)
