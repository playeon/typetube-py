from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

class TypeTubeError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code

@dataclass
class Thumbnail:
    url: str
    width: Optional[int] = None
    height: Optional[int] = None

@dataclass
class AudioStream:
    itag: int
    quality: str
    mime_type: str
    bitrate: int
    url: str
    is_hifi: bool = False
    raw_url: Optional[str] = None

@dataclass
class VideoStream:
    itag: int
    quality: str
    mime_type: str
    url: str
    resolution: Optional[str] = None

@dataclass
class TrackResult:
    success: bool
    query: str
    id: str
    title: str
    author: str
    duration_seconds: int
    thumbnail: str
    latency_ms: float
    best_audio: AudioStream
    uploader: Optional[str] = None
    artist_avatar: Optional[str] = None
    best_video: Optional[VideoStream] = None
    thumbnails: List[Thumbnail] = field(default_factory=list)
    audio_streams: List[AudioStream] = field(default_factory=list)
    video_streams: List[VideoStream] = field(default_factory=list)

@dataclass
class SearchItem:
    id: str
    title: str
    url: str
    duration: Optional[int] = None
    uploader: Optional[str] = None

@dataclass
class UsageInfo:
    success: bool
    key_type: str
    limit: int
    used: int
    remaining: int
    reset_in_seconds: int
    window_seconds: int
    daily_limit: int
    daily_used: int
    daily_remaining: int
    daily_reset_in_seconds: int

    @property
    def tier(self) -> str:
        return self.key_type

    @property
    def resolve_limit(self) -> int:
        return self.limit

    @property
    def resolve_remaining(self) -> int:
        return self.remaining

    @property
    def reset_seconds(self) -> int:
        return self.reset_in_seconds

@dataclass
class DownloadResult:
    success: bool
    file_path: str
    file_name: str
    size_bytes: int
    file_size_mb: float
    duration_sec: float
    speed_mbps: float
    id: str
    title: str
    author: str
    duration_seconds: int
    track: TrackResult

    @property
    def path(self) -> str:
        return self.file_path

    @property
    def bytes_written(self) -> int:
        return self.size_bytes

    @property
    def average_speed_mbps(self) -> float:
        return self.speed_mbps
