"""
Stream parser for incremental chunked TAP frames.
Matches src/tap/parser.ts.
"""
from __future__ import annotations
from typing import Optional
from .protocol import TAP_HEADER_SIZE, TapFrame, parse_header

class StreamParser:
    def __init__(self) -> None:
        self.buffer = bytearray()
        self.offset = 0

    def push(self, chunk: bytes) -> None:
        self.buffer.extend(chunk)

    def next_frame(self) -> Optional[TapFrame]:
        available = len(self.buffer) - self.offset
        if available < TAP_HEADER_SIZE:
            self._compact()
            return None

        header = parse_header(self.buffer, self.offset)
        if not header:
            return None

        frame_len = TAP_HEADER_SIZE + header.length
        if available < frame_len:
            self._compact()
            return None

        payload_start = self.offset + TAP_HEADER_SIZE
        payload_end = payload_start + header.length
        payload = bytes(self.buffer[payload_start:payload_end])

        self.offset += frame_len
        self._compact()

        return TapFrame(
            origin=header.origin,
            intent=header.intent,
            flags=header.flags,
            trace_id=header.trace_id,
            payload=payload
        )

    def _compact(self) -> None:
        if self.offset > 64 * 1024:
            del self.buffer[:self.offset]
            self.offset = 0

    def reset(self) -> None:
        self.buffer.clear()
        self.offset = 0
