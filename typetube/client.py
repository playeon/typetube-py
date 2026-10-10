"""
TypeTube client library for Python.
Provides both AsyncTypeTube (asynchronous) and TypeTube (synchronous) interfaces.
Includes multi-worker parallel range downloads, IPv4/IPv6 socket binding, and FFmpeg video muxing.
"""
from __future__ import annotations
import asyncio
import http.client
import os
import re
import socket
import subprocess
import time
import urllib.parse
from typing import Optional, List, Dict, Any, Callable, Union

from .tap.client import TapClient
from .tap.protocol import TapOrigin
from .protocol import decode_track_result, decode_search_results
from .types import (
    TrackResult,
    AudioStream,
    VideoStream,
    Thumbnail,
    SearchItem,
    DownloadProgress,
    DownloadResult,
)


class TypeTubeError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class IPv4HTTPConnection(http.client.HTTPConnection):
    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect((self.host, self.port))


class IPv4HTTPSConnection(http.client.HTTPSConnection):
    def connect(self) -> None:
        raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_sock.settimeout(self.timeout)
        raw_sock.connect((self.host, self.port))
        server_hostname = self.host if not self._tunnel_host else self._tunnel_host
        self.sock = self._context.wrap_socket(raw_sock, server_hostname=server_hostname)


def get_ip_family(url: str) -> int:
    try:
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        ip_val = params.get("ip", [""])[0]
        if ":" in ip_val:
            return 6
        return 4
    except Exception:
        return 4


