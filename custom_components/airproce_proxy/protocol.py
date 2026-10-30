"""Observed AI-370/AI-600 wire protocol, without cloud account APIs.

State layout and captured command templates adapted from jackjinke/ha-airproce
and Griddz/home-assistant-airproce-bridge (MIT). See THIRD_PARTY_NOTICES.
Unrecognized bytes are never rewritten by the observation parser.
"""

from __future__ import annotations

from dataclasses import dataclass

STATUS_QUERY = bytes.fromhex("000800040b97250000019fd0e781af")
COMMANDS = {
    "fan_1": bytes.fromhex("001000070ba41e0000019fd0e9bdee0101011300000000"),
    "fan_2": bytes.fromhex("001000070b917c0000019fd0e7229a0201011300000000"),
    "fan_3": bytes.fromhex("001000070b939f0000019fd0e74b870301011300000000"),
    "fan_4": bytes.fromhex("001000070b96950000019fd0e780f30401011300000000"),
    "fan_5": bytes.fromhex("001000070baf590000019fd0ea5bea0501011300000000"),
    "fan_6": bytes.fromhex("001000070b9bb00000019fd0e7f3e40601011300000000"),
    "auto": bytes.fromhex("001000070b9e280000019fd0e85cdf0602011300000000"),
    "sleep": bytes.fromhex("001000070ba11d0000019fd0e8dd200620011300000000"),
    "power_off": bytes.fromhex("001000070ba8c10000019fd0e9f1a60110011300000000"),
    "power_on": bytes.fromhex("001000070bab270000019fd0ea20920100011300000000"),
}
REPORT = b"\x00\x1c\x00\x09"
QUERY_REPLY = b"\x00\x1d\xff\xfc"
CONTROL_REPLY = b"\x00\x09\xff\xf9"
MAX_FRAME = 4096


@dataclass(frozen=True, slots=True)
class DeviceState:
    """Only fields corroborated by the existing decoder and live device reports."""

    power: bool
    mode: str
    speed: int
    pm25: int
    temperature: float
    humidity: float
    voc: float
    raw_speed: int
    raw_mode: int


@dataclass(frozen=True, slots=True)
class StateReport:
    state: DeviceState
    sequence: int
    queried: bool
    frame: bytes


def decode_state(frame: bytes) -> DeviceState | None:
    """Validate a complete known envelope before interpreting its sensor tail."""
    if not (
        (len(frame) == 35 and frame.startswith(REPORT))
        or (len(frame) == 36 and frame.startswith(QUERY_REPLY))
    ):
        return None
    if frame.startswith(QUERY_REPLY) and frame[6:8] != b"\x00\xc8":
        return None
    tail = frame[-20:]
    pm25 = int.from_bytes(tail[:2], "big")
    temperature = int.from_bytes(tail[4:6], "big") / 10
    humidity = int.from_bytes(tail[6:8], "big") / 10
    voc = int.from_bytes(tail[8:10], "big") / 1000
    if pm25 > 5000 or temperature > 100 or humidity > 100:
        return None
    raw_speed, raw_mode = tail[12:14]
    speed = raw_speed if 1 <= raw_speed <= 6 else 0
    if raw_speed == 255 and raw_mode in (17, 18):
        mode, power = "off", False
    elif raw_mode == 2:
        mode, power = "auto", True
    elif raw_mode in (32, 33, 34):
        mode, power = "sleep", True
    elif raw_mode == 1 and speed:
        mode, power = "manual", True
    else:
        return None
    return DeviceState(power, mode, speed, pm25, temperature, humidity, voc, raw_speed, raw_mode)


class StateObserver:
    """Read reports without controlling or modifying the forwarded byte stream.

    These devices sometimes emit a truncated notification before a full frame.
    An invalid candidate advances by one byte, so it cannot consume a following
    complete report. Fragmentation and coalescing are both normal TCP behavior.
    """

    def __init__(self) -> None:
        self.buffer = bytearray()

    def feed(self, data: bytes) -> list[StateReport]:
        reports = []
        for offset in range(0, len(data), MAX_FRAME):
            self.buffer.extend(data[offset : offset + MAX_FRAME])
            while len(self.buffer) >= 4:
                positions = [
                    p for marker in (REPORT, QUERY_REPLY) if (p := self.buffer.find(marker)) >= 0
                ]
                if not positions:
                    del self.buffer[:-3]
                    break
                del self.buffer[: min(positions)]
                size = self.buffer[1] + 7
                if len(self.buffer) < size:
                    break
                frame = bytes(self.buffer[:size])
                state = decode_state(frame)
                if state is None:
                    del self.buffer[0]
                    continue
                reports.append(
                    StateReport(
                        state,
                        int.from_bytes(frame[4:6], "big"),
                        frame.startswith(QUERY_REPLY),
                        frame,
                    )
                )
                del self.buffer[:size]
        return reports


def query(sequence: int) -> bytes:
    """Use a private correlation ID; changing it was verified on the AI-600."""
    if not 0 <= sequence <= 65535:
        raise ValueError("Sequence must fit in two bytes")
    return STATUS_QUERY[:4] + sequence.to_bytes(2, "big") + STATUS_QUERY[6:]


def command(name: str, *, context_speed: int | None = None, sequence: int | None = None) -> bytes:
    """Build only captured controls; presets preserve the CURRENT speed context."""
    if name not in COMMANDS:
        raise ValueError(f"Unsupported control: {name}")
    frame = COMMANDS[name]
    if name in ("auto", "sleep"):
        if type(context_speed) is not int or not 1 <= context_speed <= 6:
            raise ValueError("A current hardware speed from 1 to 6 is required")
        frame = frame[:15] + bytes([context_speed]) + frame[16:]
    if sequence is not None:
        if not 0 <= sequence <= 65535:
            raise ValueError("Sequence must fit in two bytes")
        frame = frame[:4] + sequence.to_bytes(2, "big") + frame[6:]
    return frame


def matches(state: DeviceState, name: str) -> bool:
    """A command succeeds only after a fresh query reports the intended state."""
    if name.startswith("fan_") and name in COMMANDS:
        return state.power and state.mode == "manual" and state.speed == int(name[-1])
    if name in ("auto", "sleep"):
        return state.power and state.mode == name
    if name == "power_on":
        return state.power
    if name == "power_off":
        return not state.power
    return False
