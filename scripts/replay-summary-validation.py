"""Replay stored newsroom writer replies through a baseline revision and the working tree.

Offline only: no model or network call. Each cycle folder (plans/handoffs/replay-cycles/<cycle>/)
holds writer.json (the desk's verdict and the source paragraphs the writer read), raw/writer-*.json
(the writer's replies) and, from cycles that ran the one-time rewrite, raw/rewrite-writer-*.json.
The script rebuilds the writer inputs from writer.json and runs phong_bao.newsroom._written_prose
once with the baseline's newsroom and summary validator (both loaded with git show) and once with
the working tree's. It prints per error type how many sentences each rejected, every sentence that
flipped from rejected to accepted (with the paragraphs it cites, so a reader can judge it), and how
many stories reach a complete summary: from the first draft alone, and after the stored rewrite reply
when a cycle has one (that reply answered the baseline's rejections, so it is evidence, not a replay
of what the working tree's prompt would get).

Calibration: the baseline run must reproduce the stored verdict of every story; mismatches are listed.
A cycle written before the baseline's validator changed cannot match, because it ran an older one.

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
import radar.summary_validation  # noqa: E402


def git_source(rev, path):
    return subprocess.run(["git", "show", f"{rev}:{path}"], cwd=ROOT, check=True,
                          capture_output=True).stdout.decode("utf-8")


def baseline_newsroom(rev):
    """newsroom.py at rev, bound to summary_validation.py at rev; other modules come from the working tree."""
    validator = types.ModuleType("radar.summary_validation")
    validator.__file__ = f"{rev}:radar/summary_validation.py"
    exec(compile(git_source(rev, "radar/summary_validation.py"), validator.__file__, "exec"), validator.__dict__)
    module = types.ModuleType("phong_bao.baseline_newsroom")
    module.__file__ = f"{rev}:phong_bao/newsroom.py"
    module.__package__ = "phong_bao"
    current = sys.modules["radar.summary_validation"]
    sys.modules["radar.summary_validation"] = validator
    try:
        exec(compile(git_source(rev, "phong_bao/newsroom.py"), module.__file__, "exec"), module.__dict__)
    finally:
        sys.modules["radar.summary_validation"] = current
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


def load_replies(cycle, prefix="writer"):
    replies = {}
    for path in sorted((cycle / "raw").glob(f"{prefix}-*.json"), key=lambda p: int(p.stem.split("-")[-1])):
        for story in json.loads(path.read_text(encoding="utf-8")).get("stories") or []:
            if isinstance(story, dict) and story.get("id"):
                replies[story["id"]] = story
    return replies


def run(module, inputs, reply, evidence, rewrite):
    """(first-draft result, result after the stored rewrite or None when no rewrite was asked or stored)."""
    first = module._written_prose(inputs, reply, evidence)
    output, dropped, error = first
    if error not in module.REWRITE_ERRORS:
        return first, None
    roles = module._lost_roles(reply, dropped)
    if not roles or rewrite is None:
        return first, None
    merged = module._merged_rewrite(reply, rewrite, roles)
    if merged is None:
        return first, (None, dropped, "rewrite_unusable")
    valid, more, final_error = module._written_prose(inputs, merged, evidence)
    return first, (valid, dropped + [item for item in more if item not in dropped], final_error)


def error_type(error):
    return error.split(":")[0].strip() if not error.startswith("title:") else "title " + error[6:].split(":")[0].strip()


def sentence_key(cycle, sid, text):
    return hashlib.sha1(f"{cycle}|{sid}|{text}".encode("utf-8")).hexdigest()[:12]


def verdict_of(result):
    output, _, error = result
    return "written" if output else error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", default=str(ROOT / "plans" / "handoffs" / "replay-cycles"))
    parser.add_argument("--baseline", default="origin/main")
    parser.add_argument("--verdicts", help="JSON object: flipped sentence key -> one-line verdict")
    parser.add_argument("--out", help="also write the report to this Markdown file")
    args = parser.parse_args()
    baseline_sha = subprocess.run(["git", "rev-parse", "--short=11", args.baseline], cwd=ROOT, check=True,
                                  capture_output=True, text=True).stdout.strip()
    baseline = baseline_newsroom(args.baseline)
    verdicts = json.loads(Path(args.verdicts).read_text(encoding="utf-8")) if args.verdicts else {}

    before, after, flipped, newly_rejected, mismatches = Counter(), Counter(), [], [], []
    stories, story_changes, rewrite_rows = Counter(), [], []
    for cycle in sorted(Path(args.cycles).iterdir()):
        if not (cycle / "writer.json").exists():
            continue
        rows = json.loads((cycle / "writer.json").read_text(encoding="utf-8"))
        replies, rewrites = load_replies(cycle), load_replies(cycle, "rewrite-writer")
        has_rewrites = any((cycle / "raw").glob("rewrite-writer-*.json"))
        for sid, row in rows.items():
            if "writer_sources" not in row:
                continue
            reply = replies.get(sid)
            inputs, evidence = rebuild_inputs(row)
            old, old_rewritten = run(baseline, inputs, reply, evidence, rewrites.get(sid))
            new, new_rewritten = run(newsroom, inputs, reply, evidence, rewrites.get(sid))
            old_final, new_final = old_rewritten or old, new_rewritten or new
            stored = "written" if row["written"] else row["reason"]
            replayed = verdict_of(old_final if has_rewrites else old)
            if replayed != stored or [d.get("error") for d in (old_final if has_rewrites else old)[1]] != [
                    d.get("error") for d in row["dropped_points"]]:
                mismatches.append((cycle.name, sid, stored, replayed))
            stories["drafted"] += 1
            stories["written from the first draft, baseline"] += bool(old[0])
            stories["written from the first draft, branch"] += bool(new[0])
            if has_rewrites:
                stories["drafted in cycles with a stored rewrite"] += 1
                stories["written after the stored rewrite, baseline"] += bool(old_final[0])
                stories["written after the stored rewrite, branch"] += bool(new_final[0])
            if bool(old_final[0]) != bool(new_final[0]) or bool(old[0]) != bool(new[0]):
                story_changes.append((cycle.name, sid, f"{verdict_of(old)} -> {verdict_of(new)}"
                                      + (f"; with stored rewrite {verdict_of(old_final)} -> {verdict_of(new_final)}"
                                         if has_rewrites else "")))
            if new[2] in newsroom.REWRITE_ERRORS:
                roles = newsroom._lost_roles(reply, new[1])
                rewrite_rows.append((cycle.name, sid, f"{new[2]}; one rewrite asks for: "
                                                      f"{', '.join(roles) or 'nothing (roles repeat)'}"
                                     + (f"; stored rewrite gives {verdict_of(new_rewritten)}" if new_rewritten else "")))
            old_errors = {(d.get("role"), d["text"]): d["error"] for d in old_final[1]}
            new_errors = {(d.get("role"), d["text"]): d["error"] for d in new_final[1]}
            for error in old_errors.values():
                before[error_type(error)] += 1
            for error in new_errors.values():
                after[error_type(error)] += 1
            cited = {p["id"]: p["text"] for source in inputs["sources"] for p in source["paragraphs"]}
            refs_by_text = {}
            for answer in (reply, rewrites.get(sid)):
                for p in (answer or {}).get("paragraphs") or []:
                    for s in p.get("sentences") or []:
                        refs_by_text[s["text"][:400]] = s.get("evidence_refs", [])
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

    lines = ["# Replay: summary validation, baseline vs working tree", "",
             f"Baseline `{args.baseline}` = `{baseline_sha}` (newsroom.py and summary_validation.py); cycles in "
             f"`{Path(args.cycles).as_posix()}`. Offline, no model calls.", "",
             "## Stories", "", "| Measure | Count |", "|---|---|"]
    lines += [f"| {name} | {count} |" for name, count in stories.items()]
    lines += ["", "## Stories whose outcome changed", ""]
    lines += [f"- {cycle} / {sid}: {change}" for cycle, sid, change in story_changes] or ["- none"]
    lines += ["", "## Rejected sentences per error type (after the stored rewrite where a cycle has one)", "",
              "| Error type | Baseline | Branch |", "|---|---|---|"]
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
    lines += [f"## Newly rejected or rejected for another reason on the branch ({len(newly_rejected)})", "",
              "A sentence the baseline never reached (its story stopped at the title) counts here when it fails now.", ""]
    lines += [f"- {cycle} / {sid}: `{error}` — {text}" for cycle, sid, error, text in newly_rejected] or ["- none"]
    lines += ["", f"## Stories still losing a paragraph on the branch: one rewrite each ({len(rewrite_rows)})", ""]
    lines += [f"- {cycle} / {sid}: {error}" for cycle, sid, error in rewrite_rows] or ["- none"]
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
