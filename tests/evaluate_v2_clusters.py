"""Offline calibration against real captured data, never a network acceptance test."""

from collections import Counter
from datetime import timedelta
import hashlib
from itertools import combinations
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from radar.assembly import legacy_items
from radar.clustering import _tokens, canonical_url, cluster_items, titles_match
from radar.items import instant

SNAPSHOTS = ("tests/fixtures/radar-before-round2.json", "plans/reports/p1-original-snapshot.json")
SITE_LF_SHA256 = "7a06ed9f68ba9549b41e07a13a628f66c6e42b80e57c125e5545a3b68ea43fae"
THRESHOLDS = (0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.9)
EVIDENCE_PATH = ROOT / "plans/reports/p1-clustering-evidence.json"
# Review labels use original snapshot positions, not invented titles or URLs.
# Different product announcements remain separate even when unveiled at one event.
LABELS = (
    (("updates", 9), ("live", 0), True, "Same named 2026 DevDay: whole-event recap and keynote."),
    (("updates", 82), ("updates", 84), True, "Identical cyber-defense announcement, same date, two Google feeds."),
    (("hf_releases", 2), ("trending.huggingface", 6), True, "Exact same Qwen model repository URL in two HF lists."),
    (("updates", 8), ("updates", 9), False, "A specific GPT release and a whole-event recap have different story scope."),
    (("updates", 8), ("live", 0), False, "A specific GPT release must not absorb the entire DevDay keynote."),
    (("updates", 10), ("live", 0), False, "A dots product announcement is distinct from the whole-event keynote."),
    (("updates", 0), ("updates", 1), False, "Gemini model release versus SynthID Bio watermarking."),
    (("updates", 2), ("updates", 3), False, "Distillation campaign disruption versus small-business AI adoption."),
    (("updates", 8), ("updates", 10), False, "Different GPT and dots product announcements on the same date."),
    (("updates", 14), ("updates", 19), False, "Safety-case research versus a tax-workbook customer case study."),
    (("updates", 23), ("updates", 60), False, "Live Avatar announcement versus earlier Live/Extended Thinking release."),
    (("updates", 29), ("updates", 23), False, "Text-to-speech release versus Live Avatar."),
    (("updates", 31), ("updates", 34), False, "Different customers and workflows despite shared GPT-6 Astra model."),
    (("updates", 63), ("updates", 64), False, "Science applications versus language access; separate article scope."),
    (("updates", 83), ("updates", 84), False, "Gemini Flash release versus cyber-defense program announcement."),
    (("updates", 95), ("updates", 100), False, "Omni Flash versus Transcribe; different model identity."),
    (("updates", 117), ("updates", 133), False, "Gemini 3.7 release versus older 3.6/3.5 release."),
    (("updates", 160), ("updates", 161), False, "OpenCode and OpenClaw integrations are different products."),
)


def raw_item(snapshot, reference, reference_snapshot):
    section, index = reference
    value, original = snapshot, reference_snapshot
    for key in section.split("."):
        value = value[key]
        original = original[key]
    matches = [item for item in value if item["url"] == original[index]["url"]]
    if len(matches) != 1:
        raise ValueError(f"Expected one captured URL for label {reference}: {len(matches)}")
    return matches[0]


def coverage_item(snapshot, items, reference, reference_snapshot):
    raw = raw_item(snapshot, reference, reference_snapshot)
    candidates = [item for item in items if item["url"] == raw["url"]]
    section = reference[0]
    if section == "updates":
        candidates = [item for item in candidates if item["source"] == raw["source"]]
    elif section == "hf_releases":
        candidates = [item for item in candidates if item["source"] == raw["lab"] + "-hf"]
    elif section == "trending.huggingface":
        candidates = [item for item in candidates if item["source"] == "hf-trending"]
    if len(candidates) != 1:
        raise ValueError(f"Expected one real coverage item for {reference}: {len(candidates)}")
    return candidates[0]


