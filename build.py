"""Build site/data/radar.json from free public sources."""

from pathlib import Path
import time

from radar.pipeline import build, write_atomic


def main():
    started = time.monotonic()
    payload = build()
    output = Path(__file__).resolve().parent / "site" / "data" / "radar.json"
    write_atomic(payload, output)
    for source in payload["sources"]:
        state = "ok" if source["ok"] else "FAILED"
        detail = f" -- {source['error']}" if source["error"] else ""
        print(f"{source['id']}: {state}, {source['count']} items{detail}")
    print(f"Built {output}: {len(payload['updates'])} updates, {len(payload['hf_releases'])} HF releases, "
          f"{len(payload['live'])} streams, {len(payload['trending']['github'])} GitHub / "
          f"{len(payload['trending']['huggingface'])} HF trending in {time.monotonic() - started:.1f}s")


if __name__ == "__main__":
    main()
