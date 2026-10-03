"""Build site/data/radar.json from free public sources."""

from pathlib import Path
from datetime import datetime, timezone
import os
import time

from radar.measurement_cache import load_baseline, promotion_reason
from radar.pipeline import build_v2, write_atomic
from radar.publication import assess_publication, load_published, prepare_publication
from radar.seo import write_sitemap
from radar.site_payload import page_path, write_site_snapshot


def github_outputs(published, baseline_updated):
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8", newline="\n") as stream:
            stream.write(f"published={str(published).lower()}\n")
            stream.write(f"published_snapshot_updated={str(published).lower()}\n")
            stream.write(f"baseline_updated={str(baseline_updated).lower()}\n")


def main():
    started = time.monotonic()
    root = Path(__file__).resolve().parent
    output = Path(os.environ.get("RADAR_OUTPUT", root / "site/data/radar.json"))
    baseline = Path(os.environ.get("RADAR_BASELINE", root / "data/measurement-baseline.json"))
    published_cache = Path(os.environ.get("RADAR_PUBLISHED_SNAPSHOT", baseline.parent / "published-snapshot.json"))
    status_path = Path(os.environ.get("RADAR_PUBLISH_STATUS", baseline.parent / "publish-status.json"))
    site_root = output.parent.parent if output.parent.name == "data" else output.parent
    sitemap = Path(os.environ.get("RADAR_SITEMAP", site_root / "sitemap.xml"))
    paths = (output, page_path(output), baseline, published_cache, status_path, sitemap)
    if len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("Output, page projection, baseline, publication cache, diagnostic and sitemap must be different files")
    previous = load_baseline(baseline, datetime.now(timezone.utc))
    prior_publication = load_published(published_cache, datetime.now(timezone.utc))
    if prior_publication is None:
        prior_publication = load_published(output, datetime.now(timezone.utc))
    try:
        payload = build_v2(previous=previous)
    except Exception as error:
        status = assess_publication(None, prior_publication, datetime.now(timezone.utc))
        status["reason"] = f"collection failed: {type(error).__name__}"
        write_atomic(status, status_path)
        github_outputs(False, False)
        print(f"Publication rejected: {status['reason']}")
        return 1
    payload, status = prepare_publication(payload, prior_publication, datetime.now(timezone.utc))
    write_atomic(status, status_path)
    if not status["published"]:
        github_outputs(False, False)
        print(f"Publication rejected: {status['reason']}; prior snapshot left unchanged")
        return 1
    payload["freshness"] = status["freshness"]
    write_site_snapshot(payload, output)
    write_sitemap(payload["generated_at"], sitemap)
    write_atomic(payload, published_cache)
    reason = promotion_reason(payload, previous, datetime.now(timezone.utc))
    if reason is None:
        write_atomic(payload, baseline)
    github_outputs(True, reason is None)
    print(f"Measurement baseline: {'updated' if reason is None else 'not updated -- ' + reason}")
    for source in payload["sources"]:
        state = "ok" if source["ok"] else "FAILED"
        detail = f" -- {source['error']}" if source.get("error") else ""
        print(f"{source['id']}: {state}, HTTP {source.get('http_status')}, {source['count']} items{detail}")
    print(f"Built {output}: {len(payload['updates'])} updates, {len(payload['hf_releases'])} HF releases, "
          f"{len(payload['live'])} streams, {len(payload['trending']['github'])} GitHub / "
          f"{len(payload['trending']['huggingface'])} HF trending in {time.monotonic() - started:.1f}s")
    print(f"V2: {len(payload['stories'])} stories, "
          f"{sum(story['source_count'] >= 2 for story in payload['stories'])} independent multi-source clusters, "
          f"{len(payload['sections']['hot'])} hot, {len(payload['events'])} verified events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