def pair_evidence(left, right):
    a, b = _tokens(left["title"]), _tokens(right["title"])
    dates = instant(left.get("published_at")), instant(right.get("published_at"))
    hours = abs((dates[0] - dates[1]).total_seconds()) / 3600 if all(dates) else None
    jaccard = len(a & b) / max(1, len(a | b))
    same_numbers = ({token for token in a if any(c.isdigit() for c in token)}
                    == {token for token in b if any(c.isdigit() for c in token)})
    return {
        "left": {key: left.get(key) for key in ("id", "source", "publisher", "title", "url", "published_at", "time_basis")},
        "right": {key: right.get(key) for key in ("id", "source", "publisher", "title", "url", "published_at", "time_basis")},
        "shared_tokens": sorted(a & b), "jaccard": jaccard,
        "hours_apart": hours,
        "ordinary_jaccard_match_at_075": bool(hours is not None and hours <= 48 and same_numbers and len(a & b) >= 3 and jaccard >= 0.75),
        "same_canonical_url": canonical_url(left["url"]) == canonical_url(right["url"]),
    }


def counts(items, now, threshold, stories=None):
    if stories is None:
        stories = cluster_items(items, now, threshold=threshold)
    return {
        "items": len(items), "clusters": len(stories),
        "possible_pairs": len(items) * (len(items) - 1) // 2,
        "multiple_coverage_clusters": sum(len(story["coverage"]) >= 2 for story in stories),
        "multiple_feed_clusters": sum(len({item["source"] for item in story["coverage"]}) >= 2 for story in stories),
        "multiple_publisher_clusters": sum(story["source_count"] >= 2 for story in stories),
        "merged_clusters": [{"title": story["title"], "source_count": story["source_count"],
                             "coverage": [{key: item.get(key) for key in ("source", "title", "url")} for item in story["coverage"]]}
                            for story in stories if len(story["coverage"]) > 1],
    }


def evaluate_snapshot(path, provenance, reference_snapshot):
    raw = (ROOT / path).read_bytes()
    expected = provenance.get(Path(path).name, {}).get("sha256") or SITE_LF_SHA256
    normalized_sha = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
    if normalized_sha != expected:
        raise ValueError(f"Snapshot changed; positional human labels require a new review: {path}")
    snapshot = json.loads(raw)
    now = instant(snapshot["generated_at"])
    if now is None:
        raise ValueError(f"Missing snapshot timestamp: {path}")
    items = legacy_items(snapshot, now)
    week = [item for item in items if (date := instant(item.get("published_at")))
            and item.get("time_basis") == "published" and now - timedelta(days=7) <= date <= now]
    reviewed = []
    for left_ref, right_ref, same, reason in LABELS:
        left, right = (coverage_item(snapshot, items, ref, reference_snapshot) for ref in (left_ref, right_ref))
        reviewed.append(pair_evidence(left, right) | {"same_story_label": same, "label_reason": reason,
                        "both_in_last_publication_week": left in week and right in week})
    measurements = []
    for threshold in THRESHOLDS:
        stories = cluster_items(items, now, threshold=threshold)
        membership = {item["id"]: story["id"] for story in stories for item in story["coverage"]}
        confusion = Counter(tp=0, fp=0, tn=0, fn=0)
        week_confusion = Counter(tp=0, fp=0, tn=0, fn=0)
        decisions, direct = [], []
        for row in reviewed:
            predicted = membership[row["left"]["id"]] == membership[row["right"]["id"]]
            direct.append(row["same_canonical_url"] or titles_match(row["left"], row["right"], threshold=threshold))
            verdict = ("t" if predicted == row["same_story_label"] else "f") + ("p" if predicted else "n")
            confusion[verdict] += 1
            if row["both_in_last_publication_week"]:
                week_confusion[verdict] += 1
            decisions.append(predicted)
        measurements.append({"threshold": threshold, "full_snapshot": counts(items, now, threshold, stories),
                             "last_publication_week": counts(week, now, threshold),
                             "hand_label_confusion": dict(confusion), "pair_predictions": decisions, "direct_pair_matches": direct,
                             "publication_week_hand_label_confusion": dict(week_confusion),
                             "precision_on_selected_labels": confusion["tp"] / (confusion["tp"] + confusion["fp"]) if confusion["tp"] + confusion["fp"] else None,
                             "recall_on_selected_labels": confusion["tp"] / (confusion["tp"] + confusion["fn"]) if confusion["tp"] + confusion["fn"] else None})
    candidates = [pair_evidence(a, b) for a, b in combinations(items, 2)
                  if canonical_url(a["url"]) == canonical_url(b["url"]) or titles_match(a, b, threshold=min(THRESHOLDS))]
    return {"path": path, "generated_at": snapshot["generated_at"],
            "sha256": hashlib.sha256(raw).hexdigest(), "lf_sha256": normalized_sha,
            "recorded_sha256": expected, "source_status_counts": dict(Counter(str(source["ok"]) for source in snapshot["sources"])),
            "raw_collection_counts": {"updates": len(snapshot["updates"]), "hf_releases": len(snapshot["hf_releases"]),
                                      "live": len(snapshot["live"]), **{key: len(value) for key, value in snapshot["trending"].items()}},
            "normalized_items": len(items), "time_bases": dict(Counter(item["time_basis"] for item in items)),
            "publication_week_start": (now - timedelta(days=7)).isoformat(),
            "published_at_min": min(item["published_at"] for item in items if item.get("published_at")),
            "published_at_max": max(item["published_at"] for item in items if item.get("published_at")),
            "labelled_pairs": reviewed, "candidate_pairs_at_lowest_threshold": candidates, "measurements": measurements}


