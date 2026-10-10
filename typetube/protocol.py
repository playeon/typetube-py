"""
TypeTube Protocol Buffers serializer and deserializer in pure Python.
Matches src/protocol.ts wire format exactly.
"""
from __future__ import annotations
import struct
from typing import Any, List, Optional, Tuple, Dict

class ProtoWriter:
    def __init__(self) -> None:
        self.buf = bytearray()

    @property
    def length(self) -> int:
        return len(self.buf)

    def write_tag(self, field: int, wire: int) -> None:
        self.write_varint((field << 3) | wire)

    def write_varint(self, value: int) -> None:
        v = value & 0xFFFFFFFF
        while v >= 0x80:
            self.buf.append((v & 0x7F) | 0x80)
            v >>= 7
        self.buf.append(v)

    def write_string(self, field: int, s: Optional[str]) -> None:
        if not s:
            return
        utf8 = s.encode("utf-8")
        self.write_tag(field, 2)
        self.write_varint(len(utf8))
        self.buf.extend(utf8)

    def write_uint32(self, field: int, val: Optional[int]) -> None:
        if val is None or val == 0:
            return
        self.write_tag(field, 0)
        self.write_varint(val)

    def write_bool(self, field: int, val: Optional[bool]) -> None:
        if not val:
            return
        self.write_tag(field, 0)
        self.write_varint(1)

    def write_double(self, field: int, val: Optional[float]) -> None:
        if val is None or val == 0:
            return
        self.write_tag(field, 1)
        self.buf.extend(struct.pack("<d", float(val)))

    def write_message(self, field: int, writer: ProtoWriter) -> None:
        b = bytes(writer.buf)
        if not b:
            return
        self.write_tag(field, 2)
        self.write_varint(len(b))
        self.buf.extend(b)

    def to_bytes(self) -> bytes:
        return bytes(self.buf)


class ProtoReader:
    def __init__(self, data: bytes) -> None:
        self.buf = data
        self.pos = 0

    @property
    def has_more(self) -> bool:
        return self.pos < len(self.buf)

    def read_tag(self) -> Tuple[int, int]:
        tag = self.read_varint()
        return tag >> 3, tag & 0x07

    def read_varint(self) -> int:
        res = 0
        shift = 0
        while True:
            if self.pos >= len(self.buf):
                return res
            b = self.buf[self.pos]
            self.pos += 1
            res |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        return res

    def read_string(self) -> str:
        length = self.read_varint()
        data = self.buf[self.pos : self.pos + length]
        self.pos += length
        return data.decode("utf-8", errors="replace")

    def read_double(self) -> float:
        val = struct.unpack("<d", self.buf[self.pos : self.pos + 8])[0]
        self.pos += 8
        return val

    def read_bytes(self) -> bytes:
        length = self.read_varint()
        data = self.buf[self.pos : self.pos + length]
        self.pos += length
        return data

    def skip(self, wire: int) -> None:
        if wire == 0:
            self.read_varint()
        elif wire == 1:
            self.pos += 8
        elif wire == 2:
            length = self.read_varint()
            self.pos += length
        elif wire == 5:
            self.pos += 4


def _read_thumbnail(buf: bytes) -> Dict[str, Any]:
    r = ProtoReader(buf)
    thumb: Dict[str, Any] = {}
    while r.has_more:
        field, wire = r.read_tag()
        if field == 1:
            thumb["url"] = r.read_string()
        elif field == 2:
            thumb["width"] = r.read_varint()
        elif field == 3:
            thumb["height"] = r.read_varint()
        else:
            r.skip(wire)
    return thumb


def _read_audio_stream(buf: bytes) -> Dict[str, Any]:
    r = ProtoReader(buf)
    stream: Dict[str, Any] = {"isHiFi": False}
    while r.has_more:
        field, wire = r.read_tag()
        if field == 1:
            stream["itag"] = r.read_varint()
        elif field == 2:
            stream["quality"] = r.read_string()
        elif field == 3:
            stream["mimeType"] = r.read_string()
        elif field == 4:
            stream["bitrate"] = r.read_varint()
        elif field == 5:
            stream["url"] = r.read_string()
        elif field == 6:
            stream["isHiFi"] = (r.read_varint() == 1)
        elif field == 7:
            stream["rawUrl"] = r.read_string()
        else:
            r.skip(wire)
    return stream


def _read_video_stream(buf: bytes) -> Dict[str, Any]:
    r = ProtoReader(buf)
    stream: Dict[str, Any] = {}
    while r.has_more:
        field, wire = r.read_tag()
        if field == 1:
            stream["itag"] = r.read_varint()
        elif field == 2:
            stream["quality"] = r.read_string()
        elif field == 3:
            stream["resolution"] = r.read_string()
        elif field == 4:
            stream["mimeType"] = r.read_string()
        elif field == 5:
            stream["url"] = r.read_string()
        else:
            r.skip(wire)
    return stream


