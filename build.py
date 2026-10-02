"""Build site/data/radar.json from free public sources."""

from pathlib import Path
from datetime import datetime, timezone
import os
import time

from radar.measurement_cache import load_baseline, promotion_reason
from radar.pipeline import build_v2, write_atomic


def main():
    started = time.monotonic()
    root = Path(__file__).resolve().parent
    output = Path(os.environ.get("RADAR_OUTPUT", root / "site/data/radar.json"))
    baseline = Path(os.environ.get("RADAR_BASELINE", root / "data/measurement-baseline.json"))
    if output.resolve() == baseline.resolve():
        raise ValueError("RADAR_OUTPUT and RADAR_BASELINE must be different files")
    previous = load_baseline(baseline, datetime.now(timezone.utc))
    payload = build_v2(previous=previous)
    write_atomic(payload, output)
    reason = promotion_reason(payload, previous, datetime.now(timezone.utc))
    if reason is None:
        write_atomic(payload, baseline)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8", newline="\n") as stream:
            stream.write(f"baseline_updated={str(reason is None).lower()}\n")
    print(f"Measurement baseline: {'updated' if reason is None else 'not updated -- ' + reason}")
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
