"""Narrow startup/keepalive replies when the cloud does not answer.

Only repeat the firmware version supplied by the device itself. These replies
contain no firmware image, download URL, provisioning data or user controls.
"""

from __future__ import annotations

import re

from .protocol import decode_state, payload_checksum

REPLY_OPS = {1: 0xFFFF, 0x103: 0xFEFD, 9: 0xFFF7}
_VERSION = re.compile(rb"AI-[0-9]+(?:\.[0-9]+){1,3}")


def _field(frame: bytes, offset: int) -> tuple[bytes, int] | None:
    if offset + 2 > len(frame):
        return None
    size = int.from_bytes(frame[offset : offset + 2], "big")
    end = offset + 2 + size
    if not 1 <= size <= 64 or end > len(frame):
        return None
    return frame[offset + 2 : end], end


def recovery_request(frame: bytes) -> tuple[int, bytes] | None:
    """Recognize only the observed complete request layouts, without credentials."""
    if len(frame) < 8 or int.from_bytes(frame[:2], "big") != len(frame) - 7:
        return None
    opcode = int.from_bytes(frame[2:4], "big")
    if opcode == 9:
        return (opcode, b"") if decode_state(frame) else None
    if opcode == 1:
        if frame[7:10] != b"\x10\x00\x06" or frame[10:16] not in (b"AI-370", b"AI-600"):
            return None
        offset = 24  # Model and the device timestamp precede three string fields.
        for _ in range(3):
            if (field := _field(frame, offset)) is None:
                return None
            firmware, offset = field
    elif opcode == 0x103:
        if frame[7:8] != b"\x10" or (field := _field(frame, 16)) is None:
            return None
        firmware, end = field
        if end != len(frame):
            return None
    else:
        return None
    if not _VERSION.fullmatch(firmware):
        return None
    return opcode, firmware


def recovery_reply(opcode: int, firmware: bytes, timestamp_ms: int) -> bytes:
    """Use the observed server ID 1 and freshly checksum the current timestamp."""
    stamp = timestamp_ms.to_bytes(8, "big")
    if opcode == 9:
        payload = b"\xc8" + stamp
    else:
        if not _VERSION.fullmatch(firmware):
            raise ValueError("An observed installed firmware version is required")
        payload = b"\xc8\x0a"
        if opcode == 0x103:
            payload += stamp + stamp
        payload += len(firmware).to_bytes(2, "big") + firmware
    return (
        len(payload).to_bytes(2, "big")
        + REPLY_OPS[opcode].to_bytes(2, "big")
        + b"\x00\x01"
        + bytes([payload_checksum(payload)])
        + payload
    )


def answered_operation(frame: bytes) -> int | None:
    """Only complete, checksummed cloud acknowledgements cancel a fallback."""
    if (
        len(frame) < 8
        or int.from_bytes(frame[:2], "big") != len(frame) - 7
        or payload_checksum(frame[7:]) != frame[6]
    ):
        return None
    opcode = int.from_bytes(frame[2:4], "big")
    return next((request for request, reply in REPLY_OPS.items() if opcode == reply), None)
