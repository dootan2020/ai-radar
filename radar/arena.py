"""Optional, licensed Arena text rankings; independent of news publication."""
import argparse
from datetime import date, datetime, timedelta, timezone
import io
import json
import math
import os
from pathlib import Path
from urllib.request import Request, urlopen

from radar.pipeline import write_atomic

DATASET = "https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset"
LICENSE = "https://creativecommons.org/licenses/by/4.0/"
BASE = DATASET + "/resolve/main/text_style_control/"
CATEGORIES = ("overall", "hard_prompts", "non_english")
COLUMNS = ["model_name", "organization", "rating", "rank", "category", "leaderboard_publish_date"]
OPTIONAL_COLUMNS = ["rating_lower", "rating_upper", "vote_count"]


def parse_parquet(content, since=None):
    """Read only owned columns; reject incomplete publications, never invent ranks."""
    import pyarrow.parquet as pq
    parquet_file = pq.ParquetFile(io.BytesIO(content))
    schema_names = set(parquet_file.schema.names)
    read_cols = [c for c in COLUMNS if c in schema_names]
    opt_cols = [c for c in OPTIONAL_COLUMNS if c in schema_names]
    batches = parquet_file.iter_batches(columns=read_cols + opt_cols)
    rows = (row for batch in batches for row in batch.to_pylist())
    publications = {}
    for row in rows:
        category = row["category"]
        if category not in CATEGORIES:
            continue
        published = date.fromisoformat(row["leaderboard_publish_date"]).isoformat()
        if since and published < since:
            continue
        model, maker = row["model_name"], row["organization"] or ""
        rank, score = row["rank"], row["rating"]
        if (not isinstance(model, str) or not model.strip() or not isinstance(maker, str)
                or isinstance(rank, bool) or not isinstance(rank, int)
                or rank < 1 or not isinstance(score, (int, float)) or not math.isfinite(score)):
            raise ValueError("Invalid Arena row")
        group = publications.setdefault(published, {}).setdefault(category, {})
        if model in group:
            raise ValueError("Duplicate Arena model")
        item = {"id": model, "maker": maker, "rank": rank, "score": score}
        if "rating_lower" in row and isinstance(row["rating_lower"], (int, float)) and math.isfinite(row["rating_lower"]):
            item["rating_lower"] = float(row["rating_lower"])
        if "rating_upper" in row and isinstance(row["rating_upper"], (int, float)) and math.isfinite(row["rating_upper"]):
            item["rating_upper"] = float(row["rating_upper"])
        if "vote_count" in row and isinstance(row["vote_count"], (int, float)) and math.isfinite(row["vote_count"]):
            item["vote_count"] = int(row["vote_count"]) if float(row["vote_count"]).is_integer() else float(row["vote_count"])
        group[model] = item
    if not publications:
        raise ValueError("No Arena publications")
    result = {}
    for published, categories in publications.items():
        if any(len(categories.get(c, {})) < 10 for c in CATEGORIES):
            raise ValueError("Incomplete Arena publication")
        result[published] = {c: sorted(categories[c].values(), key=lambda r: (r["rank"], -r["score"], r["id"]))
                             for c in CATEGORIES}
    return result


def rank_history(publications):
    return {day: {c: {r["id"]: r["rank"] for r in rows} for c, rows in groups.items()}
            for day, groups in publications.items()}


def comparison_date(published, history):
    current = date.fromisoformat(published)
    eligible = [day for day in history
                if current - timedelta(days=14) <= date.fromisoformat(day) <= current - timedelta(days=7)]
    return max(eligible, default=None)


def make_payload(published, categories, history):
    baseline = comparison_date(published, history)
    groups = {}
    for category in CATEGORIES:
        previous = history[baseline][category] if baseline else {}
        groups[category] = [{**r, "rank_change": previous[r["id"]] - r["rank"] if r["id"] in previous else None,
                             "change_status": "compared" if r["id"] in previous else "unlisted" if baseline else "unavailable"}
                            for r in categories[category][:10]]
    return {"schema_version": 1, "source": "Arena / LMArena", "dataset_url": DATASET,
            "license_url": LICENSE, "published_at": published, "comparison_at": baseline, "categories": groups}


