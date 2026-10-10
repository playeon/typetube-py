"""
Data classes and types matching types.ts.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable

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
    resolution: str
    mime_type: str
    url: str


@dataclass
class Thumbnail:
    url: str
    width: Optional[int] = None
    height: Optional[int] = None


@dataclass
class TrackResult:
    success: bool
    query: str
    id: str
    title: str
    author: str
    uploader: str
    artist_avatar: Optional[str]
    duration_seconds: int
    thumbnail: Optional[str]
    thumbnails: List[Thumbnail] = field(default_factory=list)
    latency_ms: float = 0.0
    meta: Dict[str, Any] = field(default_factory=dict)
    best_audio: Optional[AudioStream] = None
    best_video: Optional[VideoStream] = None
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
class DownloadProgress:
    phase: str
    percent: float
    downloaded_bytes: int
    total_bytes: int
    speed_mbps: float


@dataclass
class DownloadResult:
    file_path: str
    file_name: str
    file_size_bytes: int
    duration_seconds: int
    duration_ms: float
    average_speed_mbps: float