class AsyncTypeTube:
    def __init__(
        self,
        api_key: Optional[str] = None,
        host: Optional[str] = None,
        port: int = 8443,
        timeout_ms: int = 15000,
        encrypted: Optional[bool] = None,
        server_identity_key: Optional[Union[bytes, str]] = None,
        socket_path: Optional[str] = None,
        psk: Optional[str] = None
    ) -> None:
        target = host or "sg.clusters.typetube.xyz"
        self.api_calls_count = 0
        self.tap_client = TapClient(
            target=target,
            port=port,
            auth_key=api_key,
            origin=TapOrigin.TYPETUBE_PY,
            encrypted=encrypted,
            server_identity_key=server_identity_key,
            timeout_ms=timeout_ms,
            auto_retry=True,
            socket_path=socket_path,
            psk=psk
        )

    async def resolve(self, query_or_url: str, max_video_height: Optional[int] = None) -> TrackResult:
        self.api_calls_count += 1
        raw_payload = query_or_url.strip().encode("utf-8")
        res_buffer = await self.tap_client.invoke("resolve", raw_payload)
        envelope = decode_track_result(res_buffer)

        if not envelope.get("success"):
            err = envelope.get("error") or {"message": "Failed to resolve track", "code": "UNKNOWN_ERROR"}
            raise TypeTubeError(f"[TypeTube Error {err.get('code', 500)}]: {err.get('message')}", 500)

        data = envelope.get("data") or {}
        meta = envelope.get("meta") or {}

        def _to_audio(a: Optional[dict]) -> Optional[AudioStream]:
            if not a:
                return None
            return AudioStream(
                itag=a.get("itag", 0),
                quality=a.get("quality", ""),
                mime_type=a.get("mimeType", ""),
                bitrate=a.get("bitrate", 0),
                url=a.get("url", ""),
                is_hifi=a.get("isHiFi", False),
                raw_url=a.get("rawUrl")
            )

        def _to_video(v: Optional[dict]) -> Optional[VideoStream]:
            if not v:
                return None
            return VideoStream(
                itag=v.get("itag", 0),
                quality=v.get("quality", ""),
                resolution=v.get("resolution", ""),
                mime_type=v.get("mimeType", ""),
                url=v.get("url", "")
            )

        def _to_thumb(t: dict) -> Thumbnail:
            return Thumbnail(
                url=t.get("url", ""),
                width=t.get("width"),
                height=t.get("height")
            )

        audio_streams = [_to_audio(a) for a in data.get("audioStreams", []) if a]
        video_streams = [_to_video(v) for v in data.get("videoStreams", []) if v]
        thumbnails = [_to_thumb(t) for t in data.get("thumbnails", []) if t]

        best_audio = _to_audio(data.get("bestAudio"))
        best_video = _to_video(data.get("bestVideo"))

        if max_video_height and best_video:
            filtered = self._filter_video_by_height(video_streams, max_video_height)
            if filtered:
                best_video = filtered

        return TrackResult(
            success=True,
            query=data.get("query") or data.get("id", ""),
            id=data.get("id", ""),
            title=data.get("title", ""),
            author=data.get("author", ""),
            uploader=data.get("uploader") or data.get("author", ""),
            artist_avatar=data.get("artistAvatar"),
            duration_seconds=data.get("durationSeconds", 0),
            thumbnail=data.get("thumbnail"),
            thumbnails=thumbnails,
            latency_ms=meta.get("latencyMs", 0.0),
            meta=meta,
            best_audio=best_audio,
            best_video=best_video,
            audio_streams=audio_streams,
            video_streams=video_streams
        )

    async def search(self, query: str, limit: int = 10) -> List[SearchItem]:
        self.api_calls_count += 1
        import json
        payload = json.dumps({"q": query.strip(), "limit": limit}).encode("utf-8")
        res_buffer = await self.tap_client.invoke("search", payload)
        envelope = decode_search_results(res_buffer)

        if not envelope.get("success"):
            err = envelope.get("error") or {"message": "Search failed", "code": "SEARCH_ERROR"}
            raise TypeTubeError(f"[TypeTube Error {err.get('code', 500)}]: {err.get('message')}", 500)

        items = []
        for item in envelope.get("data", []):
            items.append(
                SearchItem(
                    id=item.get("id", ""),
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    duration=item.get("duration"),
                    uploader=item.get("uploader")
                )
            )
        return items

    async def ping(self) -> float:
        return await self.tap_client.ping()

    def _filter_video_by_height(self, streams: List[VideoStream], max_height: int) -> Optional[VideoStream]:
        def parse_h(q: str) -> int:
            m = re.match(r"^(\d+)p", q or "")
            return int(m.group(1)) if m else 0

        candidates = [v for v in streams if parse_h(v.quality) <= max_height]
        return candidates[0] if candidates else (streams[0] if streams else None)

    def _resolve_destination(self, dest_path: str, track: TrackResult, ext: str) -> str:
        target = dest_path.strip()
        is_dir = (
            not os.path.splitext(target)[1]
            or (os.path.exists(target) and os.path.isdir(target))
            or target.endswith("/")
            or target.endswith("\\")
        )
        if is_dir:
            author = (track.author or "").strip()
            title = (track.title or track.id).strip()
            name = f"{author} - {title}" if author and not title.lower().startswith(author.lower()) else title
            safe_name = re.sub(r'[\\/:*?"<>|]', '_', name)[:120]
            return os.path.join(target, f"{safe_name}.{ext}")
        return target

    def _select_audio_stream(
        self,
        streams: List[AudioStream],
        best: Optional[AudioStream],
        preference: Optional[str]
    ) -> Optional[AudioStream]:
        if not streams:
            return best
        non_gcr = [s for s in streams if "gcr=" not in s.url]
        pool = non_gcr if non_gcr else streams

        if preference in ("hifi", "256kbps"):
            hifi = next((s for s in pool if s.itag in (141, 774)), None)
            if hifi:
                return hifi
        if preference == "128kbps":
            std = next((s for s in pool if s.itag in (140, 251)), None)
            if std:
                return std
        if preference == "lowest":
            return sorted(pool, key=lambda s: s.bitrate or 0)[0]
        return pool[0] if pool else best

    def _select_video_stream(
        self,
        streams: List[VideoStream],
        best: Optional[VideoStream],
        quality_preference: Optional[str],
        codec_preference: Optional[str]
    ) -> Optional[VideoStream]:
        if not streams:
            return best
        pool = list(streams)
        if codec_preference and codec_preference != "any":
            filtered = [s for s in pool if codec_preference.lower() in s.mime_type.lower()]
            if filtered:
                pool = filtered

        def parse_h(q: str) -> int:
            m = re.match(r"^(\d+)p", q or "")
            return int(m.group(1)) if m else (int(q) if q and q.isdigit() else 0)

        if quality_preference and quality_preference not in ("highest", "lowest"):
            target_h = parse_h(quality_preference)
            if target_h > 0:
                exact = next((s for s in pool if parse_h(s.quality) == target_h), None)
                if exact:
                    return exact
                leq = [s for s in pool if parse_h(s.quality) <= target_h]
                if leq:
                    return leq[0]

        if quality_preference == "lowest":
            return sorted(pool, key=lambda s: parse_h(s.quality))[0]

        return pool[0] if pool else best

    async def download_audio(
        self,
        track_or_query: Union[TrackResult, str],
        dest_path: str = "./downloads",
        audio_quality: Optional[str] = None,
        workers: int = 4,
        chunk_size_bytes: Optional[int] = None,
        on_progress: Optional[Callable[[DownloadProgress], None]] = None
    ) -> DownloadResult:
        track = await self._ensure_fresh_track(track_or_query)
        stream = self._select_audio_stream(track.audio_streams, track.best_audio, audio_quality)
        if not stream or not stream.url:
            raise TypeTubeError("No playable audio stream found for download")

        ext = "m4a" if ("mp4" in stream.mime_type or "m4a" in stream.mime_type) else "webm"
        final_dest = self._resolve_destination(dest_path, track, ext)
        os.makedirs(os.path.dirname(os.path.abspath(final_dest)), exist_ok=True)

        t0 = time.perf_counter()
        bytes_downloaded = await self._download_chunked_range(
            stream.url,
            final_dest,
            workers=workers,
            chunk_size_bytes=chunk_size_bytes,
            on_progress=on_progress
        )
        duration_sec = time.perf_counter() - t0
        speed_mbps = (bytes_downloaded / (1024 * 1024)) / duration_sec if duration_sec > 0 else 0.0

        return DownloadResult(
            file_path=final_dest,
            file_name=os.path.basename(final_dest),
            file_size_bytes=bytes_downloaded,
            duration_seconds=int(duration_sec),
            duration_ms=duration_sec * 1000.0,
            average_speed_mbps=speed_mbps
        )

    async def download_video(
        self,
        track_or_query: Union[TrackResult, str],
        dest_path: str = "./downloads",
        quality: Optional[str] = "1080p",
        prefer_codec: Optional[str] = "avc1",
        workers: int = 6,
        chunk_size_bytes: Optional[int] = None,
        on_progress: Optional[Callable[[DownloadProgress], None]] = None
    ) -> DownloadResult:
        track = await self._ensure_fresh_track(track_or_query)
        v_stream = self._select_video_stream(track.video_streams, track.best_video, quality, prefer_codec)
        if not v_stream or not v_stream.url:
            raise TypeTubeError("No playable video stream found for video download")

        ext = "mp4" if "mp4" in v_stream.mime_type else "webm"
        final_dest = self._resolve_destination(dest_path, track, ext)
        os.makedirs(os.path.dirname(os.path.abspath(final_dest)), exist_ok=True)

        t0 = time.perf_counter()
        bytes_downloaded = await self._download_chunked_range(
            v_stream.url,
            final_dest,
            workers=workers,
            chunk_size_bytes=chunk_size_bytes,
            on_progress=on_progress
        )
        duration_sec = time.perf_counter() - t0
        speed_mbps = (bytes_downloaded / (1024 * 1024)) / duration_sec if duration_sec > 0 else 0.0

        return DownloadResult(
            file_path=final_dest,
            file_name=os.path.basename(final_dest),
            file_size_bytes=bytes_downloaded,
            duration_seconds=int(duration_sec),
            duration_ms=duration_sec * 1000.0,
            average_speed_mbps=speed_mbps
        )

    async def download_media(
        self,
        track_or_query: Union[TrackResult, str],
        dest_path: str = "./downloads",
        quality: Optional[str] = "1080p",
        audio_quality: Optional[str] = "highest",
        prefer_codec: Optional[str] = "avc1",
        output_format: str = "mp4",
        workers: int = 6,
        ffmpeg_bin: str = "ffmpeg",
        on_progress: Optional[Callable[[DownloadProgress], None]] = None
    ) -> DownloadResult:
        track = await self._ensure_fresh_track(track_or_query)
        v_stream = self._select_video_stream(track.video_streams, track.best_video, quality, prefer_codec)
        a_stream = self._select_audio_stream(track.audio_streams, track.best_audio, audio_quality)

        if not v_stream or not v_stream.url:
            raise TypeTubeError("No playable video stream found for media download")
        if not a_stream or not a_stream.url:
            raise TypeTubeError("No playable audio stream found for media download")

        final_dest = self._resolve_destination(dest_path, track, output_format)
        os.makedirs(os.path.dirname(os.path.abspath(final_dest)), exist_ok=True)

        temp_v = f"{final_dest}.tmp.{int(time.time() * 1000)}.v"
        temp_a = f"{final_dest}.tmp.{int(time.time() * 1000)}.a"

        v_downloaded = 0
        a_downloaded = 0
        v_total = 0
        a_total = 0

        def on_v_prog(p: DownloadProgress) -> None:
            nonlocal v_downloaded, v_total
            v_downloaded = p.downloaded_bytes
            v_total = p.total_bytes
            _notify_combined()

        def on_a_prog(p: DownloadProgress) -> None:
            nonlocal a_downloaded, a_total
            a_downloaded = p.downloaded_bytes
            a_total = p.total_bytes
            _notify_combined()

        def _notify_combined() -> None:
            if not on_progress:
                return
            tot = (v_total + a_total) if (v_total > 0 and a_total > 0) else 0
            curr = v_downloaded + a_downloaded
            pct = round((curr / tot) * 100, 1) if tot > 0 else 0.0
            on_progress(DownloadProgress(
                phase="downloading",
                percent=pct,
                downloaded_bytes=curr,
                total_bytes=tot,
                speed_mbps=0.0
            ))

        t0 = time.perf_counter()
        try:
            await asyncio.gather(
                self._download_chunked_range(v_stream.url, temp_v, workers=workers, on_progress=on_v_prog),
                self._download_chunked_range(a_stream.url, temp_a, workers=workers, on_progress=on_a_prog)
            )

            if on_progress:
                on_progress(DownloadProgress(
                    phase="muxing",
                    percent=100.0,
                    downloaded_bytes=v_downloaded + a_downloaded,
                    total_bytes=v_total + a_total,
                    speed_mbps=0.0
                ))

            # Mux streams with FFmpeg
            args = [
                ffmpeg_bin,
                "-y",
                "-i", temp_v,
                "-i", temp_a,
                "-c:v", "copy",
                "-c:a", "copy",
                "-movflags", "+faststart",
                final_dest
            ]
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(None, lambda: subprocess.run(args, capture_output=True))
            if res.returncode != 0:
                raise TypeTubeError(f"FFmpeg muxing failed: {res.stderr.decode('utf-8', errors='replace')[-300:]}")

            duration_sec = time.perf_counter() - t0
            stat = os.stat(final_dest)
            speed_mbps = (stat.st_size / (1024 * 1024)) / duration_sec if duration_sec > 0 else 0.0

            if on_progress:
                on_progress(DownloadProgress(
                    phase="complete",
                    percent=100.0,
                    downloaded_bytes=stat.st_size,
                    total_bytes=stat.st_size,
                    speed_mbps=speed_mbps
                ))

            return DownloadResult(
                file_path=final_dest,
                file_name=os.path.basename(final_dest),
                file_size_bytes=stat.st_size,
                duration_seconds=int(duration_sec),
                duration_ms=duration_sec * 1000.0,
                average_speed_mbps=speed_mbps
            )
        finally:
            if os.path.exists(temp_v):
                os.remove(temp_v)
            if os.path.exists(temp_a):
                os.remove(temp_a)

    async def _ensure_fresh_track(self, track_or_query: Union[TrackResult, str]) -> TrackResult:
        if isinstance(track_or_query, str):
            return await self.resolve(track_or_query)
        if hasattr(track_or_query, "best_audio") and track_or_query.best_audio:
            if self.is_stream_expired(track_or_query.best_audio.url):
                q = f"https://www.youtube.com/watch?v={track_or_query.id}" if track_or_query.id else track_or_query.title
                return await self.resolve(q)
            return track_or_query
        return track_or_query

    def is_stream_expired(self, url: str, margin_seconds: int = 30) -> bool:
        if not url:
            return True
        try:
            parsed = urllib.parse.urlparse(url)
            expire_str = urllib.parse.parse_qs(parsed.query).get("expire", [""])[0]
            if not expire_str:
                return False
            expire_ts = int(expire_str)
            now_ts = int(time.time())
            return (expire_ts - now_ts) < margin_seconds
        except Exception:
            return False

    async def _download_chunked_range(
        self,
        url: str,
        dest_path: str,
        workers: int = 4,
        chunk_size_bytes: Optional[int] = None,
        on_progress: Optional[Callable[[DownloadProgress], None]] = None
    ) -> int:
        total_bytes, effective_url = await self._probe_content_length(url)
        if not total_bytes or total_bytes <= 0:
            return await self._download_linear(url, dest_path, on_progress)

        chunk_size = max(512 * 1024, chunk_size_bytes or (10 * 1024 * 1024))
        num_workers = max(1, min(32, workers))

        chunks: List[tuple[int, int]] = []
        for start in range(0, total_bytes, chunk_size):
            end = min(start + chunk_size - 1, total_bytes - 1)
            chunks.append((start, end))

        queue: asyncio.Queue[tuple[int, int]] = asyncio.Queue()
        for ch in chunks:
            queue.put_nowait(ch)

        downloaded_bytes = 0
        t0 = time.perf_counter()
        lock = asyncio.Lock()

        fd = os.open(dest_path, os.O_RDWR | os.O_CREAT | os.O_TRUNC, 0o644)

        async def worker() -> None:
            nonlocal downloaded_bytes
            while not queue.empty():
                try:
                    start, end = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                chunk_data = await self._fetch_range_chunk(effective_url, start, end)

                async with lock:
                    os.lseek(fd, start, os.SEEK_SET)
                    os.write(fd, chunk_data)
                    downloaded_bytes += len(chunk_data)

                    if on_progress:
                        elapsed = time.perf_counter() - t0
                        speed = (downloaded_bytes / (1024 * 1024)) / elapsed if elapsed > 0 else 0.0
                        pct = round((downloaded_bytes / total_bytes) * 100, 1)
                        on_progress(DownloadProgress(
                            phase="downloading",
                            percent=pct,
                            downloaded_bytes=downloaded_bytes,
                            total_bytes=total_bytes,
                            speed_mbps=speed
                        ))
                queue.task_done()

        try:
            tasks = [asyncio.create_task(worker()) for _ in range(num_workers)]
            await asyncio.gather(*tasks)
            return downloaded_bytes
        finally:
            os.close(fd)

    async def _probe_content_length(self, url: str) -> tuple[Optional[int], str]:
        def _sync_probe() -> tuple[Optional[int], str]:
            curr_url = url
            family = get_ip_family(curr_url)
            for _ in range(5):
                parsed = urllib.parse.urlparse(curr_url)
                host = parsed.hostname or ""
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                path = parsed.path + ("?" + parsed.query if parsed.query else "")

                headers = {
                    "Range": "bytes=0-0",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128.0.0.0",
                    "Host": host
                }

                conn_cls = IPv4HTTPSConnection if (family == 4 and parsed.scheme == "https") else (
                    IPv4HTTPConnection if (family == 4 and parsed.scheme == "http") else (
                        http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
                    )
                )

                try:
                    conn = conn_cls(host, port, timeout=10)
                    conn.request("GET", path, headers=headers)
                    resp = conn.getresponse()
                    resp.read()
                    loc = resp.getheader("Location")
                    if resp.status in (301, 302, 303, 307, 308) and loc:
                        curr_url = urllib.parse.urljoin(curr_url, loc)
                        conn.close()
                        continue
                    if resp.status == 403:
                        raise TypeTubeError(
                            "Stream download forbidden (HTTP 403): track restricted to the cluster's region",
                            403
                        )
                    cr = resp.getheader("Content-Range")
                    if cr and "/" in cr:
                        return int(cr.split("/")[-1]), curr_url
                except TypeTubeError:
                    raise
                except Exception:
                    return None, curr_url
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
                break
            return None, curr_url

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _sync_probe)

    async def _fetch_range_chunk(self, url: str, start: int, end: int) -> bytes:
        def _sync_fetch() -> bytes:
            curr_url = url
            family = get_ip_family(curr_url)
            for _ in range(5):
                parsed = urllib.parse.urlparse(curr_url)
                host = parsed.hostname or ""
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                path = parsed.path + ("?" + parsed.query if parsed.query else "")

                headers = {
                    "Range": f"bytes={start}-{end}",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128.0.0.0",
                    "Host": host
                }

                conn_cls = IPv4HTTPSConnection if (family == 4 and parsed.scheme == "https") else (
                    IPv4HTTPConnection if (family == 4 and parsed.scheme == "http") else (
                        http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
                    )
                )

                conn = conn_cls(host, port, timeout=60)
                try:
                    conn.request("GET", path, headers=headers)
                    resp = conn.getresponse()
                    loc = resp.getheader("Location")
                    if resp.status in (301, 302, 303, 307, 308) and loc:
                        curr_url = urllib.parse.urljoin(curr_url, loc)
                        conn.close()
                        continue
                    if resp.status == 403:
                        raise TypeTubeError(
                            "Stream download forbidden (HTTP 403): track restricted to the cluster's region",
                            403
                        )
                    if resp.status not in (200, 206):
                        raise TypeTubeError(f"Range chunk failed with status {resp.status}", resp.status)
                    return resp.read()
                finally:
                    try:
                        conn.close()
                    except Exception:
                        pass
            raise TypeTubeError("Too many redirects during chunk fetch")

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _sync_fetch)

    async def _download_linear(
        self,
        url: str,
        dest_path: str,
        on_progress: Optional[Callable[[DownloadProgress], None]]
    ) -> int:
        def _sync_linear() -> int:
            family = get_ip_family(url)
            parsed = urllib.parse.urlparse(url)
            host = parsed.hostname or ""
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            path = parsed.path + ("?" + parsed.query if parsed.query else "")

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128.0.0.0",
                "Host": host
            }

            conn_cls = IPv4HTTPSConnection if (family == 4 and parsed.scheme == "https") else (
                IPv4HTTPConnection if (family == 4 and parsed.scheme == "http") else (
                    http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
                )
            )

            conn = conn_cls(host, port, timeout=60)
            downloaded = 0
            t0 = time.perf_counter()
            try:
                conn.request("GET", path, headers=headers)
                resp = conn.getresponse()
                if resp.status == 403:
                    raise TypeTubeError(
                        "Stream download forbidden (HTTP 403): track restricted to the cluster's region",
                        403
                    )
                if resp.status not in (200, 206):
                    raise TypeTubeError(f"Download stream failed with status {resp.status}", resp.status)
                total = int(resp.getheader("Content-Length", 0))
                with open(dest_path, "wb") as f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if on_progress:
                            elapsed = time.perf_counter() - t0
                            speed = (downloaded / (1024 * 1024)) / elapsed if elapsed > 0 else 0.0
                            pct = round((downloaded / total) * 100, 1) if total > 0 else 0.0
                            on_progress(DownloadProgress(
                                phase="downloading",
                                percent=pct,
                                downloaded_bytes=downloaded,
                                total_bytes=total,
                                speed_mbps=speed
                            ))
                return downloaded
            finally:
                conn.close()

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _sync_linear)

    def close(self) -> None:
        self.tap_client.close()


