"""
TAP payload compression and decompression.
Supports Zstandard (zstd) with fallback to Brotli, matching Node.js zlib.
"""
from __future__ import annotations
import zlib

def decompress_payload(payload: bytes) -> bytes:
    # 1. Try Zstandard (preferred in Node.js)
    try:
        import zstandard as zstd
        dctx = zstd.ZstdDecompressor()
        return dctx.decompress(payload, max_output_size=16 * 1024 * 1024)
    except Exception:
        pass

    # 2. Try Brotli
    try:
        import brotli
        return brotli.decompress(payload)
    except Exception:
        pass

    # 3. Try standard Deflate
    try:
        return zlib.decompress(payload)
    except Exception:
        return zlib.decompress(payload, -zlib.MAX_WBITS)


def compress_payload(payload: bytes) -> bytes:
    try:
        import zstandard as zstd
        cctx = zstd.ZstdCompressor(level=1)
        out = cctx.compress(payload)
        if len(out) < len(payload):
            return out
    except Exception:
        pass

    try:
        import brotli
        out = brotli.compress(payload, quality=5)
        if len(out) < len(payload):
            return out
    except Exception:
        pass

    return payload
