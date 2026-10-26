"""Score newsroom decisions against independently labelled stories."""

from __future__ import annotations

import json
from pathlib import Path

ROUNDS = ("intake", "reporter", "editor", "checker", "chief")


def evaluate(decisions_path, labels_path):
    decisions_data = json.loads(Path(decisions_path).read_text(encoding="utf-8"))
    labels_data = json.loads(Path(labels_path).read_text(encoding="utf-8"))
    decisions = decisions_data.get("decisions") if isinstance(decisions_data, dict) else decisions_data
    labels = labels_data.get("stories") if isinstance(labels_data, dict) else labels_data
    if not isinstance(decisions, list) or not isinstance(labels, list):
        raise ValueError("invalid decisions or labels file")
    labelled = {item["id"]: item for item in labels}
    decided = {item["id"]: item for item in decisions}
    if len(labelled) != len(labels) or len(decided) != len(decisions) or set(labelled) != set(decided):
        raise ValueError("decisions must cover every labelled story exactly once")
    if any(row.get("decision") not in {"publish", "hold"} or row.get("round") not in ROUNDS for row in decisions):
        raise ValueError("invalid decision or round")
    junk = {sid for sid, row in labelled.items() if row["labels"]["junk"] is True}
    good = set(labelled) - junk
    leaked = [sid for sid in junk if decided[sid]["decision"] == "publish"]
    false_holds = [sid for sid in good if decided[sid]["decision"] == "hold"]
    breakdown = {desk: {"junk_held": 0, "good_held": 0, "published": 0} for desk in ROUNDS}
    for sid, row in decided.items():
        key = "published" if row["decision"] == "publish" else "junk_held" if sid in junk else "good_held"
        breakdown[row["round"]][key] += 1
    return {"stories": len(labels), "junk_total": len(junk), "good_total": len(good),
            "junk_leaked": len(leaked), "junk_leak_percent": round(100 * len(leaked) / len(junk), 2) if junk else 0,
            "good_wrongly_held": len(false_holds), "good_hold_percent": round(100 * len(false_holds) / len(good), 2) if good else 0,
            "targets_met": (len(leaked) / len(junk) <= .02 if junk else True) and
                           (len(false_holds) / len(good) <= .10 if good else True),
            "by_desk": breakdown}
