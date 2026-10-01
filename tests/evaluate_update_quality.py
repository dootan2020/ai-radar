"""Re-evaluate the frozen real snapshot; no network or generated-site writes."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from radar.common import classify
from radar.feeds import _research_copy


def evaluate():
    fixtures = ROOT / "tests" / "fixtures"
    raw = (fixtures / "radar-before-round2.json").read_bytes()
    baseline = json.loads(raw)
    judgments = json.loads((fixtures / "model-release-judgments.json").read_text(encoding="utf-8"))
    before_counts, after_counts = Counter(), Counter()
    before_truth, after_truth = Counter(), Counter()
    decisions, changed_titles, misses = [], [], []
    for index, item in enumerate(baseline["updates"]):
        title, summary = item["title"], item["summary"]
        before_counts[item["kind"]] += 1
        if item["source"] == "anthropic-research":
            title, summary = _research_copy(title, summary)
            kind = "research"
        else:
            kind = classify(title, summary)
        after_counts[kind] += 1
        truth = judgments[item["id"]]["truth"]
        if item["kind"] == "model":
            before_truth[truth] += 1
        if kind == "model":
            after_truth[truth] += 1
        decision = {"index": index, "id": item["id"], "url": item["url"], "title": title,
                    "before": item["kind"], "after": kind, "truth": truth,
                    "reason": judgments[item["id"]]["reason"]}
        decisions.append(decision)
        if truth == "release" and kind != "model":
            misses.append(decision)
        if title != item["title"]:
            changed_titles.append({"before": item["title"], "after": title, "url": item["url"]})
    return {
        "baseline_generated_at": baseline["generated_at"],
        "baseline_sha256": hashlib.sha256(raw).hexdigest(),
        "updates": len(decisions), "before_counts": dict(before_counts),
        "after_counts": dict(after_counts),
        "hand_review_truth": dict(Counter(row["truth"] for row in decisions)),
        "before_model_truth": dict(before_truth), "after_model_truth": dict(after_truth),
        "known_false_negatives": misses, "changed_titles": changed_titles,
        "decisions": decisions,
    }


if __name__ == "__main__":
    result = evaluate()
    target = ROOT / "plans" / "reports" / "round2-evaluation.json"
    target.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    for key in ("updates", "before_counts", "after_counts", "hand_review_truth", "before_model_truth", "after_model_truth"):
        print(key, result[key])
    print("Changed titles:", len(result["changed_titles"]))
    print("Known false negatives:", len(result["known_false_negatives"]))
    print("Evidence:", target)