def _read_meta(buf: bytes) -> Dict[str, Any]:
    r = ProtoReader(buf)
    meta: Dict[str, Any] = {}
    while r.has_more:
        field, wire = r.read_tag()
        if field == 1:
            meta["latencyMs"] = r.read_varint() if wire == 0 else round(r.read_double(), 2)
        elif field == 2:
            meta["timestamp"] = r.read_double()
        elif field == 3:
            meta["total"] = r.read_varint()
        elif field == 4:
            meta["limit"] = r.read_varint()
        elif field == 5:
            meta["sLatencyMS"] = r.read_varint() if wire == 0 else round(r.read_double(), 2)
        elif field == 6:
            meta["eLatencyMS"] = r.read_varint() if wire == 0 else round(r.read_double(), 2)
        elif field == 7:
            meta["tLatencyMS"] = r.read_varint() if wire == 0 else round(r.read_double(), 2)
        else:
            r.skip(wire)
    return meta


def _read_error(buf: bytes) -> Dict[str, Any]:
    r = ProtoReader(buf)
    err: Dict[str, Any] = {}
    while r.has_more:
        field, wire = r.read_tag()
        if field == 1:
            err["code"] = r.read_string()
        elif field == 2:
            err["message"] = r.read_string()
        elif field == 3:
            err["statusCode"] = r.read_varint()
        else:
            r.skip(wire)
    return err


def _read_track_data(buf: bytes) -> Dict[str, Any]:
    r = ProtoReader(buf)
    track: Dict[str, Any] = {
        "thumbnails": [],
        "audioStreams": [],
        "videoStreams": []
    }
    while r.has_more:
        field, wire = r.read_tag()
        if field == 1:
            track["id"] = r.read_string()
            track["query"] = track["id"]
        elif field == 2:
            track["title"] = r.read_string()
        elif field == 3:
            track["author"] = r.read_string()
        elif field == 4:
            track["uploader"] = r.read_string()
        elif field == 5:
            track["artistAvatar"] = r.read_string()
        elif field == 6:
            track["durationSeconds"] = r.read_varint()
        elif field == 7:
            track["thumbnail"] = r.read_string()
        elif field == 8:
            track["thumbnails"].append(_read_thumbnail(r.read_bytes()))
        elif field == 9:
            track["bestAudio"] = _read_audio_stream(r.read_bytes())
        elif field == 10:
            track["bestVideo"] = _read_video_stream(r.read_bytes())
        elif field == 11:
            track["audioStreams"].append(_read_audio_stream(r.read_bytes()))
        elif field == 12:
            track["videoStreams"].append(_read_video_stream(r.read_bytes()))
        else:
            r.skip(wire)
    return track


def decode_track_result(buf: bytes) -> Dict[str, Any]:
    r = ProtoReader(buf)
    envelope: Dict[str, Any] = {"success": False}
    while r.has_more:
        field, wire = r.read_tag()
        if field == 1:
            envelope["success"] = (r.read_varint() == 1)
        elif field == 2:
            envelope["data"] = _read_track_data(r.read_bytes())
        elif field == 3:
            envelope["meta"] = _read_meta(r.read_bytes())
        elif field == 4:
            envelope["error"] = _read_error(r.read_bytes())
        else:
            r.skip(wire)
    return envelope


def decode_search_results(buf: bytes) -> Dict[str, Any]:
    r = ProtoReader(buf)
    envelope: Dict[str, Any] = {"success": False, "data": []}
    while r.has_more:
        field, wire = r.read_tag()
        if field == 1:
            envelope["success"] = (r.read_varint() == 1)
        elif field == 2:
            item_buf = r.read_bytes()
            ir = ProtoReader(item_buf)
            item: Dict[str, Any] = {"duration": None, "uploader": None}
            while ir.has_more:
                ifield, iwire = ir.read_tag()
                if ifield == 1:
                    item["id"] = ir.read_string()
                elif ifield == 2:
                    item["title"] = ir.read_string()
                elif ifield == 3:
                    item["url"] = ir.read_string()
                elif ifield == 4:
                    item["duration"] = ir.read_varint()
                elif ifield == 5:
                    item["uploader"] = ir.read_string()
                else:
                    ir.skip(iwire)
            envelope["data"].append(item)
        elif field == 3:
            envelope["meta"] = _read_meta(r.read_bytes())
        elif field == 4:
            envelope["error"] = _read_error(r.read_bytes())
        else:
            r.skip(wire)
    return envelope
