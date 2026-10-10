#!/usr/bin/env python3
"""
TypeTube interactive CLI shell in Python.
Matches src/cli.ts.
"""
from __future__ import annotations
import sys
import os
import argparse
from typetube import TypeTube

def main() -> None:
    parser = argparse.ArgumentParser(description="TypeTube high-performance media client")
    parser.add_argument("query", nargs="*", help="Track title, URL, or video ID to resolve")
    parser.add_argument("-k", "--key", help="API key for private cluster tier", default=os.environ.get("TYPETUBE_API_KEY"))
    parser.add_argument("-H", "--host", help="Cluster host (e.g. tap://sg.clusters.typetube.xyz)", default=os.environ.get("TYPETUBE_HOST"))
    parser.add_argument("-p", "--port", type=int, help="Cluster port", default=8443)
    parser.add_argument("-x", "--audio-only", action="store_true", help="Download audio only")
    parser.add_argument("-v", "--video", action="store_true", help="Download video muxed with audio to MP4")
    parser.add_argument("--video-only", action="store_true", help="Download raw adaptive video stream without audio")
    parser.add_argument("-f", "--format", help="Video quality (2160p, 1440p, 1080p, 720p, 480p, 360p, highest, lowest)", default="1080p")
    parser.add_argument("-a", "--audio-quality", help="Audio quality (highest, hifi, 256kbps, 128kbps, lowest)", default="highest")
    parser.add_argument("-c", "--codec", help="Preferred video codec (avc1, vp9, av01, any)", default="avc1")
    parser.add_argument("--ext", help="Output container format (mp4, mkv, webm)", default="mp4")
    parser.add_argument("-o", "--output", help="Output directory or file path", default="./downloads")
    parser.add_argument("-N", "--workers", type=int, help="Parallel range download workers", default=4)
    parser.add_argument("-e", "--get-title", action="store_true", help="Print track title")
    parser.add_argument("--get-id", action="store_true", help="Print video ID")
    parser.add_argument("--get-thumbnail", action="store_true", help="Print thumbnail URL")

    args = parser.parse_args()

    client = TypeTube(
        api_key=args.key,
        host=args.host,
        port=args.port
    )

    if not args.query:
        print("TypeTube Interactive Shell (Python)")
        print("Type track names or 'exit' to quit.\n")
        try:
            while True:
                q = input("typetube> ").strip()
                if not q or q.lower() in ("exit", "quit"):
                    break
                track = client.resolve(q)
                print(f"{track.title} ({track.duration_seconds}s)")
                print(f"Audio Stream: {track.best_audio.url if track.best_audio else 'None'}")
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
        finally:
            client.close()
        return

    query_str = " ".join(args.query)
    track = client.resolve(query_str)

    if args.get_title:
        print(track.title)
        return
    if args.get_id:
        print(track.id)
        return
    if args.get_thumbnail:
        print(track.thumbnail or "")
        return

    if args.video:
        print(f"Downloading Video+Audio: {track.title} ({args.format})...")
        res = client.download_media(
            track,
            dest_path=args.output,
            quality=args.format,
            audio_quality=args.audio_quality,
            prefer_codec=args.codec,
            output_format=args.ext,
            workers=args.workers,
            on_progress=lambda p: print(f"{p.phase}: {p.percent}%", end="\r", flush=True)
        )
        print(f"\nSaved to: {res.file_path}")
    elif args.video_only:
        print(f"Downloading Video: {track.title} ({args.format})...")
        res = client.download_video(
            track,
            dest_path=args.output,
            quality=args.format,
            prefer_codec=args.codec,
            workers=args.workers,
            on_progress=lambda p: print(f"{p.percent}% - {p.speed_mbps:.1f} MB/s", end="\r", flush=True)
        )
        print(f"\nSaved to: {res.file_path}")
    elif args.audio_only:
        print(f"Downloading Audio: {track.title} ({args.audio_quality})...")
        res = client.download_audio(
            track,
            dest_path=args.output,
            audio_quality=args.audio_quality,
            workers=args.workers,
            on_progress=lambda p: print(f"{p.percent}% - {p.speed_mbps:.1f} MB/s", end="\r", flush=True)
        )
        print(f"\nSaved to: {res.file_path}")
    else:
        print(f"Title: {track.title}")
        print(f"ID: {track.id}")
        print(f"Author: {track.author}")
        print(f"Duration: {track.duration_seconds}s")
        if track.best_audio:
            print(f"Best Audio: {track.best_audio.quality} ({track.best_audio.bitrate} bps)")
            print(f"Audio URL: {track.best_audio.url}")

    client.close()

if __name__ == "__main__":
    main()
