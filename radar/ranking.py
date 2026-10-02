"""Explainable freshness-weighted ranking from measured observations only."""

from collections import defaultdict
from decimal import Decimal

from radar.items import instant, measured

METRICS = ("points", "score", "upvotes", "trending_score", "stars_today", "stars")
LABELS = {"points": "điểm", "score": "điểm", "upvotes": "lượt bình chọn", "trending_score": "điểm thịnh hành",
          "stars_today": "sao hôm nay", "stars": "sao"}


def _metric(item):
    metrics = item.get("metrics") or {}
    if not isinstance(metrics, dict):
        return None, None
    for key in METRICS:
        value = measured(metrics.get(key))
        if value is not None:
            return key, value
    return None, None


def _format_measurement(value):
    """Display validated counters the Vietnamese way (1.234.567,25), without exponent notation or lost decimals."""
    if isinstance(value, int) or value.is_integer():
        return f"{int(value):,}".replace(",", ".")
    return f"{Decimal(str(value)):,f}".replace(",", " ").replace(".", ",").replace(" ", ".")


def _percentiles(rows):
    """Average tie ranks in [0,1]; a singleton has no comparison population."""
    if len(rows) < 2:
        return {key: None for key, _ in rows}
    values = [value for _, value in rows]
    return {key: (sum(other < value for other in values) + (sum(other == value for other in values) - 1) / 2)
            / (len(values) - 1) for key, value in rows}


def rank_stories(stories, now, previous=None):
    now = instant(now)
    previous = previous if isinstance(previous, dict) else {}
    baseline_at = instant(previous.get("generated_at"))
    valid_baseline = bool(previous.get("schema_version") == 2 and now and baseline_at
                          and 0 < (now - baseline_at).total_seconds() <= 48 * 3600)
    baseline = {}
    if valid_baseline and isinstance(previous.get("stories"), list):
        for story in previous["stories"]:
            if isinstance(story, dict):
                for item in story.get("coverage", []) if isinstance(story.get("coverage"), list) else []:
                    if isinstance(item, dict):
                        source, id_ = item.get("source"), item.get("id")
                        if isinstance(source, str) and isinstance(id_, str):
                            baseline[(source, id_)] = item
    populations, velocities, observations = defaultdict(dict), defaultdict(dict), {}
    for story in stories:
        for item in story["coverage"]:
            metric, value = _metric(item)
            if metric is None:
                continue
            key = (item["source"], item["id"])
            peer_group = (item["source"], metric)
            populations[peer_group][key] = value
            old = baseline.get(key, {})
            old_metrics = old.get("metrics") if isinstance(old.get("metrics"), dict) else {}
            old_value = measured(old_metrics.get(metric))
            before, after = instant(old.get("observed_at")), instant(item.get("observed_at"))
            velocity = None
            if (old_value is not None and before and after and now and after <= now and before <= baseline_at
                    and 0 < (after - before).total_seconds() <= 48 * 3600 and value >= old_value):
                try:
                    velocity = measured((value - old_value) / ((after - before).total_seconds() / 3600))
                except OverflowError:
                    velocity = None
                if velocity is not None:
                    velocities[peer_group][key] = velocity
            observations[key] = dict(source=item["source"], metric=metric, value=value,
                                     observed_at=item.get("observed_at"), velocity_per_hour=velocity,
                                     previous_observed_at=old.get("observed_at") if velocity is not None else None,
                                     previous_value=old_value if velocity is not None else None)
    percentiles, velocity_percentiles = {}, {}
    for peers in populations.values():
        percentiles.update(_percentiles(list(peers.items())))
    for peers in velocities.values():
        velocity_percentiles.update(_percentiles(list(peers.items())))
    for story in stories:
        candidates = [(percentiles.get((item["source"], item["id"])), (item["source"], item["id"]))
                      for item in story["coverage"] if (item["source"], item["id"]) in observations]
        candidates.sort(key=lambda row: (row[0] is not None, row[0] or 0, row[1]), reverse=True)
        percentile, key = candidates[0] if candidates else (None, None)
        measurement = observations.get(key)
        velocity_rank = velocity_percentiles.get(key)
        count = len({item["publisher"] for item in story["coverage"]})
        spread = min(count, 5) / 5 if count >= 2 else None
        published = instant(story.get("published_at"))
        age = (now - published).total_seconds() / 3600 if now and published else None
        freshness = 0.5 ** (age / 24) if age is not None and 0 <= age <= 72 else None
        signals = dict(age_hours=round(age, 4) if age is not None else None, freshness=freshness,
                       engagement_percentile=percentile, velocity_per_hour=measurement["velocity_per_hour"] if measurement else None,
                       velocity_percentile=velocity_rank, source_count=count, spread=spread, measurement=measurement)
        story.update(source_count=count, hot_score=None, hot_reason=None, hot_signals=signals)
        components = [(percentile, 0.4), (velocity_rank, 0.2), (spread, 0.4)]
        components = [(value, weight) for value, weight in components if value is not None]
        if freshness is None or not components:
            continue
        story["hot_score"] = round(100 * freshness * sum(value * weight for value, weight in components)
                                   / sum(weight for _, weight in components), 3)
        reasons = []
        if spread is not None:
            reasons.append(f"{count} nguồn độc lập cùng đưa")
        if measurement and percentile is not None:
            reasons.append(f"{measurement['source']}: {_format_measurement(measurement['value'])} {LABELS[measurement['metric']]}")
        if measurement and velocity_rank is not None:
            reasons.append(f"tăng {measurement['velocity_per_hour']:.1f}/giờ từ hai lần đo".replace(".", ",", 1))
        prefix = "kho mã được tạo" if story.get("time_basis") == "repository_created" else "đăng"
        reasons.append(f"{prefix} {max(0, int(age))} giờ trước")
        story["hot_reason"] = " · ".join(reasons)
    return stories


def hot_eligible(story):
    if story.get("hot_score") is None:
        return False
    signals = story.get("hot_signals", {})
    measurement = signals.get("measurement") or {}
    return (signals.get("source_count", 0) >= 2 or
            (signals.get("engagement_percentile") is not None and signals["engagement_percentile"] >= 0.8
             and measurement.get("value", 0) > 0))