def evaluate():
    provenance = json.loads((ROOT / "tests/fixtures/sources.json").read_bytes())
    reference_raw = (ROOT / SNAPSHOTS[1]).read_bytes()
    if hashlib.sha256(reference_raw.replace(b"\r\n", b"\n")).hexdigest() != SITE_LF_SHA256:
        raise ValueError("Reference snapshot changed; human labels require a new review")
    reference_snapshot = json.loads(reference_raw)
    baseline = json.loads((ROOT / SNAPSHOTS[0]).read_bytes())
    return {"method": "Offline real-snapshot evaluation with manually reviewed selected pair labels; not a representative accuracy benchmark.",
            "reference_snapshot_origin": "Exact site/data/radar.json bytes preserved before P1 build; generated 2026-10-01T03:01:38Z.",
            "implementation_lf_sha256": {path: hashlib.sha256((ROOT / path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                                          for path in ("radar/clustering.py", "radar/assembly.py")},
            "shared_update_ids": len({item["id"] for item in baseline["updates"]} & {item["id"] for item in reference_snapshot["updates"]}),
            "snapshot_span_hours": (instant(reference_snapshot["generated_at"]) - instant(baseline["generated_at"])).total_seconds() / 3600,
            "recommended_threshold": 0.75, "threshold_status": "provisional_policy_not_statistically_identified",
            "limitations": ["Two highly overlapping snapshots are not seven daily captures.",
                            "Legacy pipeline already discarded repeated update URLs across feeds.",
                            "Handpicked pair labels are a development set, not independent holdout data.",
                            "No new press/forum/podcast feeds, multilingual labels, or paraphrased independent coverage in this corpus.",
                            "Missing publication dates remain unknown; repository creation is excluded from the publication-week slice."],
            "snapshots": [evaluate_snapshot(path, provenance, reference_snapshot) for path in SNAPSHOTS]}


if __name__ == "__main__":
    result = evaluate()
    target = EVIDENCE_PATH
    target.write_bytes((json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))
    for snapshot in result["snapshots"]:
        selected = next(row for row in snapshot["measurements"] if row["threshold"] == result["recommended_threshold"])
        print(snapshot["path"], snapshot["generated_at"], "items", snapshot["normalized_items"])
        for scope in ("full_snapshot", "last_publication_week"):
            print(scope, {key: value for key, value in selected[scope].items() if key != "merged_clusters"})
        print("selected-label confusion", selected["hand_label_confusion"])
    print("Evidence:", target)
