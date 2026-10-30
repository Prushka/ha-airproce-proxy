"""Bounded stream framing and queues shared by the two independent TCP paths."""

from __future__ import annotations

import asyncio
from collections import deque

from .protocol import CONTROL_REPLY, QUERY_REPLY, REPORT, decode_state

MAX_WIRE_FRAME = 65535 + 7
MODULE_PREAMBLE = b"AT+CIPSENDRAW\r"


class QueueFullError(ConnectionError):
    """A cloud session cannot keep up; local operation must not wait for it."""


class ByteQueue:
    """Bound by bytes, not by the number of potentially huge TCP chunks."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.size = 0
        self._items: deque[bytes] = deque()
        self._ready = asyncio.Event()

    def put(self, data: bytes) -> None:
        if not data:
            return
        if self.size + len(data) > self.limit:
            raise QueueFullError("Cloud forwarding buffer is full")
        self._items.append(data)
        self.size += len(data)
        self._ready.set()

    async def get(self) -> bytes:
        while not self._items:
            self._ready.clear()
            await self._ready.wait()
        item = self._items.popleft()
        self.size -= len(item)
        return item

    def clear(self) -> None:
        self._items.clear()
        self.size = 0
        self._ready.clear()

    def discard_one(self, data: bytes) -> None:
        """Remove a queued registration when that same frame is replayed first."""
        try:
            self._items.remove(data)
        except ValueError:
            return
        self.size -= len(data)
        if not self._items:
            self._ready.clear()


class WireFramer:
    """Partition the byte stream without discarding or rewriting any byte.

    The length word excludes the first seven bytes. Unknown opcodes remain
    opaque. A truncated *known state* frame can be followed by a new envelope
    on these firmwares; preserve the truncated prefix as raw bytes and resume
    at the validated state envelope instead of swallowing that next report.
    """

    def __init__(self, *, module_preamble: bool = False) -> None:
        self.buffer = bytearray()
        self.module_preamble = module_preamble

    def feed(self, data: bytes) -> list[bytes]:
        out = []
        for offset in range(0, len(data), MAX_WIRE_FRAME):
            self.buffer.extend(data[offset : offset + MAX_WIRE_FRAME])
            while len(self.buffer) >= 4:
                if self.module_preamble and self.buffer.startswith(MODULE_PREAMBLE):
                    out.append(bytes(self.buffer[: len(MODULE_PREAMBLE)]))
                    del self.buffer[: len(MODULE_PREAMBLE)]
                    continue
                if self.module_preamble and MODULE_PREAMBLE.startswith(self.buffer):
                    break
                size = int.from_bytes(self.buffer[:2], "big") + 7
                if size < 8:
                    out.append(bytes(self.buffer[:1]))
                    del self.buffer[:1]
                    continue
                if len(self.buffer) < size:
                    break
                frame = bytes(self.buffer[:size])
                if frame.startswith((REPORT, QUERY_REPLY)) and decode_state(frame) is None:
                    candidates = []
                    for marker, next_size in ((REPORT, 35), (QUERY_REPLY, 36)):
                        pos = self.buffer.find(marker, 1)
                        if pos >= 0:
                            if len(self.buffer) < pos + next_size:
                                # Wait only when a complete next report could establish resync.
                                if len(self.buffer) < size + 36:
                                    candidates.append((pos, False))
                            elif decode_state(bytes(self.buffer[pos : pos + next_size])):
                                candidates.append((pos, True))
                    if candidates:
                        pos, complete = min(candidates)
                        if not complete:
                            break
                        out.append(bytes(self.buffer[:pos]))
                        del self.buffer[:pos]
                        continue
                out.append(frame)
                del self.buffer[:size]
        return out

    def finish(self) -> bytes:
        data = bytes(self.buffer)
        self.buffer.clear()
        return data


def response_sequence(frame: bytes) -> int | None:
    """Identify replies to local requests, never unsolicited state notifications."""
    if len(frame) < 8:
        return None
    if frame[2:4] not in (QUERY_REPLY[2:4], CONTROL_REPLY[2:4]):
        return None
    if len(frame) != int.from_bytes(frame[:2], "big") + 7:
        return None
    return int.from_bytes(frame[4:6], "big")
