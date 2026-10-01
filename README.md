# typetube-py

[![PyPI version](https://img.shields.io/pypi/v/typetube.svg)](https://pypi.org/project/typetube/)
[![Python versions](https://img.shields.io/pypi/pyversions/typetube.svg)](https://pypi.org/project/typetube/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

Official Python client library for the [TypeTube](https://typetube.xysushi.in) streaming API.

Delivers **sub-second latency** stream extraction and ultra-fast parallel audio downloading with **zero external dependencies** (uses only standard library `urllib`, `concurrent.futures`, `dataclasses`).

## Features

- ⚡ **Sub-Second Latency**: Lightning-fast resolution (~200–400ms cached, sub-second uncached) powered by high-performance Protobuf wire decoding.
- 🚀 **Zero Dependencies**: Pure Python 3.9+ standard library. No bloated dependency trees.
- 📦 **Native Protobuf Wire Decoding**: High-throughput binary deserialization directly from `/v1/resolve` and `/v1/search`.
- ⚡ **Multi-Worker Range Downloads**: Parallel multi-stream chunked downloading that bypasses standard throttling.
- 🔍 **Search & Stream Resolution**: Resolve YouTube audio/video via queries, video IDs, or direct URLs.
- 📊 **Quota & Usage Inspection**: Built-in monitoring for rate limits and remaining calls (`/v1/usage`).

## Installation

### From PyPI (Recommended)

```bash
pip install typetube
```

### Direct from GitHub

```bash
pip install git+https://github.com/playeon/typetube-py.git
```

### From Source

```bash
git clone https://github.com/playeon/typetube-py.git
cd typetube-py
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
