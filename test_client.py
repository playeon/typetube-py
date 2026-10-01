import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from typetube import create_client, TypeTubeError

def run_tests():
    client = create_client(
        endpoint="https://typetube.xysushi.in",
        api_key="tt_priv_prod_key",
        timeout=15,
    )

    t0 = time.time()
    usage = client.usage()
    t_usage = (time.time() - t0) * 1000
    print(f"[OK] usage(): tier={usage.tier}, remaining={usage.resolve_remaining}/{usage.resolve_limit} in {t_usage:.1f}ms")
    assert usage.resolve_limit > 0

    t0 = time.time()
    search_res = client.search("Queen Bohemian Rhapsody", limit=3)
    t_search = (time.time() - t0) * 1000
    print(f"[OK] search(): found {len(search_res)} items in {t_search:.1f}ms")
    assert len(search_res) > 0
    print(f"     First item: {search_res[0].title} ({search_res[0].duration}) - {search_res[0].url}")

    t0 = time.time()
    track = client.resolve("dQw4w9WgXcQ")
    t_resolve = (time.time() - t0) * 1000
    print(f"[OK] resolve(dQw4w9WgXcQ): title='{track.title}', duration={track.duration_seconds}s in {t_resolve:.1f}ms")
    assert track.success
    assert track.best_audio is not None
    assert track.best_audio.url.startswith("http")
    print(f"     Best audio: itag={track.best_audio.itag}, mime={track.best_audio.mime_type}, bitrate={track.best_audio.bitrate}")

    out_file = "/tmp/test_download.m4a"
    if os.path.exists(out_file):
        os.remove(out_file)

    t0 = time.time()
    dl = client.download_audio(track, out_file, workers=4, chunk_size=512 * 1024)
    print(f"[OK] download_audio(): bytes={dl.bytes_written}, time={dl.duration_sec:.2f}s, speed={dl.average_speed_mbps:.2f} MB/s")
    assert os.path.exists(out_file)
    assert os.path.getsize(out_file) == dl.bytes_written
    assert dl.bytes_written > 100000

    if os.path.exists(out_file):
        os.remove(out_file)

    print("ALL PYTHON CLIENT TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_tests()
