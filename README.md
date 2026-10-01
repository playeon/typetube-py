# typetube-py

Python client library for the TypeTube streaming API.

Zero runtime dependencies. Uses standard Python libraries (urllib.request, concurrent.futures, dataclasses).

## Features

- Native Protocol Buffers wire decoding (fast binary responses from /v1/resolve and /v1/search)
- Multi-worker chunked range downloading with fallback to single-stream download
- Stream resolution (/v1/resolve)
- Video search (/v1/search)
- Quota and usage inspection (/v1/usage)
- Support for API key authentication and custom endpoints

## Installation

```bash
pip install typetube
```

Or install from source:

```bash
cd packages/typetube-py
pip install .
```

## Quick Start

```python
from typetube import create_client

client = create_client(
    endpoint="https://typetube.xysushi.in",
    api_key="your_api_key_here",
)

result = client.resolve("Rick Astley - Never Gonna Give You Up")
print(result.title)
print(result.author)
if result.best_audio:
    print(result.best_audio.url)

client.download_audio(result, "track.m4a", workers=8)
```

## Usage

### Stream Resolution

Resolve YouTube videos by search query, video ID, or direct URL:

```python
result = client.resolve("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
print(f"Title: {result.title}")
print(f"Duration: {result.duration_seconds}s")
if result.best_audio:
    print(f"Best Audio Bitrate: {result.best_audio.bitrate} bps")
    print(f"Best Audio URL: {result.best_audio.url}")
```

### Search

Search for tracks:

```python
results = client.search("Hans Zimmer Interstellar", limit=5)
for item in results:
    print(f"{item.title} ({item.duration}) - {item.url}")
```

### Parallel Chunked Audio Download

Download audio with multi-worker parallel HTTP range requests:

```python
download_res = client.download_audio(
    result,
    output_path="never_gonna_give_you_up.m4a",
    workers=8,
    chunk_size=1048576,
)

print(f"Downloaded {download_res.bytes_written} bytes to {download_res.path}")
print(f"Average speed: {download_res.average_speed_mbps:.2f} MB/s")
```

### Quota and Usage

Inspect quota limits and remaining calls:

```python
usage = client.usage()
print(f"IP: {usage.ip}")
print(f"Tier: {usage.tier}")
print(f"Resolve remaining: {usage.resolve_remaining}/{usage.resolve_limit}")
print(f"Reset in: {usage.reset_seconds}s")
```

## License

MIT
