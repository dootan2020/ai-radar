"""Print Vietnamese/foreign origin precision and recall on labelled RSS titles."""

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from radar.vn_origin import classify_origin_item


def main():
    fixture = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "vn-origin-titles.json"
    rows = json.loads(fixture.read_text(encoding="utf-8"))
    pairs = []
    for row in rows:
        predicted = classify_origin_item(
            {"title": row["title"], "summary": row.get("summary", "")}, [],
            vietnamese_language=row["source"] != "vnexpress-tech")
        pairs.append((row["vn_origin"], predicted["has_vn_entity"]))
    print(f"Labelled titles: {len(pairs)}")
    print("Label       TP  FP  FN  Precision  Recall")
    for label, name in ((True, "Vietnam"), (False, "Foreign")):
        tp = sum(actual == label and predicted == label for actual, predicted in pairs)
        fp = sum(actual != label and predicted == label for actual, predicted in pairs)
        fn = sum(actual == label and predicted != label for actual, predicted in pairs)
        precision = tp / (tp + fp) if tp + fp else 0
        recall = tp / (tp + fn) if tp + fn else 0
        print(f"{name:10} {tp:2}  {fp:2}  {fn:2}  {precision:.1%}      {recall:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
