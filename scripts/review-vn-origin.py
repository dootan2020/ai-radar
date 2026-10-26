"""Review seven days of Vietnamese-origin shadow artifacts without publishing."""

import argparse
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from radar.clustering import canonical_url


VIETNAM_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def local_day(timestamp):
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return parsed.astimezone(VIETNAM_TZ).date() if parsed.tzinfo else None
    except (AttributeError, TypeError, ValueError):
        return None


def snapshot_paths(inputs):
    for entry in inputs:
        path = Path(entry)
        if path.is_file():
            yield path
        elif path.is_dir():
            yield from sorted(path.rglob("shadow-records.json"))
        else:
            raise FileNotFoundError(path)


def download_artifacts(root, start, days):
    end = start + timedelta(days=days)
    command = ["gh", "run", "list", "--workflow", "shadow-collector.yml",
               "--branch", "main", "--json", "databaseId,createdAt,conclusion,event",
               "--limit", "300"]
    runs = json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)
    selected = [run for run in runs if run.get("event") == "schedule"
                and (day := local_day(run.get("createdAt"))) is not None
                and start <= day < end]
    missing = []
    for run in selected:
        target = root / str(run["databaseId"])
        target.mkdir()
        result = subprocess.run(["gh", "run", "download", str(run["databaseId"]),
                                 "--name", "shadow-collector-records", "--dir", str(target)],
                                capture_output=True, text=True)
        if result.returncode or not (target / "shadow-records.json").is_file():
            missing.append(run["databaseId"])
    return len(selected), missing


def summarize(paths, start, days, sample_size=20, seed=26):
    end = start + timedelta(days=days)
    unique = {}
    failed_sources = set()
    undated = set()
    snapshots = 0
    for path in sorted(paths):
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        snapshots += 1
        for record in snapshot.get("records", []):
            if not record.get("candidate_id"):
                continue
            observed = local_day(record.get("request_time"))
            if record.get("origin_trial") and (record.get("error") or record.get("http_status") not in (None, 200)):
                if observed is not None and start <= observed < end:
                    failed_sources.add((observed, record["candidate_id"]))
            for item in record.get("items", []):
                label = item.get("vn_origin")
                if not isinstance(label, dict):
                    continue
                url = canonical_url(item.get("url"))
                if not url:
                    continue
                published = local_day(item.get("published_at"))
                if published is None:
                    undated.add(url)
                if published is None or not start <= published < end:
                    continue
                key = url
                prior = unique.get(key)
                if prior is None:
                    unique[key] = dict(item, source=record["candidate_id"], day=published)
                else:
                    old = prior["vn_origin"]
                    old["likely_foreign_republish"] |= label.get("likely_foreign_republish", False)
                    old["live_match_checked"] |= label.get("live_match_checked", False)
                    old["live_match_url"] = old.get("live_match_url") or label.get("live_match_url")
    daily = []
    all_items = list(unique.values())
    for offset in range(days):
        day = start + timedelta(days=offset)
        items = [item for item in all_items if item["day"] == day]
        daily.append((day, len(items),
                      sum(item["vn_origin"].get("vn_origin_ai", False) for item in items),
                      sum(item["vn_origin"].get("likely_foreign_republish", False) for item in items)))
    eligible = [item for item in all_items if item["vn_origin"].get("vn_origin_ai")]
    sample = random.Random(seed).sample(sorted(eligible, key=lambda item: item["url"]),
                                      min(sample_size, len(eligible)))
    unchecked = sum(not item["vn_origin"].get("live_match_checked") for item in all_items)
    return snapshots, daily, sample, unchecked, len(failed_sources), len(undated)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, type=date.fromisoformat,
                        help="First trial day in Vietnam, YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--input", action="append", default=[], help="Local snapshot or artifact directory")
    parser.add_argument("--seed", type=int, default=26)
    args = parser.parse_args(argv)
    if args.days < 1:
        parser.error("--days must be positive")
    try:
        with tempfile.TemporaryDirectory() as temporary:
            downloaded = missing = None
            inputs = args.input
            if not inputs:
                downloaded, missing = download_artifacts(Path(temporary), args.start, args.days)
                inputs = [temporary]
            snapshots, daily, sample, unchecked, failed_sources, undated = summarize(
                snapshot_paths(inputs), args.start, args.days, seed=args.seed)
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(f"Review failed: {error}", file=sys.stderr)
        return 1
    if downloaded is not None:
        print(f"Scheduled runs found: {downloaded}; artifacts missing: {len(missing)}")
        if missing:
            print("Missing run IDs: " + ", ".join(map(str, missing)))
    print(f"Snapshots read: {snapshots}; window: {args.start} through {daily[-1][0]} (Vietnam time)")
    print("Day          Items  Vietnam-origin AI  Likely foreign republish")
    for day, count, origin, republish in daily:
        print(f"{day}  {count:5}  {origin:18}  {republish:24}")
    total = sum(row[1] for row in daily)
    origins = sum(row[2] for row in daily)
    republished = sum(row[3] for row in daily)
    print(f"Total: {total} items; {origins} Vietnam-origin AI; {republished} likely republished")
    share = f"{republished / total:.1%}" if total else "unavailable (zero items)"
    print(f"Average origin AI/day: {origins / args.days:.2f}; republish share: {share}")
    print(f"Items without live comparison: {unchecked}; failed source-days: {failed_sources}; "
          f"undated items excluded: {undated}")
    print(f"Random sample for human worth-reading review ({len(sample)} items, seed {args.seed}):")
    for item in sample:
        print(f"- {item['day']} [{item['source']}] {item['title']} — {item['url']}")
    return 0 if snapshots and not (missing or unchecked or failed_sources or undated) else 1


if __name__ == "__main__":
    raise SystemExit(main())
