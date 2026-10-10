# TypeTube

High-performance YouTube stream resolver and unthrottled downloader for Python powered by TAP (Tagged Asynchronous Protocol).

Features:
- Sub-second full stream resolution for search queries and direct video URLs
- Tagged Asynchronous Protocol (TAP) with binary RPC multiplexing over persistent sockets
- Direct Google Video CDN URLs with automatic stream selection
- Multi-worker range downloads (up to 32 parallel workers) to avoid speed throttling
- Automatic recovery when stream URLs expire mid-flight
- Optional video and audio muxing to MP4 via FFmpeg
- Native Asynchronous (`AsyncTypeTube`) engine with synchronous (`TypeTube`) wrapper support

## Public Access & Limits

The client connects to the official public cluster by default. Public access is granted automatically per IP address:

- **60 resolves / minute** per IP
- **1,500 resolves / day** per IP
- *Public limits are subject to change at any time without notice*

### Hi-Fi 256kbps Audio & Private API Keys

- **Public access** provides standard audio streams (up to 128kbps / 160kbps)
- **Private API keys** unlock unthrottled 256kbps Hi-Fi AAC (`itag 141`) and 272kbps Opus (`itag 774`) streams, higher throughput quotas, and priority cluster routing

> **Regional Notice**: The cluster is currently located in Singapore only. Due to YouTube regional restrictions, some original VEVO tracks may not be downloadable or playable when accessed from outside Singapore. An India cluster will be added soon.

To request a private API key, join our Telegram channel: **[@PlayeonX](https://t.me/PlayeonX)**

## Installation

```bash
pip install typetube
```

Requires Python 3.9 or higher. If you plan to mux video and audio into a single MP4 file, make sure `ffmpeg` is installed on your system.

## Quick Start (SDK)

### Asynchronous (Recommended)

```python
import asyncio
from typetube import AsyncTypeTube

async def main():
    # Initializes client (connects to default public cluster)
    client = AsyncTypeTube()

    # 1. Resolve metadata and stream manifests
    track = await client.resolve("ReoNa 『ないない』-Music Video-")
    print(track.title, f"({track.duration_seconds}s)")
    print("Audio Stream URL:", track.best_audio.url)

    # 2. Download audio with 4 parallel range workers
    audio = await client.download_audio(
        track,
        dest_path="./music",
        audio_quality="highest",
        workers=4,
        on_progress=lambda p: print(f"{p.percent}% - {p.speed_mbps:.1f} MB/s")
    )
    print("Audio saved to:", audio.file_path)

    # 3. Download 1080p video muxed with audio
    video = await client.download_media(
        track,
        dest_path="./videos",
        quality="1080p",
        output_format="mp4",
        on_progress=lambda p: print(f"{p.phase}: {p.percent}%")
    )
    print("Video saved to:", video.file_path)

    client.close()

asyncio.run(main())
```

### Synchronous

```python
from typetube import TypeTube

client = TypeTube()

track = client.resolve("ReoNa 『ないない』-Music Video-")
print(track.title, track.best_audio.url)

audio = client.download_audio(track, dest_path="./music")
print("Audio saved to:", audio.file_path)

client.close()
```

## Client Configuration

```python
from typetube import AsyncTypeTube

# 1. Default public cluster
client = AsyncTypeTube()

# 2. Private access with an API key
private_client = AsyncTypeTube(api_key="YOUR_PRIVATE_KEY")

# 3. Custom cluster endpoint
custom_client = AsyncTypeTube(
    api_key="YOUR_PRIVATE_KEY",
    host="tap://sg.clusters.typetube.xyz",
    port=8443,
    timeout_ms=15000
)
```

## Methods

### `await client.resolve(query, max_video_height=None)`

Resolves a video URL, video ID, or search query into a complete track object with sub-second latency.

```python
track = await client.resolve("https://www.youtube.com/watch?v=dQw4w9WgXcQ", max_video_height=1080)
```

Returns `TrackResult`:
- `id`: YouTube video ID
- `title`: Video title
- `author`: Channel name
- `duration_seconds`: Track duration in seconds
- `best_audio`: Best available audio stream (prefers 256kbps AAC or Opus on private keys)
- `best_video`: Best available video stream matching `max_video_height`
- `audio_streams`: List of audio streams
- `video_streams`: List of video streams
- `thumbnails`: Array of thumbnail objects with dimensions
- `latency_ms`: Resolution latency in milliseconds

### `await client.search(query, limit=10)`

Searches YouTube and returns a ranked list of items.

```python
results = await client.search("daft punk", limit=5)
for item in results:
    print(item.title, item.url)
```

### `await client.download_audio(track_or_query, dest_path="./downloads", audio_quality="highest", workers=4, on_progress=None)`

Downloads the audio stream to disk using multi-worker HTTP range requests.

### `await client.download_video(track_or_query, dest_path="./downloads", quality="1080p", workers=6, on_progress=None)`

Downloads the standalone adaptive video stream to disk using multi-worker range requests.

### `await client.download_media(track_or_query, dest_path="./downloads", quality="1080p", audio_quality="highest", output_format="mp4", workers=6, on_progress=None)`

Downloads both audio and video streams in parallel, then muxes them into a single MP4 container using FFmpeg.

### `await client.ping()`

Pings the active socket connection and returns live round-trip latency in milliseconds.

```python
latency = await client.ping()
print(f"Socket RTT: {latency:.2f} ms")
```

### `client.close()`

Closes the active connection.

```python
client.close()
```

## Interactive CLI Shell

TypeTube provides a persistent interactive shell that keeps a TAP connection open across commands:

```bash
# Launch interactive shell
typetube
```

Inside the interactive shell:
```text
typetube> "ReoNa ないない"
typetube> "ReoNa ないない" -v -f 1080p -o ./videos
typetube> "queen bohemian rhapsody" -x -a hifi -o ./music -N 8
typetube> exit
```

### CLI Command Flags

- `-v`, `--video`: Download video muxed with audio to MP4
- `--video-only`: Download raw adaptive video stream without audio
- `-x`, `--audio-only`: Download audio stream only
- `-f`, `--format <quality>`: Video resolution: `2160p`, `1440p`, `1080p`, `720p`, `480p`, `360p`, `highest`, `lowest` (default: `1080p`)
- `-a`, `--audio-quality <q>`: Audio quality: `highest`, `hifi`, `256kbps`, `128kbps`, `lowest` (default: `highest`)
- `-c`, `--codec <name>`: Preferred video codec: `avc1` (H.264), `vp9`, `av01` (AV1), `any` (default: `avc1`)
- `--ext <mp4|mkv|webm>`: Output container format (default: `mp4`)
- `-o`, `--output <path>`: Destination file path or directory (default: `./downloads`)
- `-N`, `--workers <count>`: Number of parallel download workers: 1 to 32 (default: 4 for audio, 6 for video)
- `--chunk-size <mb>`: Range chunk size in MB (default: 10)
- `-e`, `--get-title`: Print track title
- `--get-id`: Print video ID
- `--get-thumbnail`: Print high-resolution thumbnail URL

## License

MIT
