"""
TAP binary frame protocol definitions and encoders.
Matches src/tap/protocol.ts.
"""
from __future__ import annotations
import struct
from enum import IntEnum
from typing import Optional, NamedTuple

TAP_HEADER_SIZE = 12
MAX_PAYLOAD_SIZE = 1 * 1024 * 1024

class TapOrigin(IntEnum):
    GENERIC_TAP = 0x54415001  # "TAP\x01" - Standard TAP
    AUDIUM_CORE = 0x41554401  # "AUD\x01" - Official Audium Audio Engine
    TYPETUBE_CLI = 0x54544301  # "TTC\x01" - Official TypeTube Client
    TYPETUBE_TS = 0x54545301  # "TTS\x01" - Official TypeTube TypeScript Client
    TYPETUBE_PY = 0x54415001  # Uses Standard TAP for universal compatibility


class TapIntent(IntEnum):
    PING = 0x00
    NEGOTIATE = 0x01
    AUTH = 0x02
    GOAWAY = 0x07
    RPC_CALL = 0x10
    DISCONNECT = 0x7E
    ERROR = 0x7F


class TapFlags(IntEnum):
    REQUEST = 0x00
    RESPONSE = 0x01
    ERROR = 0x02
    COMPRESSED = 0x04
    ENCRYPTED = 0x08
    ACCEPT_COMPRESSED = 0x10


class TapHeader(NamedTuple):
    origin: int
    intent: int
    flags: int
    trace_id: int
    length: int


class TapFrame(NamedTuple):
    origin: int
    intent: int
    flags: int
    trace_id: int
    payload: bytes


def encode_frame(
    intent: int,
    trace_id: int,
    flags: int,
    payload: bytes = b"",
    origin: int = TapOrigin.TYPETUBE_PY
) -> bytes:
    if len(payload) > MAX_PAYLOAD_SIZE:
        raise ValueError(f"TAP frame payload exceeds maximum size ({len(payload)} > {MAX_PAYLOAD_SIZE})")
    
    header = struct.pack(
        ">IBBH I",
        origin,
        int(intent) & 0xFF,
        int(flags) & 0xFF,
        trace_id & 0xFFFF,
        len(payload)
    )
    return header + payload


def parse_header(buf: bytes, offset: int = 0) -> Optional[TapHeader]:
    if len(buf) - offset < TAP_HEADER_SIZE:
        return None
    origin, intent, flags, trace_id, length = struct.unpack_from(">IBBH I", buf, offset)
    if length > MAX_PAYLOAD_SIZE:
        raise ValueError(f"TAP payload size {length} exceeds safety cap of {MAX_PAYLOAD_SIZE} bytes")
    if (intent in (TapIntent.PING, TapIntent.NEGOTIATE, TapIntent.AUTH)) and length > 2048:
        raise ValueError(f"TAP handshake frame {intent} exceeds pre-allocation limit ({length} > 2048 bytes)")
    return TapHeader(origin, intent, flags, trace_id, length)


def get_frame_header_aad(origin: int, intent: int, flags: int, trace_id: int, length: int) -> bytes:
    return struct.pack(
        ">IBBH I",
        origin,
        int(intent) & 0xFF,
        int(flags) & 0xFF,
        trace_id & 0xFFFF,
        length
    )
