"""Build site/data/radar.json from free public sources."""

from pathlib import Path
import json
import time

from radar.pipeline import build_v2, write_atomic


def main():
    started = time.monotonic()
    output = Path(__file__).resolve().parent / "site" / "data" / "radar.json"
    previous = None
    if output.exists():
        try:
            previous = json.loads(output.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass  # A damaged baseline cannot veto fresh source collection.
    payload = build_v2(previous=previous)
    write_atomic(payload, output)
    for source in payload["sources"]:
        state = "ok" if source["ok"] else "FAILED"
        detail = f" -- {source['error']}" if source["error"] else ""
        print(f"{source['id']}: {state}, HTTP {source.get('http_status')}, {source['count']} items{detail}")
    print(f"Built {output}: {len(payload['updates'])} updates, {len(payload['hf_releases'])} HF releases, "
          f"{len(payload['live'])} streams, {len(payload['trending']['github'])} GitHub / "
          f"{len(payload['trending']['huggingface'])} HF trending in {time.monotonic() - started:.1f}s")
    print(f"V2: {len(payload['stories'])} stories, "
          f"{sum(story['source_count'] >= 2 for story in payload['stories'])} independent multi-source clusters, "
          f"{len(payload['sections']['hot'])} hot, {len(payload['events'])} verified events")


if __name__ == "__main__":
    main()