class TypeTube:
    """
    Synchronous wrapper for scripting environments.
    """
    def __init__(
        self,
        api_key: Optional[str] = None,
        host: Optional[str] = None,
        port: int = 8443,
        timeout_ms: int = 15000,
        encrypted: Optional[bool] = None,
        server_identity_key: Optional[Union[bytes, str]] = None,
        socket_path: Optional[str] = None,
        psk: Optional[str] = None
    ) -> None:
        self._async_client = AsyncTypeTube(
            api_key=api_key,
            host=host,
            port=port,
            timeout_ms=timeout_ms,
            encrypted=encrypted,
            server_identity_key=server_identity_key,
            socket_path=socket_path,
            psk=psk
        )

    def _run(self, coro):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import nest_asyncio
                nest_asyncio.apply()
                return loop.run_until_complete(coro)
            return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)

    def resolve(self, query_or_url: str, max_video_height: Optional[int] = None) -> TrackResult:
        return self._run(self._async_client.resolve(query_or_url, max_video_height))

    def search(self, query: str, limit: int = 10) -> List[SearchItem]:
        return self._run(self._async_client.search(query, limit))

    def ping(self) -> float:
        return self._run(self._async_client.ping())

    def download_audio(
        self,
        track_or_query: Union[TrackResult, str],
        dest_path: str = "./downloads",
        audio_quality: Optional[str] = None,
        workers: int = 4,
        chunk_size_bytes: Optional[int] = None,
        on_progress: Optional[Callable[[DownloadProgress], None]] = None
    ) -> DownloadResult:
        return self._run(self._async_client.download_audio(
            track_or_query,
            dest_path=dest_path,
            audio_quality=audio_quality,
            workers=workers,
            chunk_size_bytes=chunk_size_bytes,
            on_progress=on_progress
        ))

    def download_video(
        self,
        track_or_query: Union[TrackResult, str],
        dest_path: str = "./downloads",
        quality: Optional[str] = "1080p",
        prefer_codec: Optional[str] = "avc1",
        workers: int = 6,
        chunk_size_bytes: Optional[int] = None,
        on_progress: Optional[Callable[[DownloadProgress], None]] = None
    ) -> DownloadResult:
        return self._run(self._async_client.download_video(
            track_or_query,
            dest_path=dest_path,
            quality=quality,
            prefer_codec=prefer_codec,
            workers=workers,
            chunk_size_bytes=chunk_size_bytes,
            on_progress=on_progress
        ))

    def download_media(
        self,
        track_or_query: Union[TrackResult, str],
        dest_path: str = "./downloads",
        quality: Optional[str] = "1080p",
        audio_quality: Optional[str] = "highest",
        prefer_codec: Optional[str] = "avc1",
        output_format: str = "mp4",
        workers: int = 6,
        ffmpeg_bin: str = "ffmpeg",
        on_progress: Optional[Callable[[DownloadProgress], None]] = None
    ) -> DownloadResult:
        return self._run(self._async_client.download_media(
            track_or_query,
            dest_path=dest_path,
            quality=quality,
            audio_quality=audio_quality,
            prefer_codec=prefer_codec,
            output_format=output_format,
            workers=workers,
            ffmpeg_bin=ffmpeg_bin,
            on_progress=on_progress
        ))

    def is_stream_expired(self, url: str, margin_seconds: int = 30) -> bool:
        return self._async_client.is_stream_expired(url, margin_seconds)

    def close(self) -> None:
        self._async_client.close()


def create_client(api_key: Optional[str] = None, **kwargs) -> TypeTube:
    return TypeTube(api_key=api_key, **kwargs)
