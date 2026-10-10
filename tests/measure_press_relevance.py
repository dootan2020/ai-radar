"""Read-only relevance measurement. Never captures publisher copy into fixtures."""

from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from radar.catalog import RSS
from radar.items import relevant
from radar.press_relevance import press_subject_reason


def measure():
    sources = {row[0]: {"filter_ai": row[5]} for row in RSS if row[2] == "press"}
    # This former source ID exists in the committed headline fixture.
    sources["vnexpress-so-hoa"] = {"filter_ai": True}
    publishers = {row[3]: row[0] for row in RSS if row[2] == "press"}
    rows, inputs = {}, []

    def walk(value, path):
        if isinstance(value, list):
            for child in value:
                walk(child, path)
        elif isinstance(value, dict):
            source = value.get("source")
            owners = value.get("publishers", [])
            if not source and len(owners) == 1:
                source = publishers.get(owners[0])
            title = value.get("title")
            if title and (source in sources or value.get("group") == "press"):
                summary = value.get("summary") or ""
                key = (source, title, summary)
                row = rows.setdefault(key, dict(source=source, title=title, summary=summary,
                                                reason=press_subject_reason(title, summary), inputs=[]))
                if path not in row["inputs"]:
                    row["inputs"].append(path)
                row["url"] = value.get("url") or row.get("url")
                # Title-only extracts cannot establish the former RSS decision.
                row["old_admission"] = ("unknown: summary omitted" if "summary" not in value
                                        else "accepted" if not sources.get(source, {}).get("filter_ai")
                                        or relevant(title, summary) else "already rejected")
            for child in value.values():
                walk(child, path)

    paths = sorted((ROOT / "tests/fixtures").rglob("*.json"))
    paths += sorted((ROOT / "site/data").rglob("*.json"))
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        name = path.relative_to(ROOT).as_posix()
        inputs.append(dict(path=name, generated_at=data.get("generated_at") if isinstance(data, dict) else None))
        walk(data, name)
    return inputs, sorted(rows.values(), key=lambda row: (row["reason"], row["source"] or "", row["title"]))


def markdown():
    inputs, rows = measure()
    counts = Counter(row["reason"] for row in rows)
    lines = ["## Measurement", "",
             f"Scanned {len(inputs)} JSON files under `tests/fixtures` and `site/data` without writes. "
             f"Found {len(rows)} distinct press inputs, deduplicated by source, original title and summary. "
             "Title-only search/review extracts are incomplete evidence, not full RSS snapshots.", "",
             "Counts: " + ", ".join(f"`{key}`: {count}" for key, count in sorted(counts.items())) + ".", "",
             "The following tables are exhaustive for all drop reasons and all keep reasons except "
             "`keep-title` (an ordinary existing AI keyword in the headline). Borderline means a weak "
             "relationship, summary-only evidence, adjacent context or insufficient copy; it is a "
             "review bucket, not a verified relevance label. A dropped observation is not necessarily "
             "a dropped story when other coverage survives.", ""]
    for heading, predicate in [("Dropped inputs", lambda r: r["reason"].startswith("drop-")),
                               ("Borderline kept inputs", lambda r: r["reason"].startswith("keep-") and r["reason"] != "keep-title")]:
        lines.extend(["### " + heading, "", "| Source | Original title | Reason | Former admission | Evidence |",
                      "| --- | --- | --- | --- | --- |"])
        for row in filter(predicate, rows):
            title = row["title"].replace("|", "\\|").replace("\n", " ")
            if row.get("url"):
                title = f"[{title}]({row['url']})"
            refs = ", ".join(f"`{p}`" for p in row["inputs"])
            lines.append(f"| {row['source']} | {title} | {row['reason']} | {row['old_admission']} | {refs} |")
        lines.append("")
    from test_press_relevance import GENUINE, PASSING
    lines.extend(["### Authored synthetic cases", "",
                  "These cases come from `tests/test_press_relevance.py`; no publisher copy was added. "
                  "The tests run the passing-mention rule across every catalog press source.", "",
                  "| Expected | Title | Actual reason |", "| --- | --- | --- |"])
    for expected, cases in [("drop", PASSING), ("keep", GENUINE)]:
        for title, summary in cases:
            lines.append(f"| {expected} | {title} | {press_subject_reason(title, summary)} |")
    lines.extend(["", "### Input inventory", ""])
    lines.extend(f"- `{entry['path']}`" + (f" — generated {entry['generated_at']}" if entry["generated_at"] else "")
                 for entry in inputs)
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(markdown(), end="")
