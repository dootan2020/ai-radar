"""Read stored newsroom cycles into a deterministic desk ledger and report."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .evaluation import evaluate
from .newsroom import DESKS
from .paywall import HOLD_REASON as PAYWALL_HOLD_REASON

STAMP = re.compile(r"^\d{8}T\d{6}Z$")
LOCAL = ZoneInfo("Asia/Bangkok")
SCHEDULE_LOCAL = (2, 6, 10, 14, 18, 22)
VERDICTS = {"intake": "pass", "reporter": "readable", "editor": "news",
            "checker": "verified", "writer": "written", "chief": "decision"}


def _read(path, problems, required=True):
    if not path.is_file():
        if required:
            problems[f"{path}: thiếu file"] += 1
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        problems[f"{path}: không đọc được JSON ({type(error).__name__})"] += 1
        return None


def _rows(data, path, problems):
    if isinstance(data, dict):
        return [(key, value) for key, value in sorted(data.items())]
    if isinstance(data, list):
        return [(str(index), value) for index, value in enumerate(data)]
    if data is not None:
        problems[f"{path}: cấu trúc hàng không nhận diện"] += 1
    return []


def _verdict(desk, raw):
    if desk == "chief":
        return raw if raw in ("publish", "hold") else None
    if isinstance(raw, bool):
        return "pass" if raw else "fail"
    return None


def _percent(numerator, denominator):
    return f"{numerator}/{denominator} ({100 * numerator / denominator:.1f}%)" if denominator else "không có dữ liệu"


def _quantile(values, fraction):
    if not values:
        return "không có dữ liệu"
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = int(position)
    return f"{ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (position - low):.1f}"


def _summary(counter, limit=None):
    if not counter:
        return "không có dữ liệu"
    items = sorted(counter.items(), key=lambda item: (-item[1], str(item[0])))
    return "; ".join(f"{key}: {value}" for key, value in items[:limit])


def _checker_label(row, editor, reporter, raw_reply_ids, chief):
    if not editor.get("news"):
        return "not_checked", "editor_junk" if editor.get("junk_kind") else "editor_hold"
    if not reporter.get("readable"):
        return ("not_checked", "paywall" if reporter.get("representative_status") == "paywall"
                or chief.get("reason") == PAYWALL_HOLD_REASON
                else "unreadable_source")
    if row.get("invalid_response"):
        if row.get("reason") == "checker_model_failure":
            return "checker_failure", "model_failure"
        if row.get("reason") == "checker_no_reply" or row.get("id") not in raw_reply_ids:
            return "checker_failure", "no_reply"
        return "checker_failure", "invalid_reply"
    return "checked", None


def collect(cycles_dir):
    """Return all ledger rows and source problems without changing the cycle tree."""
    root = Path(cycles_dir)
    if not root.is_dir():
        raise ValueError(f"cycles directory does not exist: {root}")
    ledger, cycles, problems = [], [], Counter()
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or not STAMP.fullmatch(folder.name):
            continue
        try:
            start = datetime.strptime(folder.name, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            problems[f"{folder.name}: dấu thời gian không hợp lệ"] += 1
            continue
        status = _read(folder / "status.json", problems)
        state = status.get("state") if isinstance(status, dict) else None
        job = _read(folder / "job" / "status.json", problems, required=state != "no_new_stories")
        decisions = _read(folder / "quyet-dinh.json", problems, required=False)
        if state is None:
            problems[f"{folder.name}/status.json: thiếu state"] += 1
        elif state not in ("running", "decided", "no_new_stories"):
            problems[f"{folder.name}/status.json: state không nhận diện ({state})"] += 1
        desks = job.get("desks") if isinstance(job, dict) else None
        if not isinstance(desks, dict) and state != "no_new_stories":
            problems[f"{folder.name}/job/status.json: thiếu desks"] += 1
            desks = {}
        elif not isinstance(desks, dict):
            desks = {}
        cycle = {"id": folder.name, "start": start, "state": state, "stories": [],
                 "desks": desks, "decisions": [],
                 "writer_retry": status.get("writer_retry") if isinstance(status, dict) else None}
        if isinstance(decisions, dict) and isinstance(decisions.get("decisions"), list):
            cycle["decisions"] = decisions["decisions"]
        elif decisions is not None:
            problems[f"{folder.name}/quyet-dinh.json: thiếu decisions"] += 1
        if state == "decided" and decisions is None:
            problems[f"{folder.name}/quyet-dinh.json: thiếu file của cycle đã quyết định"] += 1
        desk_rows = {}
        chief_data = _read(folder / "job" / "chief.json", problems,
                           required=isinstance(desks.get("chief"), dict) and desks["chief"].get("state") == "done")
        chief_rows = {row.get("id"): row for row in chief_data if isinstance(row, dict)} if isinstance(chief_data, list) else {}
        raw_reply_ids = set()
        for raw_path in sorted((folder / "job" / "raw").glob("checker-*.json")):
            raw = _read(raw_path, problems, required=False)
            if isinstance(raw, dict):
                replies = raw.get("stories")
                if isinstance(replies, list):
                    raw_reply_ids.update(item.get("id") for item in replies if isinstance(item, dict))
        for desk in DESKS:
            meta = desks.get(desk)
            path = folder / "job" / f"{desk}.json"
            data = (chief_data if desk == "chief" else
                    _read(path, problems, required=isinstance(meta, dict) and meta.get("state") == "done"))
            desk_rows[desk] = data if isinstance(data, dict) else {}
            if isinstance(meta, dict):
                if meta.get("state") not in ("running", "done"):
                    problems[f"job/status.json/{desk}: state không nhận diện"] += 1
                if meta.get("state") == "done" and "seconds" not in meta:
                    problems[f"job/status.json/{desk}: thiếu seconds"] += 1
                batches = meta.get("batches", [])
                if not isinstance(batches, list):
                    problems[f"{folder.name}/job/status.json/{desk}: batches không hợp lệ"] += 1
                    batches = []
                tokens = defaultdict(lambda: {"input": 0, "output": 0})
                for batch in batches:
                    if not isinstance(batch, dict) or not isinstance(batch.get("provider"), str):
                        problems[f"{folder.name}/job/status.json/{desk}: batch thiếu provider"] += 1
                        continue
                    provider = batch["provider"]
                    for key, target in (("input_tokens", "input"), ("output_tokens", "output")):
                        value = batch.get(key)
                        if isinstance(value, int) and not isinstance(value, bool):
                            tokens[provider][target] += value
                        else:
                            problems[f"{folder.name}/job/status.json/{desk}: batch thiếu {key}"] += 1
                ledger.append({"type": "desk", "cycle": folder.name, "cycle_start": start.isoformat(),
                               "desk": desk, "state": meta.get("state"), "seconds": meta.get("seconds"),
                               "tokens_by_provider": dict(sorted(tokens.items())),
                               "invalid_rows": meta.get("invalid_rows"),
                               "model_failures": meta.get("model_failures"),
                               "budget_exhausted": meta.get("budget_exhausted")})
            for key, row in _rows(data, path, problems):
                if not isinstance(row, dict):
                    problems[f"{folder.name}/job/{desk}.json: hàng {key} không phải object"] += 1
                    continue
                sid = row.get("id", key if isinstance(data, dict) else None)
                if not isinstance(sid, str) or not sid:
                    problems[f"{folder.name}/job/{desk}.json: hàng {key} thiếu id"] += 1
                    continue
                field = VERDICTS[desk]
                if "reason" not in row:
                    problems[f"{folder.name}/job/{desk}.json: thiếu reason"] += 1
                if desk == "chief" and not isinstance(row.get("source_url"), str):
                    problems[f"{folder.name}/job/chief.json: thiếu source_url"] += 1
                if field not in row:
                    problems[f"{folder.name}/job/{desk}.json: thiếu {field}"] += 1
                raw = row.get(field)
                verdict = _verdict(desk, raw)
                if raw is not None and verdict is None:
                    problems[f"{folder.name}/job/{desk}.json: {field} không nhận diện"] += 1
                entry = {"type": "story", "cycle": folder.name, "cycle_start": start.isoformat(),
                         "desk": desk, "story_id": sid, "provider": row.get("provider"),
                         "boat": row.get("boat"), "verdict": verdict, "verdict_raw": raw,
                         "reason": row.get("reason"), "invalid_response": row.get("invalid_response"),
                         "tier_capped": row.get("tier_capped"),
                         "degradation_reasons": row.get("degradation_reasons"),
                         "rejected_claim_count": len(row["rejected_claims"]) if isinstance(row.get("rejected_claims"), list) else None,
                         "writer_status": row.get("status", "written" if row.get("written") is True else row.get("reason") if desk == "writer" else None),
                         "importance_tier": row.get("importance_tier"),
                         "source_url": row.get("source_url") or row.get("selected_url"),
                         "title_vi": row.get("editorial_headline_vi"), "rewrite": row.get("rewrite")}
                if desk == "checker":
                    label, skip_reason = _checker_label(row, desk_rows["editor"].get(sid, {}),
                                                        desk_rows["reporter"].get(sid, {}), raw_reply_ids,
                                                        chief_rows.get(sid, {}))
                    entry["check_status"] = label
                    entry["skip_reason"] = skip_reason if label == "not_checked" else row.get("skip_reason")
                    if label == "not_checked":
                        entry["reason"] = "checker_not_checked"
                        entry["invalid_response"] = False
                ledger.append(entry)
                cycle["stories"].append(entry)
        checker_stories = [row for row in cycle["stories"] if row["desk"] == "checker"]
        for entry in ledger:
            if entry["type"] == "desk" and entry["cycle"] == folder.name and entry["desk"] == "checker":
                entry["invalid_rows"] = sum(row["check_status"] == "checker_failure" for row in checker_stories)
                entry["not_checked_rows"] = sum(row["check_status"] == "not_checked" for row in checker_stories)
                break
        cycles.append(cycle)
    return ledger, cycles, problems


def _sample(cycles):
    groups = defaultdict(list)
    for cycle in cycles:
        writers = {row["story_id"]: row for row in cycle["stories"] if row["desk"] == "writer"}
        for decision in cycle["decisions"]:
            if not isinstance(decision, dict) or not isinstance(decision.get("id"), str):
                continue
            writer = writers.get(decision["id"], {})
            if writer.get("writer_status") == "insufficient_evidence":
                category = "writer-insufficient"
            elif decision.get("decision") == "hold":
                category = "held"
            elif decision.get("decision") == "publish" and decision.get("tier_capped") is True:
                category = "published-capped"
            elif decision.get("decision") == "publish" and decision.get("importance_tier") == "top":
                category = "published-top"
            else:
                continue
            groups[category].append((cycle["id"], decision, writer))
    allocation = {"published-top": 2, "published-capped": 3, "held": 3, "writer-insufficient": 2}
    chosen = []
    for category, count in allocation.items():
        candidates = sorted(groups[category], key=lambda item: (not bool(item[2].get("title_vi")), item[0], item[1]["id"]))
        chosen.extend((category, *item) for item in candidates[:count])
    if len(chosen) < 10:
        used = {(item[1], item[2]["id"]) for item in chosen}
        for category in allocation:
            for item in groups[category]:
                if len(chosen) == 10:
                    break
                if (item[0], item[1]["id"]) not in used:
                    chosen.append((category, *item))
                    used.add((item[0], item[1]["id"]))
    return chosen


def report(month, cycles, problems, labels=None, decisions_path=None, now=None):
    selected = [cycle for cycle in cycles if cycle["start"].astimezone(LOCAL).strftime("%Y-%m") == month]
    lines = [f"# Báo cáo sổ bàn {month}", "", "## Lịch và kết quả cycle", ""]
    if selected:
        first = datetime.strptime(month, "%Y-%m").replace(tzinfo=LOCAL) + timedelta(hours=2)
        month_start = first.replace(day=1, hour=0)
        month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        horizon = min(now or datetime.now(LOCAL), month_end) - timedelta(microseconds=1)
        # Every scheduled slot of the month up to the horizon, across all days so far.
        # Between midnight and the day's first slot the latest slot belongs to the previous day.
        expected = set()
        day = month_start
        while day <= horizon:
            expected.update(slot for slot in (day.replace(hour=h) for h in SCHEDULE_LOCAL) if slot <= horizon)
            day += timedelta(days=1)
        last = max(expected, default=first)
        present = {c["start"].astimezone(LOCAL).replace(minute=0, second=0, microsecond=0) for c in selected}
        completed = sum(c["state"] in ("decided", "no_new_stories") for c in selected)
        interrupted = [c["id"] for c in selected if c["state"] == "running"]
        lines += [f"Khung 02, 06, 10, 14, 18, 22 giờ (+07), từ {first.isoformat()} đến {last.isoformat()}.",
                  f"Kỳ vọng: {len(expected)}; có cycle: {len(selected)}; đúng khung: {len(expected & present)}; hoàn tất: {completed}; đang dở: {len(interrupted)}.",
                  f"Khung vắng: {', '.join(x.isoformat() for x in sorted(expected - present)) or 'không có'}.",
                  f"Cycle đang dở: {', '.join(interrupted) or 'không có'}.", ""]
    else:
        lines += ["Không có cycle trong tháng này.", ""]
    for desk in DESKS:
        stories = [s for c in selected for s in c["stories"] if s["desk"] == desk]
        metas = [c["desks"][desk] for c in selected if isinstance(c["desks"].get(desk), dict)]
        outcomes = Counter(s["verdict"] for s in stories if s["verdict"] is not None)
        reasons = Counter(str(s["reason"]) for s in stories if isinstance(s["reason"], str) and s["reason"])
        invalid = (sum(s["check_status"] == "checker_failure" for s in stories) if desk == "checker" else
                   sum(m["invalid_rows"] for m in metas if isinstance(m.get("invalid_rows"), int)))
        failures = sum(len(m["model_failures"]) for m in metas if isinstance(m.get("model_failures"), list))
        exhausted = sum(m.get("budget_exhausted") is True for m in metas)
        tokens = defaultdict(lambda: [0, 0])
        seconds = defaultdict(list)
        for meta in metas:
            providers = set()
            for batch in meta.get("batches", []):
                if isinstance(batch, dict) and isinstance(batch.get("provider"), str):
                    provider = batch["provider"]
                    providers.add(provider)
                    for index, key in enumerate(("input_tokens", "output_tokens")):
                        if isinstance(batch.get(key), int):
                            tokens[provider][index] += batch[key]
            if len(providers) == 1 and isinstance(meta.get("seconds"), (int, float)):
                seconds[next(iter(providers))].append(meta["seconds"])
        lines += [f"## {desk}", "", f"Tin xử lý: {len(stories)}. Kết quả: {_summary(outcomes)}.",
                  f"5 lý do thường gặp: {_summary(reasons, 5)}.",
                  f"Hàng lỗi: {invalid}; lỗi model: {failures}; hết budget: {exhausted}."]
        if desk == "checker":
            skipped = Counter(s["skip_reason"] for s in stories if s["check_status"] == "not_checked")
            lines.append(f"Chưa gửi kiểm: {sum(skipped.values())} ({_summary(skipped)}); lỗi kiểm chứng: {invalid}.")
        if tokens:
            for provider in sorted(tokens):
                durations = seconds[provider]
                lines.append(f"{provider}: token vào/ra {tokens[provider][0]}/{tokens[provider][1]}; p50/p95 giây {_quantile(durations, .5)}/{_quantile(durations, .95)} (n={len(durations)}).")
        else:
            lines.append("Token và thời gian theo provider: không có dữ liệu.")
        lines.append("")
    chief = [s for c in selected for s in c["stories"] if s["desk"] == "chief"]
    published = [s for s in chief if s["verdict"] == "publish"]
    held = [s for s in chief if s["verdict"] == "hold"]
    domains = defaultdict(Counter)
    for story in chief:
        if story["verdict"] in ("publish", "hold") and isinstance(story["source_url"], str):
            domain = urlsplit(story["source_url"]).hostname
            if domain:
                domains[domain.lower()][story["verdict"]] += 1
    caps = Counter(str(s["importance_tier"]) for s in chief if s["tier_capped"] is True)
    degradations = Counter(reason for s in chief if isinstance(s["degradation_reasons"], list)
                           for reason in s["degradation_reasons"] if isinstance(reason, str))
    lines += ["## Quyết định và nguồn", "", f"Publish: {_percent(len(published), len(published) + len(held))}; hold: {_percent(len(held), len(published) + len(held))}.",
              f"Lý do hold: {_summary(Counter(str(s['reason']) for s in held if s['reason']), 5)}.",
              f"Tier bị giới hạn: {_summary(caps)}. Lý do giảm cấp: {_summary(degradations, 5)}.", "",
              "| Domain | Publish | Hold |", "| --- | ---: | ---: |"]
    ranked_domains = sorted(domains.items(), key=lambda item: (-(item[1]["publish"] + item[1]["hold"]), item[0]))
    lines += [f"| {domain} | {counts['publish']} | {counts['hold']} |" for domain, counts in ranked_domains[:15]]
    if len(ranked_domains) > 15:
        rest = Counter()
        for _, counts in ranked_domains[15:]:
            rest.update(counts)
        lines.append(f"| Các domain còn lại ({len(ranked_domains) - 15}) | {rest['publish']} | {rest['hold']} |")
    if not domains:
        lines.append("| không có dữ liệu | | |")
    writers = [s for c in selected for s in c["stories"] if s["desk"] == "writer"]
    eligible = [s for s in writers if s["writer_status"] != "not publishable with a readable source" and s["writer_status"] != "outside writer window"]
    insufficient = sum(s["writer_status"] == "insufficient_evidence" for s in eligible)
    retries = sum(isinstance(s["rewrite"], dict) for s in writers)
    retry_cycles = sum(c["writer_retry"].get("sent", 0) for c in selected
                       if isinstance(c["writer_retry"], dict) and isinstance(c["writer_retry"].get("sent", 0), int))
    checkers = [s for c in selected for s in c["stories"] if s["desk"] == "checker"]
    known_claims = [s for s in checkers if s["rejected_claim_count"] is not None]
    rejected = sum(s["rejected_claim_count"] > 0 for s in known_claims)
    lines += ["", "## Writer và checker", "",
              f"Writer insufficient_evidence: {_percent(insufficient, len(eligible))} trên các hàng đủ điều kiện; hàng có rewrite: {retries}; retry được ghi trong trạng thái: {retry_cycles}.",
              f"Checker có claim bị bác: {_percent(rejected, len(known_claims))} trên các hàng có danh sách rejected_claims.", "",
              "## Mẫu tin để đọc", ""]
    for category, cycle_id, decision, writer in _sample(selected):
        title = writer.get("title_vi") or "không có tiêu đề tiếng Việt trong cycle"
        lines += [f"- **{category} · {cycle_id} · {decision['id']}** — {title}",
                  f"  Nguồn: {decision.get('source_url') or 'không có dữ liệu'}. Quyết định: {decision.get('decision') or 'không có dữ liệu'}. Lý do: {decision.get('reason') or 'không có dữ liệu'}." ]
    if labels:
        try:
            result = evaluate(decisions_path, labels)
            lines += ["", "## Đối chiếu nhãn", "", "```json", json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), "```"]
        except (OSError, ValueError, KeyError, TypeError) as error:
            problems[f"labels: evaluate không chạy được ({type(error).__name__}: {error})"] += 1
    lines += ["", "## Dữ liệu không đọc được", ""]
    lines.append("Các vấn đề dưới đây thuộc toàn bộ lịch sử đã đọc, kể cả cycle ngoài tháng báo cáo.")
    if not problems:
        lines.append("Không có.")
    else:
        lines.append(f"Tổng vấn đề: {sum(problems.values())}.")
        lines += [f"- {key} ({count})" for key, count in sorted(problems.items())]
    return "\n".join(lines) + "\n"


def run(cycles_dir, out_dir, month=None, labels=None, now=None):
    ledger, cycles, problems = collect(cycles_dir)
    if month is None:
        if not cycles:
            raise ValueError("no cycle folders found; pass --month explicitly")
        month = max(c["start"] for c in cycles).astimezone(LOCAL).strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise ValueError("month must be YYYY-MM")
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "so-ban.jsonl").write_bytes("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in ledger).encode("utf-8"))
    selected = [cycle for cycle in cycles if cycle["start"].astimezone(LOCAL).strftime("%Y-%m") == month]
    domain_totals = defaultdict(Counter)
    for cycle in selected:
        for story in cycle["stories"]:
            if story["desk"] == "chief" and story["verdict"] in ("publish", "hold") and isinstance(story["source_url"], str):
                domain = urlsplit(story["source_url"]).hostname
                if domain:
                    domain_totals[domain.lower()][story["verdict"]] += 1
    csv_lines = ["domain,publish,hold"]
    csv_lines.extend(f'{json.dumps(domain, ensure_ascii=False)},{counts["publish"]},{counts["hold"]}'
                     for domain, counts in sorted(domain_totals.items()))
    (output / "so-ban-domains.csv").write_text("\n".join(csv_lines) + "\n", encoding="utf-8", newline="\n")
    decisions_path = output / "quyet-dinh-evaluate.json"
    try:
        if labels:
            label_data = _read(Path(labels), problems)
            label_rows = label_data.get("stories") if isinstance(label_data, dict) else label_data
            if isinstance(label_rows, list):
                ids = {row.get("id") for row in label_rows if isinstance(row, dict)}
                latest = {row["id"]: row for cycle in cycles for row in cycle["decisions"]
                          if isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"] in ids}
                decisions_path.write_bytes(json.dumps({"decisions": list(latest.values())}, ensure_ascii=False).encode("utf-8"))
        path = output / f"bao-cao-{month}.md"
        path.write_bytes(report(month, cycles, problems, labels, decisions_path, now).encode("utf-8"))
    finally:
        if decisions_path.exists():
            decisions_path.unlink()
    return path