def fetch_parquet(filename):
    limit = 96 * 1024 * 1024 if filename.startswith("full") else 8 * 1024 * 1024
    request = Request(BASE + filename, headers={"User-Agent": "ai-radar-arena/1.0"})
    with urlopen(request, timeout=60) as response:
        content = response.read(limit + 1)
    if len(content) > limit:
        raise ValueError("Arena download exceeds size limit")
    return content


def due(last, now, days):
    try:
        elapsed = now - datetime.fromisoformat(last)
        return elapsed >= timedelta(days=days) or elapsed < timedelta(0)
    except (TypeError, ValueError):
        return True


def refresh(state, now, fetch=fetch_parquet):
    """Failed latest reads retain the exact last good rankings and their dates."""
    state = dict(state)
    stamp = now.isoformat()
    if not due(state.get("attempted_at"), now, 1):
        return state
    state["attempted_at"] = stamp
    try:
        publications = parse_parquet(fetch("latest-00000-of-00001.parquet"))
        published = max(publications)
        if date.fromisoformat(published) > now.date():
            raise ValueError("Future Arena publication")
        old_date = state.get("snapshot", {}).get("published_at")
        if old_date and published < old_date:
            raise ValueError("Arena publication regressed")
        history = dict(state.get("history", {}))
        history.update(rank_history(publications))
        if not comparison_date(published, history) and due(state.get("history_attempted_at"), now, 7):
            state["history_attempted_at"] = stamp
            try:
                historical = rank_history(parse_parquet(fetch("full-00000-of-00001.parquet"),
                    since=(date.fromisoformat(published) - timedelta(days=60)).isoformat()))
                history = {**historical, **history}
                state.pop("history_error", None)
            except Exception as exc:
                state["history_error"] = type(exc).__name__
        cutoff = date.fromisoformat(published) - timedelta(days=60)
        history = {day: value for day, value in history.items() if cutoff <= date.fromisoformat(day) <= date.fromisoformat(published)}
        state.update(history=history, snapshot=make_payload(published, publications[published], history),
                     fetched_at=stamp, fetch_status="ok")
    except Exception as exc:
        state.update(fetch_status="failed", error=type(exc).__name__)
    return state


def public_payload(state, now):
    snapshot = state.get("snapshot", {})
    published = snapshot.get("published_at")
    return {**snapshot, "schema_version": 1, "fetched_at": state.get("fetched_at"),
            "checked_at": state.get("attempted_at"), "fetch_status": state.get("fetch_status", "unavailable"),
            "stale": bool(published and (now.date() - date.fromisoformat(published)).days > 14)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=Path("data/arena-state.json"))
    parser.add_argument("--output", type=Path, default=Path("site/data/arena.json"))
    parser.add_argument("--fixture-dir", type=Path, help="Offline verification using supplied Parquet files")
    args = parser.parse_args()
    try:
        state = json.loads(args.state.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    fetch = fetch_parquet
    if args.fixture_dir:
        def fetch(filename):
            suffix = "full-last8" if filename.startswith("full") else "latest"
            return (args.fixture_dir / f"text_style_control-{suffix}.parquet").read_bytes()
    now = datetime.now(timezone.utc)
    # Publish the fallback before network or decoder work, including hard step timeouts.
    fallback = dict(state)
    if due(state.get("attempted_at"), now, 1):
        fallback.update(attempted_at=now.isoformat(), fetch_status="failed")
    write_atomic(fallback, args.state, compact=True)
    write_atomic(public_payload(fallback, now), args.output, compact=True)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write("arena_written=true\n")
    state = refresh(state, now, fetch)
    write_atomic(state, args.state, compact=True)
    write_atomic(public_payload(state, now), args.output, compact=True)
    print(f"Arena: {state.get('fetch_status', 'unavailable')}; published={state.get('snapshot', {}).get('published_at', 'unavailable')}")


if __name__ == "__main__":
    main()
