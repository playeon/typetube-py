import struct
from typing import List, Any
from .types import TrackResult, AudioStream, VideoStream, Thumbnail, SearchItem

class ProtoReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.length = len(data)

    @property
    def has_more(self) -> bool:
        return self.pos < self.length

    def read_varint(self) -> int:
        res = 0
        shift = 0
        while self.pos < self.length:
            b = self.data[self.pos]
            self.pos += 1
            res |= (b & 0x7F) << shift
            if (b & 0x80) == 0:
                return res
            shift += 7
        return res

    def read_tag(self):
        v = self.read_varint()
        return v >> 3, v & 0x7

    def read_string(self) -> str:
        length = self.read_varint()
        sub = self.data[self.pos:self.pos + length]
        self.pos += length
        return sub.decode("utf-8", errors="replace")

    def read_double(self) -> float:
        val = struct.unpack("<d", self.data[self.pos:self.pos + 8])[0]
        self.pos += 8
        return val

    def read_bytes(self) -> bytes:
        length = self.read_varint()
        sub = self.data[self.pos:self.pos + length]
        self.pos += length
        return sub

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

def read_thumbnail(data: bytes) -> Thumbnail:
    r = ProtoReader(data)
    url = ""
    width = None
    height = None
    while r.has_more:
        field, wire = r.read_tag()
        if field == 1:
            url = r.read_string()
        elif field == 2:
            width = r.read_varint()
        elif field == 3:
            height = r.read_varint()
        else:
            r.skip(wire)
    return Thumbnail(url=url, width=width, height=height)

def read_audio_stream(data: bytes) -> AudioStream:
    r = ProtoReader(data)
    itag = 0
    quality = ""
    mime_type = ""
    bitrate = 0
    url = ""
    is_hifi = False
    raw_url = None
    while r.has_more:
        field, wire = r.read_tag()
        if field == 1:
            itag = r.read_varint()
        elif field == 2:
            quality = r.read_string()
        elif field == 3:
            mime_type = r.read_string()
        elif field == 4:
            bitrate = r.read_varint()
        elif field == 5:
            url = r.read_string()
        elif field == 6:
            is_hifi = r.read_varint() == 1
        elif field == 7:
            raw_url = r.read_string()
        else:
            r.skip(wire)
    return AudioStream(
        itag=itag,
        quality=quality,
        mime_type=mime_type,
        bitrate=bitrate,
        url=url,
        is_hifi=is_hifi,
        raw_url=raw_url
    )

def read_video_stream(data: bytes) -> VideoStream:
    r = ProtoReader(data)
    itag = 0
    quality = ""
    resolution = None
    mime_type = ""
    url = ""
    while r.has_more:
        field, wire = r.read_tag()
        if field == 1:
            itag = r.read_varint()
        elif field == 2:
            quality = r.read_string()
        elif field == 3:
            resolution = r.read_string()
        elif field == 4:
            mime_type = r.read_string()
        elif field == 5:
            url = r.read_string()
        else:
            r.skip(wire)
    return VideoStream(
        itag=itag,
        quality=quality,
        resolution=resolution,
        mime_type=mime_type,
        url=url
    )

def decode_track_result(data: bytes) -> TrackResult:
    r = ProtoReader(data)
    success = False
    query = ""
    video_id = ""
    title = ""
    author = ""
    uploader = None
    artist_avatar = None
    duration_seconds = 0
    thumbnail = ""
    thumbnails: List[Thumbnail] = []
    latency_ms = 0.0
    best_audio = None
    best_video = None
    audio_streams: List[AudioStream] = []
    video_streams: List[VideoStream] = []

    while r.has_more:
        field, wire = r.read_tag()
        if field == 1:
            success = r.read_varint() == 1
        elif field == 2:
            query = r.read_string()
        elif field == 3:
            video_id = r.read_string()
        elif field == 4:
            title = r.read_string()
        elif field == 5:
            author = r.read_string()
        elif field == 6:
            uploader = r.read_string()
        elif field == 7:
            artist_avatar = r.read_string()
        elif field == 8:
            duration_seconds = r.read_varint()
        elif field == 9:
            thumbnail = r.read_string()
        elif field == 10:
            thumbnails.append(read_thumbnail(r.read_bytes()))
        elif field == 11:
            latency_ms = r.read_double()
        elif field == 12:
            best_audio = read_audio_stream(r.read_bytes())
        elif field == 13:
            best_video = read_video_stream(r.read_bytes())
        elif field == 14:
            audio_streams.append(read_audio_stream(r.read_bytes()))
        elif field == 15:
            video_streams.append(read_video_stream(r.read_bytes()))
        else:
            r.skip(wire)

    return TrackResult(
        success=success,
        query=query,
        id=video_id,
        title=title,
        author=author,
        uploader=uploader,
        artist_avatar=artist_avatar,
        duration_seconds=duration_seconds,
        thumbnail=thumbnail,
        thumbnails=thumbnails,
        latency_ms=latency_ms,
        best_audio=best_audio,
        best_video=best_video,
        audio_streams=audio_streams,
        video_streams=video_streams
    )

def decode_search_results(data: bytes) -> List[SearchItem]:
    r = ProtoReader(data)
    items: List[SearchItem] = []
    while r.has_more:
        field, wire = r.read_tag()
        if field == 2:
            item_data = r.read_bytes()
            ir = ProtoReader(item_data)
            item_id = ""
            title = ""
            url = ""
            duration = None
            uploader = None
            while ir.has_more:
                ifield, iwire = ir.read_tag()
                if ifield == 1:
                    item_id = ir.read_string()
                elif ifield == 2:
                    title = ir.read_string()
                elif ifield == 3:
                    url = ir.read_string()
                elif ifield == 4:
                    duration = ir.read_varint()
                elif ifield == 5:
                    uploader = ir.read_string()
                else:
                    ir.skip(iwire)
            items.append(SearchItem(id=item_id, title=title, url=url, duration=duration, uploader=uploader))
        else:
            r.skip(wire)
    return items
