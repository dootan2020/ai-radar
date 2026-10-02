"""Validate and retain measurement baselines independently of fresh UI evidence."""

from collections import Counter
import json
from pathlib import Path

from radar.items import instant, measured
from radar.ranking import METRICS

MAX_AGE_SECONDS = 48 * 3600
# Cache-retention policy, not a claim about source quality or ranking accuracy.
MIN_SUCCESS_RATIO = 0.8
MIN_MEASUREMENT_RETENTION = 0.5


def _inspect(payload, now):
    """Return active source statuses and measured identities, or reject schema."""
    if not isinstance(payload, dict) or payload.get("schema_version") != 2:
        raise ValueError("incompatible snapshot schema")
    stamp, now = instant(payload.get("generated_at")), instant(now)
    if not stamp or not now or not 0 <= (now - stamp).total_seconds() <= MAX_AGE_SECONDS:
        raise ValueError("snapshot timestamp missing, future or older than 48 hours")
    sources, stories = payload.get("sources"), payload.get("stories")
    if not isinstance(sources, list) or not isinstance(stories, list):
        raise ValueError("sources and stories must be arrays")
    active, identities = {}, set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("invalid source record")
        id_ = source.get("id")
        if not isinstance(id_, str) or not id_ or id_ in identities:
            raise ValueError("missing or duplicate source identity")
        identities.add(id_)
        if (not isinstance(source.get("ok"), bool) or type(source.get("count")) is not int
                or source["count"] < 0):
            raise ValueError("invalid source status or count")
        if source.get("disabled") is True or id_ == "curated-events":
            continue
        if not isinstance(source.get("url"), str) or not source["url"]:
            raise ValueError("active remote source missing URL")
        active[id_] = source["ok"]
    measurements = set()
    for story in stories:
        if not isinstance(story, dict) or not isinstance(story.get("coverage"), list):
            raise ValueError("invalid story coverage")
        for item in story["coverage"]:
            if not isinstance(item, dict):
                raise ValueError("invalid observation")
            source, id_ = item.get("source"), item.get("id")
            if (not isinstance(source, str) or source not in identities
                    or not isinstance(id_, str) or not id_):
                raise ValueError("invalid observation identity")
            observed = instant(item.get("observed_at"))
            if not observed or not 0 <= (stamp - observed).total_seconds() <= MAX_AGE_SECONDS:
                raise ValueError("invalid observation timestamp")
            metrics = item.get("metrics")
            if not isinstance(metrics, dict):
                raise ValueError("invalid observation metrics")
            for metric in METRICS:
                value = metrics.get(metric)
                if value is not None:
                    if measured(value) is None:
                        raise ValueError("invalid measurement")
                    if source in active and active[source]:
                        measurements.add((source, id_))
    return active, measurements


def promotion_reason(payload, previous, now):
    """None permits promotion; a reason retains the old file without retimestamping."""
    try:
        active, measurements = _inspect(payload, now)
    except ValueError as error:
        return str(error)
    if not active or sum(active.values()) / len(active) < MIN_SUCCESS_RATIO:
        return "fewer than 80% of active remote sources succeeded"
    if not measurements:
        return "no valid ranking measurements"
    if previous is not None:
        try:
            _, old_measurements = _inspect(previous, now)
        except ValueError:
            old_measurements = set()
        # A healthy RSS majority cannot mask losing the source that supplied votes.
        if any(not active.get(source) for source, _ in old_measurements):
            return "a previously measured source is unavailable"
        old_counts = Counter(source for source, _ in old_measurements)
        new_counts = Counter(source for source, _ in measurements)
        if any(new_counts[source] < count * MIN_MEASUREMENT_RETENTION for source, count in old_counts.items()):
            return "a source retained fewer than half of its prior measured observations"
    return None


def load_baseline(path, now):
    """A bad cache cannot prevent collection or introduce a fabricated baseline."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if promotion_reason(payload, None, now) is not None:
            return None
        if instant(payload["generated_at"]) >= instant(now):
            return None
        return payload
    except (OSError, ValueError, TypeError):
        return None
