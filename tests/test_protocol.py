"""Regression cases from actual AI-370/AI-600 packets, with identity fields removed."""

import struct

import pytest

from custom_components.airproce_proxy.protocol import (
    COMMANDS,
    StateObserver,
    command,
    decode_state,
    query,
)
from custom_components.airproce_proxy.stream import ByteQueue, QueueFullError, WireFramer


def report(*, sequence=1, speed=1, mode=2, queried=True, pm25=7):
    tail = struct.pack("!HHHHHHBBBBI", pm25, 33, 245, 654, 15, 0, speed, mode, 1, 4, 65542)
    if queried:
        return struct.pack("!HHHHQ", 29, 0xFFFC, sequence, 200, 123456) + tail
    return struct.pack("!HHHBQ", 28, 9, sequence, 0, 123456) + tail


def test_real_device_reports():
    for raw, pm25, temp, humidity in (
        (
            "001dfffce10100c800000000000000000017002100f30274000b00000102011000010000",
            23,
            24.3,
            62.8,
        ),
        ("001dfffc0b9700c800000000000000000007002100f5028f001000000102010400010006", 7, 24.5, 65.5),
    ):
        state = decode_state(bytes.fromhex(raw))
        assert state is not None
        assert (state.pm25, state.temperature, state.humidity) == (pm25, temp, humidity)
        assert state.mode == "auto" and state.power and state.speed == 1


def test_observer_resynchronizes_after_real_truncated_notification():
    good = report()
    broken_prefix = bytes.fromhex("001c00090b9f0000000000000000000000")
    wire = broken_prefix + good + report(queried=False)
    for cut in range(len(wire) + 1):
        observer = StateObserver()
        states = observer.feed(wire[:cut]) + observer.feed(wire[cut:])
        assert len(states) == 2
        assert all(state.state.mode == "auto" for state in states)
        assert not observer.buffer


def test_lossless_framing_unknown_messages_and_every_fragmentation():
    unknown = struct.pack("!HHHBQ", 400, 0x1234, 7, 0, 1) + bytes(392)
    assert len(unknown) == 407
    wire = unknown + report() + report(queried=False)
    for cut in range(len(wire) + 1):
        parser = WireFramer()
        frames = parser.feed(wire[:cut]) + parser.feed(wire[cut:])
        assert b"".join(frames) + parser.finish() == wire
        assert frames == [unknown, report(), report(queried=False)]


def test_lossless_resync_preserves_malformed_prefix():
    prefix = bytes.fromhex("001c00090b9f0000000000000000000000")
    wire = prefix + report()
    for cut in range(len(wire) + 1):
        parser = WireFramer()
        frames = parser.feed(wire[:cut]) + parser.feed(wire[cut:])
        assert b"".join(frames) + parser.finish() == wire
        assert frames[-1] == report()


def test_commands_and_correlation_have_bounded_supported_surface():
    assert len(COMMANDS) == 10
    for name in COMMANDS:
        frame = command(name, context_speed=2)
        assert len(frame) == 23
    assert command("auto", context_speed=2)[15:17] == b"\x02\x02"
    assert command("sleep", context_speed=2)[15:17] == b"\x02\x20"
    assert query(0xE101)[4:6] == b"\xe1\x01"
    for unsupported in ("reset_filter", "factory_reset", "fan_7"):
        with pytest.raises(ValueError):
            command(unsupported)
    for bad in (None, True, 0, 7):
        with pytest.raises(ValueError):
            command("auto", context_speed=bad)


async def test_cloud_queue_never_blocks_producer_and_accounts_for_bytes():
    queue = ByteQueue(8)
    queue.put(b"12345678")
    with pytest.raises(QueueFullError):
        queue.put(b"9")
    assert await queue.get() == b"12345678"
    assert queue.size == 0
    queue.put(b"other")
    queue.clear()
    assert queue.size == 0


def test_module_startup_text_is_preserved_without_hiding_registration():
    preamble = b"AT+CIPSENDRAW\r"
    registration = bytes.fromhex("005e000100010010000641492d363030") + bytes(85)
    wire = preamble + registration + report()
    for cut in range(len(wire) + 1):
        parser = WireFramer(module_preamble=True)
        frames = parser.feed(wire[:cut]) + parser.feed(wire[cut:])
        assert frames == [preamble, registration, report()]
        assert not parser.buffer
