import os
import time
import json
import urllib.parse
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Callable, Dict, Any, Union

from .types import (
    TrackResult,
    SearchItem,
    UsageInfo,
    DownloadResult,
    AudioStream,
    VideoStream,
    TypeTubeError
)
from .protocol import decode_track_result, decode_search_results

DEFAULT_HOST = "https://typetube.xysushi.in"
DEFAULT_TIMEOUT = 10.0

class TypeTubeClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        host: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
        format: str = "protobuf",
        endpoint: Optional[str] = None
    ):
        self.api_key = api_key or "public"
        chosen_host = endpoint or host or DEFAULT_HOST
        self.host = chosen_host.rstrip("/")
        self.timeout = timeout
        self.format = format
        self.api_calls_count = 0

    def usage(self) -> UsageInfo:
        url = f"{self.host}/v1/usage"
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "X-API-Key": self.api_key
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
                return UsageInfo(
                    success=data.get("success", False),
                    key_type=data.get("keyType", "public"),
                    limit=data.get("limit", 0),
                    used=data.get("used", 0),
                    remaining=data.get("remaining", 0),
                    reset_in_seconds=data.get("resetInSeconds", 0),
                    window_seconds=data.get("windowSeconds", 60),
                    daily_limit=data.get("dailyLimit", 0),
                    daily_used=data.get("dailyUsed", 0),
                    daily_remaining=data.get("dailyRemaining", 0),
                    daily_reset_in_seconds=data.get("dailyResetInSeconds", 0)
                )
        except urllib.error.HTTPError as e:
            err_msg = "Request failed"
            try:
                body = json.loads(e.read().decode("utf-8"))
                err_msg = body.get("error", err_msg)
            except Exception:
                pass
            if e.code == 401 and (self.api_key == "public" or "public" in err_msg.lower()):
                err_msg = "No public API key is available."
            raise TypeTubeError(err_msg, status_code=e.code)
        except Exception as e:
            raise TypeTubeError(str(e))

    def resolve(self, query: str, timeout: Optional[float] = None) -> TrackResult:
        query = query.strip()
        if not query:
          raise TypeTubeError("Query cannot be empty")

        url = f"{self.host}/v1/resolve?q={urllib.parse.quote(query)}"
        headers: Dict[str, str] = {
            "Accept": "application/x-protobuf" if self.format == "protobuf" else "application/json",
            "X-API-Key": self.api_key
        }

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as response:
                self.api_calls_count += 1
                content_type = response.headers.get("content-type", "")
                raw_bytes = response.read()

                if "application/x-protobuf" in content_type or "application/octet-stream" in content_type:
                    return decode_track_result(raw_bytes)

                data = json.loads(raw_bytes.decode("utf-8"))
                return self._parse_track_json(data)
        except urllib.error.HTTPError as e:
            err_msg = "Request failed"
            try:
                body = json.loads(e.read().decode("utf-8"))
                err_msg = body.get("error", err_msg)
            except Exception:
                pass
            if e.code == 401 and (self.api_key == "public" or "public" in err_msg.lower()):
                err_msg = "No public API key is available."
            raise TypeTubeError(err_msg, status_code=e.code)
        except Exception as e:
            if isinstance(e, TypeTubeError):
                raise e
            raise TypeTubeError(str(e))

    def search(self, query: str, limit: int = 5, timeout: Optional[float] = None) -> List[SearchItem]:
        query = query.strip()
        if not query:
            return []

        url = f"{self.host}/v1/search?q={urllib.parse.quote(query)}&limit={limit}"
        headers: Dict[str, str] = {
            "Accept": "application/x-protobuf" if self.format == "protobuf" else "application/json",
            "X-API-Key": self.api_key
        }

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as response:
                content_type = response.headers.get("content-type", "")
                raw_bytes = response.read()

                if "application/x-protobuf" in content_type or "application/octet-stream" in content_type:
                    return decode_search_results(raw_bytes)

                data = json.loads(raw_bytes.decode("utf-8"))
                items = []
                for item in data.get("results", []):
                    items.append(SearchItem(
                        id=item.get("id", ""),
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        duration=item.get("durationSeconds"),
                        uploader=item.get("author") or item.get("uploader")
                    ))
                return items
        except urllib.error.HTTPError as e:
            err_msg = "Search failed"
            try:
                body = json.loads(e.read().decode("utf-8"))
                err_msg = body.get("error", err_msg)
            except Exception:
                pass
            if e.code == 401 and (self.api_key == "public" or "public" in err_msg.lower()):
                err_msg = "No public API key is available."
            raise TypeTubeError(err_msg, status_code=e.code)
        except Exception as e:
            if isinstance(e, TypeTubeError):
                raise e
            raise TypeTubeError(str(e))

    def download_audio(
        self,
        target: Union[str, TrackResult],
        dest: str = "./",
        workers: int = 4,
        chunk_size_mb: int = 10,
        quality: str = "highest",
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        output_path: Optional[str] = None,
        chunk_size: Optional[int] = None
    ) -> DownloadResult:
        if isinstance(target, TrackResult):
            track = target
        else:
            track = self.resolve(str(target))

        stream = self._select_audio_stream(track, quality)
        if not stream or not stream.url:
            raise TypeTubeError("No playable audio stream available")

        final_dest = output_path or dest
        if os.path.isdir(final_dest) or not os.path.splitext(final_dest)[1]:
            os.makedirs(final_dest, exist_ok=True)
            safe_title = "".join(c for c in f"{track.author} - {track.title}" if c.isalnum() or c in " ._-").strip()
            ext = "m4a" if "mp4" in stream.mime_type else "opus"
            final_dest = os.path.join(final_dest, f"{safe_title}.{ext}")
        else:
            parent = os.path.dirname(final_dest)
            if parent:
                os.makedirs(parent, exist_ok=True)

        effective_chunk_bytes = chunk_size if chunk_size is not None else chunk_size_mb * 1024 * 1024
        t0 = time.time()
        size_bytes = self._download_range_parallel(stream.url, final_dest, workers, effective_chunk_bytes, progress_callback)
        duration_sec = round(time.time() - t0, 2)
        speed_mbps = round((size_bytes / (1024 * 1024)) / max(duration_sec, 0.01), 2)
        file_size_mb = round(size_bytes / (1024 * 1024), 2)

        return DownloadResult(
            success=True,
            file_path=final_dest,
            file_name=os.path.basename(final_dest),
            size_bytes=size_bytes,
            file_size_mb=file_size_mb,
            duration_sec=duration_sec,
            speed_mbps=speed_mbps,
            id=track.id,
            title=track.title,
            author=track.author,
            duration_seconds=track.duration_seconds,
            track=track
        )

    def _select_audio_stream(self, track: TrackResult, quality: str) -> AudioStream:
        streams = track.audio_streams
        if not streams:
            return track.best_audio

        if quality in ("hifi", "256kbps", "highest"):
            hifi = next((s for s in streams if s.itag in (141, 774)), None)
            if hifi:
                return hifi

        if quality == "128kbps":
            std = next((s for s in streams if s.itag in (140, 251)), None)
            if std:
                return std

        return track.best_audio or streams[0]

    def _download_range_parallel(
        self,
        url: str,
        dest_path: str,
        workers: int,
        chunk_size_bytes: int,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]]
    ) -> int:
        req = urllib.request.Request(url, headers={"Range": "bytes=0-0", "User-Agent": "Mozilla/5.0"})
        total_bytes = 0
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                cr = resp.headers.get("Content-Range", "")
                if "/" in cr:
                    total_bytes = int(cr.split("/")[1])
        except Exception:
            pass

        if total_bytes <= 0:
            return self._download_linear(url, dest_path, progress_callback)

        chunk_size = max(64 * 1024, chunk_size_bytes)
        chunks = []
        for start in range(0, total_bytes, chunk_size):
            end = min(start + chunk_size - 1, total_bytes - 1)
            chunks.append((start, end))

        fd = os.open(dest_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
        downloaded = 0
        t0 = time.time()

        def fetch_chunk(start: int, end: int) -> int:
            nonlocal downloaded
            r = urllib.request.Request(url, headers={
                "Range": f"bytes={start}-{end}",
                "User-Agent": "Mozilla/5.0"
            })
            with urllib.request.urlopen(r, timeout=15.0) as resp:
                data = resp.read()
                os.pwrite(fd, data, start)
                downloaded += len(data)
                if progress_callback:
                    sec = max(time.time() - t0, 0.01)
                    pct = round((downloaded / total_bytes) * 100, 1)
                    speed = round((downloaded / (1024 * 1024)) / sec, 2)
                    progress_callback({
                        "downloaded_bytes": downloaded,
                        "total_bytes": total_bytes,
                        "percent": pct,
                        "speed_mbps": speed
                    })
                return len(data)

        try:
            with ThreadPoolExecutor(max_workers=min(workers, 32)) as pool:
                futures = [pool.submit(fetch_chunk, start, end) for start, end in chunks]
                for f in as_completed(futures):
                    f.result()
        finally:
            os.close(fd)

        return downloaded

    def _download_linear(
        self,
        url: str,
        dest_path: str,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]]
    ) -> int:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Range": "bytes=0-"
        })
        downloaded = 0
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=15.0) as resp, open(dest_path, "wb") as f:
            total_bytes = int(resp.headers.get("Content-Length", 0))
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total_bytes > 0:
                    sec = max(time.time() - t0, 0.01)
                    pct = round((downloaded / total_bytes) * 100, 1)
                    speed = round((downloaded / (1024 * 1024)) / sec, 2)
                    progress_callback({
                        "downloaded_bytes": downloaded,
                        "total_bytes": total_bytes,
                        "percent": pct,
                        "speed_mbps": speed
                    })
        return downloaded

    def _parse_track_json(self, data: Dict[str, Any]) -> TrackResult:
        best_a = data.get("bestAudio", {})
        best_audio = AudioStream(
            itag=best_a.get("itag", 0),
            quality=best_a.get("quality", ""),
            mime_type=best_a.get("mimeType", ""),
            bitrate=best_a.get("bitrate", 0),
            url=best_a.get("url", ""),
            is_hifi=best_a.get("isHiFi", False),
            raw_url=best_a.get("rawUrl")
        )
        best_v = data.get("bestVideo")
        best_video = None
        if best_v:
            best_video = VideoStream(
                itag=best_v.get("itag", 0),
                quality=best_v.get("quality", ""),
                mime_type=best_v.get("mimeType", ""),
                url=best_v.get("url", ""),
                resolution=best_v.get("resolution")
            )
        return TrackResult(
            success=data.get("success", False),
            query=data.get("query", ""),
            id=data.get("id", ""),
            title=data.get("title", ""),
            author=data.get("author", ""),
            uploader=data.get("uploader"),
            artist_avatar=data.get("artistAvatar"),
            duration_seconds=data.get("durationSeconds", 0),
            thumbnail=data.get("thumbnail", ""),
            latency_ms=data.get("latencyMs", 0.0),
            best_audio=best_audio,
            best_video=best_video
        )

def create_client(
    api_key: Optional[str] = None,
    host: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
    format: str = "protobuf",
    endpoint: Optional[str] = None
) -> TypeTubeClient:
    return TypeTubeClient(api_key=api_key, host=host, timeout=timeout, format=format, endpoint=endpoint)
