"""Replay stored newsroom writer replies through a baseline and the current summary validator.

Offline only: no model or network call. Each cycle folder (plans/handoffs/replay-cycles/<cycle>/)
holds writer.json (the desk's verdict and the source paragraphs the writer read) and raw/writer-*.json
(the writer's replies). The script rebuilds the writer inputs from writer.json, runs
phong_bao.newsroom._written_prose once with the validator functions from --baseline (loaded with
git show) and once with the working tree's, and prints per error type how many sentences each
rejected, every sentence that flipped from rejected to accepted (with the paragraphs it cites, so a
reader can judge it), and how many stories reach a complete summary without any rewrite.

Calibration: the baseline run must reproduce the stored verdict of every story; mismatches are listed
because the stored inputs lack the story title and the paragraphs fit_inputs omitted.

Usage:
    python scripts/replay-summary-validation.py [--cycles DIR] [--baseline REV] [--verdicts FILE] [--out FILE]
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import types
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from phong_bao import newsroom  # noqa: E402
from radar import summary_validation  # noqa: E402

PATCHED = ("claim_error", "attribution_error", "number_error")


def baseline_validator(rev):
    source = subprocess.run(["git", "show", f"{rev}:radar/summary_validation.py"], cwd=ROOT, check=True,
                            capture_output=True).stdout.decode("utf-8")
    module = types.ModuleType("baseline_summary_validation")
    module.__file__ = f"{rev}:radar/summary_validation.py"
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def rebuild_inputs(row):
    sources = []
    for source in row["writer_sources"]:
        sources.append({
            "id": source["id"], "role": source["role"], "url": source["url"], "title": "",
            "publisher": {"id": source["id"] + ":publisher", "text": source["publisher"]},
            "body_complete": source["body_complete"], "omitted_paragraph_ids": source["omitted_paragraph_ids"],
            "paragraphs": source["paragraphs"], "published_at": None,
        })
    inputs = {"id": row["id"], "sources": sources, "missing_primary": False, "linked_primary": None}
    evidence = {source["id"]: " ".join(p["text"] for p in source["paragraphs"]) for source in sources}
    return inputs, evidence


def load_replies(cycle):
    replies = {}
    for path in sorted((cycle / "raw").glob("writer-*.json"), key=lambda p: int(p.stem.split("-")[1])):
        for story in json.loads(path.read_text(encoding="utf-8")).get("stories") or []:
            if isinstance(story, dict) and story.get("id"):
                replies[story["id"]] = story
    return replies


def run_with(validator, inputs, reply, evidence):
    saved = {name: getattr(newsroom, name) for name in PATCHED}
    try:
        for name in PATCHED:
            setattr(newsroom, name, getattr(validator, name))
        return newsroom._written_prose(inputs, reply, evidence)
    finally:
        for name, value in saved.items():
            setattr(newsroom, name, value)


def error_type(error):
    return error.split(":")[0].strip() if not error.startswith("title:") else "title " + error[6:].split(":")[0].strip()


def sentence_key(cycle, sid, text):
    return hashlib.sha1(f"{cycle}|{sid}|{text}".encode("utf-8")).hexdigest()[:12]


def verdict_of(output, error):
    return "written" if output else error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", default=str(ROOT / "plans" / "handoffs" / "replay-cycles"))
    parser.add_argument("--baseline", default="41e8383375b")
    parser.add_argument("--verdicts", help="JSON object: flipped sentence key -> one-line verdict")
    parser.add_argument("--out", help="also write the report to this Markdown file")
    args = parser.parse_args()
    baseline = baseline_validator(args.baseline)
    verdicts = json.loads(Path(args.verdicts).read_text(encoding="utf-8")) if args.verdicts else {}

    before, after, flipped, newly_rejected, mismatches = Counter(), Counter(), [], [], []
    stories = Counter()
    rewrite_candidates = []
    for cycle in sorted(Path(args.cycles).iterdir()):
        if not (cycle / "writer.json").exists():
            continue
        rows = json.loads((cycle / "writer.json").read_text(encoding="utf-8"))
        replies = load_replies(cycle)
        for sid, row in rows.items():
            if "writer_sources" not in row:
                continue
            reply = replies.get(sid)
            inputs, evidence = rebuild_inputs(row)
            old_out, old_dropped, old_error = run_with(baseline, inputs, reply, evidence)
            new_out, new_dropped, new_error = run_with(summary_validation, inputs, reply, evidence)
            stored = "written" if row["written"] else row["reason"]
            if (verdict_of(old_out, old_error) != stored
                    or [d.get("error") for d in old_dropped] != [d.get("error") for d in row["dropped_points"]]):
                mismatches.append((cycle.name, sid, stored, verdict_of(old_out, old_error)))
            stories["drafted"] += 1
            stories["written before"] += bool(old_out)
            stories["written after"] += bool(new_out)
            if not old_out and new_out:
                stories["newly written without rewrite"] += 1
            if new_error in newsroom.REWRITE_ERRORS:
                roles = newsroom._lost_roles(reply, new_dropped)
                rewrite_candidates.append((cycle.name, sid, f"{new_error}; one rewrite asks for: "
                                                            f"{', '.join(roles) or 'nothing (roles repeat)'}"))
            old_errors = {(d.get("role"), d["text"]): d["error"] for d in old_dropped}
            new_errors = {(d.get("role"), d["text"]): d["error"] for d in new_dropped}
            for key, error in old_errors.items():
                before[error_type(error)] += 1
            for key, error in new_errors.items():
                after[error_type(error)] += 1
            cited = {p["id"]: p["text"] for source in inputs["sources"] for p in source["paragraphs"]}
            refs_by_text = {s["text"][:400]: s.get("evidence_refs", [])
                            for p in (reply or {}).get("paragraphs") or [] for s in p.get("sentences") or []}
            title = (reply or {}).get("title_vi") or {}
            if isinstance(title, dict) and isinstance(title.get("text"), str):
                refs_by_text[title["text"][:240]] = title.get("evidence_refs", [])
            for key, error in old_errors.items():
                if key not in new_errors and key[0] != "conditions":
                    refs = refs_by_text.get(key[1], [])
                    flipped.append({"key": sentence_key(cycle.name, sid, key[1]), "cycle": cycle.name, "id": sid,
                                    "role": key[0] or "title", "error": error, "text": key[1],
                                    "cited": [(ref, cited.get(ref, "")) for ref in refs]})
            for key, error in new_errors.items():
                if old_errors.get(key) != error:
                    newly_rejected.append((cycle.name, sid, (old_errors[key] + " -> " if key in old_errors else "")
                                           + error, key[1]))

    lines = ["# Replay: summary validator, baseline vs working tree", "",
             f"Baseline `{args.baseline}`; cycles in `{Path(args.cycles).as_posix()}`. Offline, no model calls.", "",
             "## Stories", "", "| Measure | Count |", "|---|---|"]
    lines += [f"| {name} | {stories[name]} |" for name in
              ("drafted", "written before", "written after", "newly written without rewrite")]
    lines += [f"| still losing a paragraph after the fix: gets one rewrite (outcome needs a live cycle) "
              f"| {len(rewrite_candidates)} |", "",
              "## Rejected sentences per error type", "", "| Error type | Before | After |", "|---|---|---|"]
    lines += [f"| {name} | {before[name]} | {after[name]} |" for name in sorted(set(before) | set(after))]
    lines += ["", f"## Flipped from rejected to accepted ({len(flipped)})", ""]
    for item in flipped:
        lines.append(f"### `{item['key']}` {item['cycle']} / {item['id']} / {item['role']} — was `{item['error']}`")
        lines.append("")
        lines.append(f"- Verdict: {verdicts.get(item['key'], '(no verdict yet)')}")
        lines.append(f"- Writer: {item['text']}")
        for ref, text in item["cited"]:
            lines.append(f"- `{ref}`: {text}")
        lines.append("")
    lines += [f"## Newly rejected or rejected for another reason after the change ({len(newly_rejected)})", "",
              "A sentence the baseline never reached (its story stopped at the title) counts here when it fails now.", ""]
    lines += [f"- {cycle} / {sid}: `{error}` — {text}" for cycle, sid, error, text in newly_rejected] or ["- none"]
    lines += ["", f"## Rewrite candidates after the fix ({len(rewrite_candidates)})", ""]
    lines += [f"- {cycle} / {sid}: {error}" for cycle, sid, error in rewrite_candidates] or ["- none"]
    lines += ["", f"## Calibration: baseline replay vs stored verdict ({len(mismatches)} mismatches)", ""]
    lines += [f"- {cycle} / {sid}: stored `{stored}`, replay `{replayed}`"
              for cycle, sid, stored, replayed in mismatches] or ["- none: the replay reproduces every stored verdict"]
    report = "\n".join(lines) + "\n"
    sys.stdout.reconfigure(encoding="utf-8")
    print(report)
    if args.out:
        Path(args.out).write_bytes(report.encode("utf-8"))


if __name__ == "__main__":
    main()
